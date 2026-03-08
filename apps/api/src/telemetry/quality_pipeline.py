"""Quality pipeline: pairwise scoring, bias detection, human calibration.

Phase 5, Pillar 1: Judge Bias Mitigation.

Domain-agnostic: the judge function is injectable (any callable that takes
query, first, second and returns "A"/"B"/"TIE"). The pipeline works for
any domain by swapping the judge function.

Key design decisions:
- Pairwise comparison runs twice with A/B swapped, requires agreement
- Position bias = disagreement when order is swapped
- Verbosity bias = preference for longer answers regardless of quality
- Self-preference = preference for same-family model outputs
- Human calibration uses Spearman rank correlation (non-parametric)
- Confidence intervals use bootstrap sampling (non-parametric, no normality assumption)
"""

import random
import statistics
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from apps.api.src.domain.telemetry import JudgeBiasResult

# Type alias for judge functions: (query, first_answer, second_answer) -> "A"/"B"/"TIE"
JudgeFn = Callable[[str, str, str], str]


class ComparisonResult(BaseModel):
    """Result of a pairwise comparison with position-swap detection.

    Round 1: A in position 1, B in position 2.
    Round 2: B in position 1, A in position 2.

    Consistent: both rounds pick the same *answer* (not same position).
    - Round1=A, Round2=A -> both picked answer A -> consistent, A wins.
    - Round1=B, Round2=B -> both picked answer B -> consistent, B wins.
    - Round1=TIE, Round2=TIE -> consistent tie.

    Position bias detected:
    - Round1=A, Round2=B -> both picked position 1 -> bias.
    - Round1=B, Round2=A -> both picked position 2 -> bias.
    """

    query: str
    answer_a: str
    answer_b: str
    round1_winner: str  # "A", "B", or "TIE"
    round2_winner: str  # "A", "B", or "TIE" (after swap)

    @property
    def is_consistent(self) -> bool:
        """Check if both rounds agree on the same answer.

        In round 1: A=first, B=second.
        In round 2: B=first, A=second.

        If round1 picks A and round2 picks A, both rounds identified
        answer A as the winner regardless of position -> consistent.

        If round1 picks A (=first) and round2 picks B (=first in round2),
        both rounds just picked whatever was in position 1 -> bias.
        """
        return self.round1_winner == self.round2_winner

    @property
    def winner(self) -> str | None:
        """Return the winner if consistent, None if position bias detected."""
        if self.is_consistent:
            return self.round1_winner
        return None

    @property
    def position_bias_detected(self) -> bool:
        """True if the two rounds disagree (each picked a different answer)."""
        if self.round1_winner == "TIE" and self.round2_winner == "TIE":
            return False
        return not self.is_consistent


class PairwiseScorer:
    """Position-randomized pairwise comparison scorer.

    Runs each comparison twice with A/B swapped. Requires agreement
    for a valid result. Disagreement = position bias detected.
    """

    def __init__(self, judge_fn: JudgeFn) -> None:
        self._judge_fn = judge_fn

    def compare(
        self, query: str, answer_a: str, answer_b: str
    ) -> ComparisonResult:
        """Run pairwise comparison with position swap.

        Round 1: A first, B second.
        Round 2: B first, A second.

        The judge returns "A" or "B" based on position (first=A, second=B).
        In round 2, we swap positions, so the judge sees B first and A second.
        If the judge returns "A" in round 2, that means it picked the first
        position (which is now B). We need to translate that back to answer labels.

        Returns:
            ComparisonResult with consistency and winner information.
        """
        # Round 1: A is first, B is second
        round1_raw = self._judge_fn(query, answer_a, answer_b)

        # Round 2: B is first, A is second
        round2_raw = self._judge_fn(query, answer_b, answer_a)

        # Translate round 2 result back to answer labels
        # In round 2: "A" means first position = answer_b, "B" means second = answer_a
        if round2_raw == "A":
            round2_translated = "B"  # Judge picked position 1, which was answer B
        elif round2_raw == "B":
            round2_translated = "A"  # Judge picked position 2, which was answer A
        else:
            round2_translated = "TIE"

        return ComparisonResult(
            query=query,
            answer_a=answer_a,
            answer_b=answer_b,
            round1_winner=round1_raw,
            round2_winner=round2_translated,
        )

    def batch_compare(
        self, pairs: list[tuple[str, str, str]]
    ) -> list[ComparisonResult]:
        """Run pairwise comparison on multiple query-answer pairs.

        Args:
            pairs: List of (query, answer_a, answer_b) tuples.

        Returns:
            List of ComparisonResult objects.
        """
        return [
            self.compare(query, answer_a, answer_b)
            for query, answer_a, answer_b in pairs
        ]


class BiasDetector:
    """Detects position, verbosity, and self-preference biases in LLM judges.

    Each detection method returns a bias rate (0.0 to 1.0) representing
    the fraction of comparisons exhibiting that bias type.
    """

    def __init__(self, judge_fn: JudgeFn) -> None:
        self._judge_fn = judge_fn
        self._scorer = PairwiseScorer(judge_fn)

    def detect_position_bias(
        self, pairs: list[tuple[str, str, str]]
    ) -> float:
        """Measure position bias: disagreement rate when swapping A/B order.

        For each pair, runs the pairwise scorer (which swaps positions).
        Position bias rate = (inconsistent results) / (total pairs).

        Args:
            pairs: List of (query, answer_a, answer_b) tuples.

        Returns:
            Position bias rate (0.0 = no bias, 1.0 = always biased).
        """
        if not pairs:
            return 0.0

        results = self._scorer.batch_compare(pairs)
        biased_count = sum(1 for r in results if r.position_bias_detected)
        return biased_count / len(results)

    def detect_verbosity_bias(
        self, pairs: list[tuple[str, str, str]]
    ) -> float:
        """Measure verbosity bias: preference for longer answers.

        For each pair where answer_a (short correct) is shorter than answer_b
        (long wrong), if the judge picks the longer answer, that is verbosity bias.

        Convention: answer_a is the short correct answer, answer_b is the long wrong answer.
        Pairs where lengths are similar (within 20% ratio) are excluded.

        Args:
            pairs: List of (query, short_correct_answer, long_wrong_answer) tuples.

        Returns:
            Verbosity bias rate (0.0 = no bias, 1.0 = always prefers longer).
        """
        if not pairs:
            return 0.0

        eligible_count = 0
        biased_count = 0

        for query, short_answer, long_answer in pairs:
            # Only test pairs where there is a meaningful length difference
            short_len = len(short_answer)
            long_len = len(long_answer)

            if short_len == 0 or long_len == 0:
                continue

            ratio = max(short_len, long_len) / min(short_len, long_len)
            if ratio < 1.5:
                continue  # Not enough length difference to test verbosity

            eligible_count += 1

            # Ask judge: which is better? (short is answer A, long is answer B)
            result = self._judge_fn(query, short_answer, long_answer)

            # If judge picks the longer answer (B), that's verbosity bias
            if result == "B":
                biased_count += 1

        if eligible_count == 0:
            return 0.0

        return biased_count / eligible_count

    def detect_self_preference(
        self, pairs: list[tuple[str, str, str]]
    ) -> float:
        """Measure self-preference bias: preference for same-family outputs.

        Convention: answer_a is labeled as same-family, answer_b as cross-family.
        Self-preference = judge picks answer_a when answer_b is equally or more correct.

        For this measurement, we count how often the judge picks the same-family
        answer. Ties are NOT counted as self-preference (fair judge would tie on
        equal quality).

        Args:
            pairs: List of (query, same_family_answer, cross_family_answer) tuples.

        Returns:
            Self-preference rate (0.0 = no preference, 1.0 = always picks same-family).
        """
        if not pairs:
            return 0.0

        total_decisive = 0
        same_family_picks = 0

        for query, same_family, cross_family in pairs:
            result = self._judge_fn(query, same_family, cross_family)
            if result == "TIE":
                continue
            total_decisive += 1
            if result == "A":  # Picked same-family
                same_family_picks += 1

        if total_decisive == 0:
            return 0.0

        # Self-preference rate: fraction of decisive comparisons that picked same-family
        # Fair judge: ~0.5 (picks each equally). Biased: > 0.5.
        # We return 0.0 if picks are balanced, scaling from 0.5 to 1.0.
        raw_rate = same_family_picks / total_decisive

        # If rate <= 0.5, no self-preference detected (or inverse preference)
        if raw_rate <= 0.5:
            return 0.0

        # Scale 0.5-1.0 to 0.0-1.0 for clearer interpretation
        return (raw_rate - 0.5) / 0.5

    def full_bias_report(
        self,
        position_pairs: list[tuple[str, str, str]],
        verbosity_pairs: list[tuple[str, str, str]],
        self_preference_pairs: list[tuple[str, str, str]],
        spearman_correlation: float,
    ) -> JudgeBiasResult:
        """Run all three bias detection methods and return a unified result.

        Args:
            position_pairs: Pairs for position bias detection.
            verbosity_pairs: Pairs for verbosity bias detection (short=A, long=B).
            self_preference_pairs: Pairs for self-preference (same_family=A, cross=B).
            spearman_correlation: Pre-computed Spearman correlation from human calibration.

        Returns:
            JudgeBiasResult with all rates populated.
        """
        position_rate = self.detect_position_bias(position_pairs)
        verbosity_rate = self.detect_verbosity_bias(verbosity_pairs)
        self_pref_rate = self.detect_self_preference(self_preference_pairs)

        total = len(position_pairs) + len(verbosity_pairs) + len(self_preference_pairs)

        return JudgeBiasResult(
            position_bias_rate=position_rate,
            verbosity_bias_rate=verbosity_rate,
            self_preference_rate=self_pref_rate,
            spearman_correlation=spearman_correlation,
            total_comparisons=total,
        )


class HumanCalibration:
    """Calibrate LLM judge against human expert scores using Spearman correlation.

    The golden set (50 human-scored examples) is the ultimate ground truth.
    If judge-human correlation drops below min_correlation, all automated
    quality gates must halt — the judge is unreliable.
    """

    def __init__(
        self,
        min_correlation: float = 0.85,
        min_samples: int = 5,
    ) -> None:
        self.min_correlation = min_correlation
        self.min_samples = min_samples

    def compute_correlation(
        self,
        human_scores: list[float],
        judge_scores: list[float],
    ) -> float:
        """Compute Spearman rank correlation between human and judge scores.

        Args:
            human_scores: Scores assigned by human experts.
            judge_scores: Scores assigned by the LLM judge.

        Returns:
            Spearman correlation coefficient (-1.0 to 1.0).

        Raises:
            ValueError: If lists have different lengths or too few samples.
        """
        if len(human_scores) != len(judge_scores):
            raise ValueError(
                f"Score lists must have the same length: "
                f"human={len(human_scores)}, judge={len(judge_scores)}"
            )
        if len(human_scores) < self.min_samples:
            raise ValueError(
                f"Need at least {self.min_samples} samples, "
                f"got {len(human_scores)}"
            )

        return _spearman_rank_correlation(human_scores, judge_scores)

    def is_calibrated(self, correlation: float) -> bool:
        """Check if the correlation meets the minimum threshold."""
        return correlation >= self.min_correlation

    def quality_gate_status(
        self, correlation: float
    ) -> Literal["PASS", "HALT"]:
        """Determine quality gate status based on calibration.

        PASS: correlation >= min_correlation, automated quality gates proceed.
        HALT: correlation < min_correlation, halt all automated quality gates.
        """
        if self.is_calibrated(correlation):
            return "PASS"
        return "HALT"


def _spearman_rank_correlation(x: list[float], y: list[float]) -> float:
    """Compute Spearman rank correlation coefficient.

    Uses the standard formula: rho = 1 - (6 * sum(d^2)) / (n * (n^2 - 1))
    where d is the difference between ranks.

    Handles ties using average rank assignment.
    """
    n = len(x)
    if n < 2:
        return 0.0

    ranks_x = _compute_ranks(x)
    ranks_y = _compute_ranks(y)

    d_squared_sum = sum((rx - ry) ** 2 for rx, ry in zip(ranks_x, ranks_y))

    denominator = n * (n**2 - 1)
    if denominator == 0:
        return 0.0

    return 1 - (6 * d_squared_sum) / denominator


def _compute_ranks(values: list[float]) -> list[float]:
    """Compute ranks with average rank for ties."""
    n = len(values)
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n

    i = 0
    while i < n:
        j = i
        # Find all tied values
        while j < n and indexed[j][1] == indexed[i][1]:
            j += 1
        # Assign average rank to all tied values
        avg_rank = (i + j + 1) / 2  # 1-based average rank
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j

    return ranks


class BootstrapCI(BaseModel):
    """Bootstrap confidence interval result."""

    lower: float
    upper: float
    mean: float
    confidence_level: float = Field(ge=0.0, le=1.0)
    n_samples: int = Field(ge=1)


def compute_bootstrap_ci(
    scores: list[float],
    confidence_level: float = 0.95,
    n_bootstrap: int = 1000,
) -> BootstrapCI:
    """Compute bootstrap confidence interval for a set of scores.

    Non-parametric: works regardless of score distribution.
    Resamples with replacement n_bootstrap times, computes the mean of
    each resample, then takes percentiles for the CI.

    Args:
        scores: List of evaluation scores.
        confidence_level: Confidence level (e.g., 0.95 for 95% CI).
        n_bootstrap: Number of bootstrap resamples.

    Returns:
        BootstrapCI with lower, upper, mean bounds.

    Raises:
        ValueError: If fewer than 3 samples provided.
    """
    if len(scores) < 3:
        raise ValueError(f"Need at least 3 samples for bootstrap CI, got {len(scores)}")

    sample_mean = statistics.mean(scores)
    n = len(scores)

    # Bootstrap resampling
    bootstrap_means = []
    for _ in range(n_bootstrap):
        resample = random.choices(scores, k=n)
        bootstrap_means.append(statistics.mean(resample))

    bootstrap_means.sort()

    # Percentile method
    alpha = 1 - confidence_level
    lower_idx = max(0, int((alpha / 2) * n_bootstrap))
    upper_idx = min(n_bootstrap - 1, int((1 - alpha / 2) * n_bootstrap))

    return BootstrapCI(
        lower=bootstrap_means[lower_idx],
        upper=bootstrap_means[upper_idx],
        mean=sample_mean,
        confidence_level=confidence_level,
        n_samples=n,
    )
