"""Tests for the quality pipeline: pairwise scoring, bias detection, calibration.

Phase 5, Pillar 1: Judge Bias Mitigation — quality_pipeline.py.

Tests cover:
- PairwiseScorer: position-randomized comparison, agreement requirement
- BiasDetector: position bias (n>=5), verbosity bias (n>=5), self-preference (n>=5)
- HumanCalibration: Spearman correlation against golden set, halt on uncalibrated
- ConfidenceInterval: bootstrap sampling on scores, CI width
"""

import pytest

from apps.api.src.telemetry.quality_pipeline import (
    BiasDetector,
    BootstrapCI,
    ComparisonResult,
    HumanCalibration,
    PairwiseScorer,
    compute_bootstrap_ci,
)

# =========================================================================
# PairwiseScorer tests
# =========================================================================


class TestComparisonResult:
    """Tests for the ComparisonResult model."""

    def test_agreement_both_pick_a(self):
        """Both rounds agree A wins -> valid result."""
        result = ComparisonResult(
            query="What is the penalty?",
            answer_a="15% penalty",
            answer_b="10% penalty",
            round1_winner="A",
            round2_winner="A",
        )
        assert result.is_consistent is True
        assert result.winner == "A"
        assert result.position_bias_detected is False

    def test_agreement_both_pick_b(self):
        """Both rounds agree B wins -> valid result."""
        result = ComparisonResult(
            query="What is the penalty?",
            answer_a="10% penalty",
            answer_b="15% penalty",
            round1_winner="B",
            round2_winner="B",
        )
        assert result.is_consistent is True
        assert result.winner == "B"
        assert result.position_bias_detected is False

    def test_disagreement_position_bias(self):
        """Round 1 picks A, Round 2 picks A (but A was swapped) -> position bias."""
        # In round 1: A is first, B is second -> judge picks A (first)
        # In round 2: B is first, A is second -> if judge picks B (first), bias
        # The comparison result stores this as round1_winner=A, round2_winner=B
        # which means both rounds picked whatever was in position 1 -> bias
        result = ComparisonResult(
            query="What is the penalty?",
            answer_a="15% penalty",
            answer_b="10% penalty",
            round1_winner="A",
            round2_winner="B",
        )
        assert result.is_consistent is False
        assert result.winner is None
        assert result.position_bias_detected is True

    def test_tie_round1_a_round2_b_is_bias(self):
        """Round1=A, Round2=B means each round picked whatever was first."""
        result = ComparisonResult(
            query="test",
            answer_a="short",
            answer_b="long verbose answer",
            round1_winner="A",
            round2_winner="B",
        )
        assert result.position_bias_detected is True

    def test_tie_explicit(self):
        """Both rounds say tie -> valid tie."""
        result = ComparisonResult(
            query="test",
            answer_a="answer 1",
            answer_b="answer 2",
            round1_winner="TIE",
            round2_winner="TIE",
        )
        assert result.is_consistent is True
        assert result.winner == "TIE"
        assert result.position_bias_detected is False


class TestPairwiseScorer:
    """Tests for PairwiseScorer with position-swap agreement requirement."""

    def test_consistent_a_wins(self):
        """Judge function consistently picks the correct answer."""

        def mock_judge(query: str, first: str, second: str) -> str:
            # Always picks the one containing "15%"
            if "15%" in first:
                return "A"
            return "B"

        scorer = PairwiseScorer(judge_fn=mock_judge)
        result = scorer.compare(
            query="What is the penalty?",
            answer_a="15% penalty per incident",
            answer_b="10% penalty per incident",
        )
        assert result.is_consistent is True
        assert result.winner == "A"

    def test_position_biased_judge_detected(self):
        """Judge always picks first option -> position bias detected."""

        def biased_judge(query: str, first: str, second: str) -> str:
            return "A"  # Always picks first

        scorer = PairwiseScorer(judge_fn=biased_judge)
        result = scorer.compare(
            query="What is the penalty?",
            answer_a="15% penalty",
            answer_b="10% penalty",
        )
        assert result.position_bias_detected is True
        assert result.winner is None

    def test_consistent_b_wins(self):
        """Judge consistently picks B across both rounds."""

        def mock_judge(query: str, first: str, second: str) -> str:
            # Always picks the one containing "correct"
            if "correct" in second:
                return "B"
            return "A"

        scorer = PairwiseScorer(judge_fn=mock_judge)
        result = scorer.compare(
            query="test question",
            answer_a="wrong answer",
            answer_b="correct answer",
        )
        assert result.is_consistent is True
        assert result.winner == "B"

    def test_tie_consistent(self):
        """Judge says tie both times -> valid tie."""

        def tie_judge(query: str, first: str, second: str) -> str:
            return "TIE"

        scorer = PairwiseScorer(judge_fn=tie_judge)
        result = scorer.compare(
            query="test", answer_a="same quality", answer_b="same quality"
        )
        assert result.is_consistent is True
        assert result.winner == "TIE"

    def test_scorer_stores_query_and_answers(self):
        """Result contains the original query and answers."""

        def mock_judge(query: str, first: str, second: str) -> str:
            return "A"

        scorer = PairwiseScorer(judge_fn=mock_judge)
        result = scorer.compare(
            query="my query", answer_a="answer A", answer_b="answer B"
        )
        assert result.query == "my query"
        assert result.answer_a == "answer A"
        assert result.answer_b == "answer B"

    def test_batch_compare_multiple_queries(self):
        """Batch comparison across multiple query-answer pairs."""
        call_count = 0

        def mock_judge(query: str, first: str, second: str) -> str:
            nonlocal call_count
            call_count += 1
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        scorer = PairwiseScorer(judge_fn=mock_judge)
        pairs = [
            ("q1", "correct a1", "wrong b1"),
            ("q2", "wrong a2", "correct b2"),
            ("q3", "equal a3", "equal b3"),
        ]
        results = scorer.batch_compare(pairs)
        assert len(results) == 3
        # Each comparison calls judge twice (position swap)
        assert call_count == 6


# =========================================================================
# BiasDetector tests — position bias (n>=5)
# =========================================================================


class TestBiasDetectorPositionBias:
    """Position bias: measure disagreement rate when swapping A/B order.

    n>=5 test scenarios to satisfy benchmark depth requirements.
    """

    def test_zero_position_bias(self):
        """All comparisons consistent -> 0% position bias rate."""

        def consistent_judge(query: str, first: str, second: str) -> str:
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=consistent_judge)
        pairs = [
            ("q1", "correct a", "wrong b"),
            ("q2", "wrong a", "correct b"),
            ("q3", "correct a", "wrong b"),
            ("q4", "wrong a", "correct b"),
            ("q5", "correct a", "wrong b"),
        ]
        result = detector.detect_position_bias(pairs)
        assert result == 0.0

    def test_full_position_bias(self):
        """Judge always picks first -> 100% position bias rate."""

        def biased_judge(query: str, first: str, second: str) -> str:
            return "A"

        detector = BiasDetector(judge_fn=biased_judge)
        pairs = [
            ("q1", "a1", "b1"),
            ("q2", "a2", "b2"),
            ("q3", "a3", "b3"),
            ("q4", "a4", "b4"),
            ("q5", "a5", "b5"),
        ]
        result = detector.detect_position_bias(pairs)
        assert result == 1.0

    def test_partial_position_bias(self):
        """Some comparisons show bias, some are consistent."""
        call_idx = 0

        def mixed_judge(query: str, first: str, second: str) -> str:
            nonlocal call_idx
            call_idx += 1
            # First 2 queries: always pick first (biased)
            # Last 3 queries: pick based on content (unbiased)
            if call_idx <= 4:  # 2 queries x 2 rounds = 4 calls
                return "A"
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=mixed_judge)
        pairs = [
            ("q1", "a1", "b1"),  # biased
            ("q2", "a2", "b2"),  # biased
            ("q3", "correct a", "wrong b"),  # consistent
            ("q4", "wrong a", "correct b"),  # consistent
            ("q5", "correct a", "wrong b"),  # consistent
        ]
        result = detector.detect_position_bias(pairs)
        assert result == pytest.approx(0.4)  # 2/5

    def test_position_bias_with_ties(self):
        """Ties are consistent (not biased)."""

        def tie_judge(query: str, first: str, second: str) -> str:
            return "TIE"

        detector = BiasDetector(judge_fn=tie_judge)
        pairs = [
            ("q1", "a1", "b1"),
            ("q2", "a2", "b2"),
            ("q3", "a3", "b3"),
            ("q4", "a4", "b4"),
            ("q5", "a5", "b5"),
        ]
        result = detector.detect_position_bias(pairs)
        assert result == 0.0

    def test_position_bias_single_biased_in_five(self):
        """1 out of 5 comparisons shows position bias -> 20% rate."""
        call_idx = 0

        def mostly_fair_judge(query: str, first: str, second: str) -> str:
            nonlocal call_idx
            call_idx += 1
            # First query: biased (picks first both times)
            if call_idx <= 2:
                return "A"
            # Rest: always picks answer containing "correct"
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=mostly_fair_judge)
        pairs = [
            ("q1", "wrong a", "wrong b"),  # biased (both rounds pick A)
            ("q2", "correct a", "wrong b"),  # consistent
            ("q3", "wrong a", "correct b"),  # consistent
            ("q4", "correct a", "wrong b"),  # consistent
            ("q5", "wrong a", "correct b"),  # consistent
        ]
        result = detector.detect_position_bias(pairs)
        assert result == pytest.approx(0.2)  # 1/5


# =========================================================================
# BiasDetector tests — verbosity bias (n>=5)
# =========================================================================


class TestBiasDetectorVerbosityBias:
    """Verbosity bias: judge prefers longer answers regardless of quality.

    n>=5 test scenarios. Each presents a short correct answer vs
    a long wrong answer. If the judge picks the long one, verbosity bias.
    """

    def test_no_verbosity_bias(self):
        """Judge picks correct answer regardless of length -> 0% bias."""

        def quality_judge(query: str, first: str, second: str) -> str:
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=quality_judge)
        pairs = [
            ("q1", "correct short", "wrong but very long verbose detailed answer"),
            ("q2", "correct brief", "wrong extended elaborate comprehensive response"),
            ("q3", "correct", "wrong and unnecessarily wordy explanation here"),
            ("q4", "correct concise", "wrong with many many extra filler words added"),
            ("q5", "correct compact", "wrong with excessive verbosity and padding"),
        ]
        result = detector.detect_verbosity_bias(pairs)
        assert result == 0.0

    def test_full_verbosity_bias(self):
        """Judge always picks longer answer -> 100% verbosity bias."""

        def verbose_judge(query: str, first: str, second: str) -> str:
            if len(first) >= len(second):
                return "A"
            return "B"

        detector = BiasDetector(judge_fn=verbose_judge)
        # Short correct answers in position A, long wrong in B
        pairs = [
            ("q1", "15%", "The penalty is approximately ten percent of the total"),
            ("q2", "Yes", "Based on the comprehensive analysis of all factors"),
            ("q3", "42", "The answer to this question involves many calculations"),
            ("q4", "No", "After careful consideration of multiple viewpoints"),
            ("q5", "EUR 5k", "The monetary amount totals five thousand euros"),
        ]
        result = detector.detect_verbosity_bias(pairs)
        assert result == 1.0

    def test_partial_verbosity_bias(self):
        """Some comparisons show verbosity preference, some don't."""

        def mixed_judge(query: str, first: str, second: str) -> str:
            # Sometimes picks longer, sometimes picks correct
            if "correct" in first and len(first) < len(second):
                # Short correct vs long wrong — 50% of the time picks long
                if "q1" in query or "q3" in query:
                    return "B"  # verbosity bias
                return "A"  # correct
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=mixed_judge)
        pairs = [
            ("q1", "correct short", "wrong long verbose answer here"),
            ("q2", "correct short", "wrong long verbose answer here"),
            ("q3", "correct short", "wrong long verbose answer here"),
            ("q4", "correct short", "wrong long verbose answer here"),
            ("q5", "correct short", "wrong long verbose answer here"),
        ]
        result = detector.detect_verbosity_bias(pairs)
        assert 0.0 < result < 1.0

    def test_verbosity_bias_with_equal_length(self):
        """Equal length answers cannot trigger verbosity bias."""

        def fair_judge(query: str, first: str, second: str) -> str:
            return "A"

        detector = BiasDetector(judge_fn=fair_judge)
        pairs = [
            ("q1", "answer A here", "answer B here"),
            ("q2", "response one", "response two"),
            ("q3", "option alpha", "option bravo"),
            ("q4", "result first", "result other"),
            ("q5", "output check", "output value"),
        ]
        # When lengths are similar, verbosity bias test is N/A — returns 0
        result = detector.detect_verbosity_bias(pairs)
        assert result == 0.0

    def test_verbosity_bias_rate_calculation(self):
        """Rate = (biased picks) / (total pairs where short was correct)."""
        judge_calls = []

        def tracking_judge(query: str, first: str, second: str) -> str:
            judge_calls.append((query, first, second))
            # Always picks the longer answer
            if len(first) >= len(second):
                return "A"
            return "B"

        detector = BiasDetector(judge_fn=tracking_judge)
        pairs = [
            ("q1", "short correct", "long wrong answer with many words"),
            ("q2", "short correct", "long wrong answer with many words"),
            ("q3", "short correct", "long wrong answer with many words"),
            ("q4", "short correct", "long wrong answer with many words"),
            ("q5", "short correct", "long wrong answer with many words"),
        ]
        result = detector.detect_verbosity_bias(pairs)
        # All 5 pairs: short answer A is correct, long answer B is wrong
        # Judge picks B (longer) every time = 100% verbosity bias
        assert result == 1.0


# =========================================================================
# BiasDetector tests — self-preference bias (n>=5)
# =========================================================================


class TestBiasDetectorSelfPreference:
    """Self-preference: judge prefers outputs from its own model family.

    n>=5 test scenarios. Compares scoring when the answer is labeled as
    coming from the judge's family vs a different family.
    """

    def test_no_self_preference(self):
        """Judge scores same-family and cross-family equally -> 0% bias.

        A fair judge picks evenly between same-family and cross-family answers.
        With an even split (same picks A half the time, B half the time),
        self-preference rate should be 0.
        """

        def fair_judge(query: str, first: str, second: str) -> str:
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=fair_judge)
        # Even split: 3 where same-family wins, 3 where cross-family wins
        same_family_pairs = [
            ("q1", "correct from gpt", "wrong from claude"),     # picks A (same)
            ("q2", "wrong from gpt", "correct from claude"),     # picks B (cross)
            ("q3", "correct from gpt", "wrong from claude"),     # picks A (same)
            ("q4", "wrong from gpt", "correct from claude"),     # picks B (cross)
            ("q5", "correct from gpt", "wrong from claude"),     # picks A (same)
            ("q6", "wrong from gpt", "correct from claude"),     # picks B (cross)
        ]
        result = detector.detect_self_preference(same_family_pairs)
        assert result == 0.0

    def test_full_self_preference(self):
        """Judge always picks same-family answer -> 100% self-preference."""

        def self_pref_judge(query: str, first: str, second: str) -> str:
            # Always picks whichever is labeled "same_family"
            if "same_family" in first:
                return "A"
            if "same_family" in second:
                return "B"
            return "A"

        detector = BiasDetector(judge_fn=self_pref_judge)
        # Answer A is always the same-family answer (labeled)
        pairs = [
            ("q1", "same_family answer 1", "cross_family answer 1"),
            ("q2", "same_family answer 2", "cross_family answer 2"),
            ("q3", "same_family answer 3", "cross_family answer 3"),
            ("q4", "same_family answer 4", "cross_family answer 4"),
            ("q5", "same_family answer 5", "cross_family answer 5"),
        ]
        result = detector.detect_self_preference(pairs)
        assert result == 1.0

    def test_partial_self_preference(self):
        """Judge shows some self-preference, not total."""
        call_count = 0

        def partial_judge(query: str, first: str, second: str) -> str:
            nonlocal call_count
            call_count += 1
            # Picks same_family 3 out of 5 times, cross_family 2 out of 5
            if call_count <= 3:
                if "same_family" in first:
                    return "A"
                return "B"
            # Last 2: fair
            if "better" in first:
                return "A"
            if "better" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=partial_judge)
        pairs = [
            ("q1", "same_family answer", "cross_family better"),
            ("q2", "same_family answer", "cross_family better"),
            ("q3", "same_family answer", "cross_family better"),
            ("q4", "same_family answer", "cross_family better"),
            ("q5", "same_family answer", "cross_family better"),
        ]
        result = detector.detect_self_preference(pairs)
        assert 0.0 < result < 1.0

    def test_self_preference_equal_quality(self):
        """When answers are equal quality, self-preference should be ~0.5."""

        def random_judge(query: str, first: str, second: str) -> str:
            return "TIE"

        detector = BiasDetector(judge_fn=random_judge)
        pairs = [
            ("q1", "same_family equal", "cross_family equal"),
            ("q2", "same_family equal", "cross_family equal"),
            ("q3", "same_family equal", "cross_family equal"),
            ("q4", "same_family equal", "cross_family equal"),
            ("q5", "same_family equal", "cross_family equal"),
        ]
        result = detector.detect_self_preference(pairs)
        # All ties -> no self-preference
        assert result == 0.0

    def test_self_preference_five_of_five(self):
        """5 out of 5 picks same-family -> 100% rate."""

        def full_bias(query: str, first: str, second: str) -> str:
            return "A"  # Always picks first (same_family is first)

        detector = BiasDetector(judge_fn=full_bias)
        pairs = [
            ("q1", "same_family", "cross_family"),
            ("q2", "same_family", "cross_family"),
            ("q3", "same_family", "cross_family"),
            ("q4", "same_family", "cross_family"),
            ("q5", "same_family", "cross_family"),
        ]
        result = detector.detect_self_preference(pairs)
        assert result == 1.0


# =========================================================================
# BiasDetector — full bias report
# =========================================================================


class TestBiasDetectorFullReport:
    """Tests for the full bias report combining all three bias types."""

    def test_full_report_returns_judge_bias_result(self):
        """Full report returns a JudgeBiasResult with all fields populated."""

        def fair_judge(query: str, first: str, second: str) -> str:
            if "correct" in first:
                return "A"
            if "correct" in second:
                return "B"
            return "TIE"

        detector = BiasDetector(judge_fn=fair_judge)
        position_pairs = [
            ("q1", "correct a", "wrong b"),
            ("q2", "wrong a", "correct b"),
            ("q3", "correct a", "wrong b"),
            ("q4", "wrong a", "correct b"),
            ("q5", "correct a", "wrong b"),
        ]
        verbosity_pairs = [
            ("q1", "correct short", "wrong long verbose answer here"),
            ("q2", "correct brief", "wrong extended elaborate response"),
            ("q3", "correct", "wrong unnecessarily wordy explanation"),
            ("q4", "correct concise", "wrong many extra filler words"),
            ("q5", "correct compact", "wrong excessive verbosity padding"),
        ]
        self_pref_pairs = [
            ("q1", "correct from same", "wrong from cross"),
            ("q2", "wrong from same", "correct from cross"),
            ("q3", "correct from same", "wrong from cross"),
            ("q4", "wrong from same", "correct from cross"),
            ("q5", "correct from same", "wrong from cross"),
        ]

        result = detector.full_bias_report(
            position_pairs=position_pairs,
            verbosity_pairs=verbosity_pairs,
            self_preference_pairs=self_pref_pairs,
            spearman_correlation=0.90,
        )

        from apps.api.src.domain.telemetry import JudgeBiasResult

        assert isinstance(result, JudgeBiasResult)
        assert result.position_bias_rate >= 0.0
        assert result.verbosity_bias_rate >= 0.0
        assert result.self_preference_rate >= 0.0
        assert result.spearman_correlation == 0.90
        assert result.total_comparisons == 15  # 5+5+5


# =========================================================================
# HumanCalibration tests — Spearman correlation
# =========================================================================


class TestHumanCalibration:
    """Tests for human vs LLM judge calibration using Spearman correlation."""

    def test_perfect_correlation(self):
        """Human and judge scores identical -> Spearman = 1.0."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        judge_scores = [1.0, 2.0, 3.0, 4.0, 5.0]

        calibration = HumanCalibration(min_correlation=0.85)
        result = calibration.compute_correlation(human_scores, judge_scores)
        assert result == pytest.approx(1.0)

    def test_perfect_inverse_correlation(self):
        """Perfectly opposite scores -> Spearman = -1.0."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        judge_scores = [5.0, 4.0, 3.0, 2.0, 1.0]

        calibration = HumanCalibration(min_correlation=0.85)
        result = calibration.compute_correlation(human_scores, judge_scores)
        assert result == pytest.approx(-1.0)

    def test_is_calibrated_above_threshold(self):
        """Correlation above 0.85 -> calibrated."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        judge_scores = [1.1, 2.2, 2.9, 4.1, 5.0, 5.9, 7.1]

        calibration = HumanCalibration(min_correlation=0.85)
        correlation = calibration.compute_correlation(human_scores, judge_scores)
        assert calibration.is_calibrated(correlation) is True

    def test_is_not_calibrated_below_threshold(self):
        """Correlation below 0.85 -> not calibrated."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        judge_scores = [3.0, 1.0, 5.0, 2.0, 4.0]  # scrambled

        calibration = HumanCalibration(min_correlation=0.85)
        correlation = calibration.compute_correlation(human_scores, judge_scores)
        assert calibration.is_calibrated(correlation) is False

    def test_custom_threshold(self):
        """Custom threshold (0.90) is stricter."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        judge_scores = [1.5, 2.5, 2.8, 4.5, 5.2, 5.5, 7.5]

        calibration = HumanCalibration(min_correlation=0.90)
        correlation = calibration.compute_correlation(human_scores, judge_scores)
        # At 0.90 threshold, a slightly noisy judge may not pass
        # Just verify the threshold comparison works
        if correlation >= 0.90:
            assert calibration.is_calibrated(correlation) is True
        else:
            assert calibration.is_calibrated(correlation) is False

    def test_minimum_samples_enforced(self):
        """Fewer than 5 samples -> raises ValueError."""
        calibration = HumanCalibration(min_correlation=0.85, min_samples=5)
        with pytest.raises(ValueError, match="samples"):
            calibration.compute_correlation([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])

    def test_mismatched_lengths_rejected(self):
        """Human and judge score lists must have same length."""
        calibration = HumanCalibration(min_correlation=0.85)
        with pytest.raises(ValueError, match="length"):
            calibration.compute_correlation(
                [1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0]
            )

    def test_quality_gate_halt_when_uncalibrated(self):
        """When uncalibrated, quality_gate_status returns HALT."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0]
        judge_scores = [3.0, 1.0, 5.0, 2.0, 4.0]  # scrambled

        calibration = HumanCalibration(min_correlation=0.85)
        correlation = calibration.compute_correlation(human_scores, judge_scores)
        status = calibration.quality_gate_status(correlation)
        assert status == "HALT"

    def test_quality_gate_pass_when_calibrated(self):
        """When calibrated, quality_gate_status returns PASS."""
        human_scores = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        judge_scores = [1.1, 2.0, 3.1, 4.0, 5.1, 6.0, 7.1]

        calibration = HumanCalibration(min_correlation=0.85)
        correlation = calibration.compute_correlation(human_scores, judge_scores)
        status = calibration.quality_gate_status(correlation)
        assert status == "PASS"


# =========================================================================
# Bootstrap confidence interval tests
# =========================================================================


class TestBootstrapCI:
    """Tests for bootstrap confidence intervals on evaluation scores."""

    def test_bootstrap_ci_narrow_for_consistent_scores(self):
        """Consistent scores -> narrow CI."""
        scores = [0.88, 0.89, 0.90, 0.91, 0.89, 0.90, 0.88, 0.91, 0.90, 0.89]
        ci = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=1000)
        assert isinstance(ci, BootstrapCI)
        assert ci.lower <= ci.mean <= ci.upper
        assert (ci.upper - ci.lower) < 0.10  # narrow CI

    def test_bootstrap_ci_wide_for_variable_scores(self):
        """Highly variable scores -> wider CI."""
        scores = [0.50, 0.95, 0.40, 0.85, 0.60, 0.90, 0.55, 0.70, 0.45, 0.80]
        ci = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=1000)
        assert ci.lower < ci.mean < ci.upper
        assert (ci.upper - ci.lower) > 0.05  # wider than consistent

    def test_bootstrap_ci_mean_matches_sample_mean(self):
        """CI mean should be close to the sample mean."""
        scores = [0.80, 0.82, 0.84, 0.86, 0.88]
        ci = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=2000)
        sample_mean = sum(scores) / len(scores)
        assert abs(ci.mean - sample_mean) < 0.02

    def test_bootstrap_ci_99_wider_than_95(self):
        """99% CI should be wider than 95% CI."""
        scores = [0.80, 0.82, 0.84, 0.86, 0.88, 0.81, 0.83, 0.85, 0.87, 0.89]
        ci_95 = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=2000)
        ci_99 = compute_bootstrap_ci(scores, confidence_level=0.99, n_bootstrap=2000)
        width_95 = ci_95.upper - ci_95.lower
        width_99 = ci_99.upper - ci_99.lower
        assert width_99 >= width_95

    def test_bootstrap_ci_minimum_samples(self):
        """Fewer than 3 samples -> raises ValueError."""
        with pytest.raises(ValueError, match="samples"):
            compute_bootstrap_ci([0.5, 0.6], confidence_level=0.95)

    def test_bootstrap_ci_all_same_scores(self):
        """All identical scores -> CI width = 0."""
        scores = [0.85, 0.85, 0.85, 0.85, 0.85]
        ci = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=1000)
        assert ci.lower == pytest.approx(0.85)
        assert ci.upper == pytest.approx(0.85)
        assert ci.mean == pytest.approx(0.85)

    def test_bootstrap_ci_contains_fields(self):
        """BootstrapCI has lower, upper, mean, confidence_level, n_samples."""
        scores = [0.7, 0.8, 0.9, 0.85, 0.75]
        ci = compute_bootstrap_ci(scores, confidence_level=0.95, n_bootstrap=500)
        assert hasattr(ci, "lower")
        assert hasattr(ci, "upper")
        assert hasattr(ci, "mean")
        assert hasattr(ci, "confidence_level")
        assert hasattr(ci, "n_samples")
        assert ci.confidence_level == 0.95
        assert ci.n_samples == 5
