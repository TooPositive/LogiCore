"""Automated RAG quality evaluation with LLM-as-Judge scoring.

Phase 4 evaluation pipeline: runs 50+ Q&A pairs through LLM-as-Judge
and scores context_precision, faithfulness, answer_relevancy.

CI quality gate: all metrics must be > 0.8 to pass.

This test file uses mock judges for CI. Live evaluation with real LLM
uses scripts/run_evaluation.py.
"""

import json
from pathlib import Path

from apps.api.src.core.domain.telemetry import EvalScore


class TestEvalDataset:
    """Verify the ground truth Q&A dataset is valid and sufficient."""

    def test_eval_dataset_exists(self):
        dataset_path = Path(__file__).parent / "eval_dataset.json"
        assert dataset_path.exists(), "eval_dataset.json must exist"

    def test_eval_dataset_has_50_plus_entries(self):
        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)
        assert len(data) >= 50, f"Need 50+ Q&A pairs, got {len(data)}"

    def test_eval_dataset_entries_have_required_fields(self):
        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        for i, entry in enumerate(data):
            assert "question" in entry, f"Entry {i} missing 'question'"
            assert "expected_answer" in entry, f"Entry {i} missing 'expected_answer'"
            assert "context" in entry, f"Entry {i} missing 'context'"
            assert "category" in entry, f"Entry {i} missing 'category'"
            assert len(entry["question"]) > 10, f"Entry {i} question too short"
            assert len(entry["expected_answer"]) > 10, f"Entry {i} answer too short"

    def test_eval_dataset_has_5_plus_per_category(self):
        """Deep benchmarks: n>=5 cases per category (architect requirement)."""
        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        categories: dict[str, int] = {}
        for entry in data:
            cat = entry["category"]
            categories[cat] = categories.get(cat, 0) + 1

        for cat, count in categories.items():
            assert count >= 5, (
                f"Category '{cat}' has only {count} entries, need >= 5"
            )

    def test_eval_dataset_covers_key_categories(self):
        """Must cover search, audit, compliance, and edge cases."""
        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        categories = {entry["category"] for entry in data}
        required = {"search", "audit", "compliance", "edge_case", "multilingual"}
        missing = required - categories
        assert not missing, f"Missing required categories: {missing}"


class TestLLMAsJudge:
    """LLM-as-Judge scoring for context precision, faithfulness, relevancy."""

    def test_score_context_precision(self):
        """Context precision: are the retrieved chunks relevant to the question?"""
        from tests.evaluation.llm_judge import score_context_precision

        score = score_context_precision(
            question="What is the penalty for late delivery to PharmaCorp?",
            context="PharmaCorp penalty clause: 2% per day for late delivery, "
            "maximum 20% of total invoice value.",
            answer="The penalty is 2% per day, up to 20%.",
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.7  # relevant context should score high

    def test_score_faithfulness(self):
        """Faithfulness: does the answer stick to the provided context?"""
        from tests.evaluation.llm_judge import score_faithfulness

        score = score_faithfulness(
            question="What is the base rate for FreshFoods?",
            context="FreshFoods base rate: EUR 0.32/kg for refrigerated goods.",
            answer="The base rate for FreshFoods is EUR 0.32/kg for refrigerated goods.",
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.7  # faithful answer should score high

    def test_faithfulness_hallucinated_answer_scores_low(self):
        """Hallucinated answer that adds info not in context should score low."""
        from tests.evaluation.llm_judge import score_faithfulness

        score = score_faithfulness(
            question="What is the base rate?",
            context="Base rate: EUR 0.32/kg",
            answer="The base rate is EUR 0.32/kg, and there is also a 5% "
            "surcharge for hazardous materials and a 10% discount for "
            "volumes over 100 tons.",
        )
        assert score < 0.5  # hallucinated info should lower the score

    def test_score_answer_relevancy(self):
        """Answer relevancy: does the answer address the question?"""
        from tests.evaluation.llm_judge import score_answer_relevancy

        score = score_answer_relevancy(
            question="What are the delivery hours for warehouse B?",
            answer="Warehouse B accepts deliveries from 6 AM to 8 PM, "
            "Monday through Saturday.",
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.7

    def test_irrelevant_answer_scores_low(self):
        """Answer that doesn't address the question should score low."""
        from tests.evaluation.llm_judge import score_answer_relevancy

        score = score_answer_relevancy(
            question="What is the penalty for late delivery?",
            answer="Bananas are a popular fruit grown in tropical regions.",
        )
        assert score < 0.5


class TestEvalPipeline:
    """Full evaluation pipeline: run dataset through judge, aggregate scores."""

    def test_run_eval_returns_eval_score(self):
        from tests.evaluation.llm_judge import run_eval_pipeline

        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        result = run_eval_pipeline(data[:10])  # subset for speed
        assert isinstance(result, EvalScore)
        assert 0.0 <= result.context_precision <= 1.0
        assert 0.0 <= result.faithfulness <= 1.0
        assert 0.0 <= result.answer_relevancy <= 1.0

    def test_quality_gate_with_mock_judge(self):
        """Mock judge pipeline passes quality gate (baseline test)."""
        from tests.evaluation.llm_judge import run_eval_pipeline

        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        result = run_eval_pipeline(data)
        # Mock judge should produce scores > 0.8 for well-formed Q&A pairs
        assert result.passes_quality_gate(threshold=0.8)

    def test_eval_pipeline_reports_dataset_size(self):
        from tests.evaluation.llm_judge import run_eval_pipeline

        dataset_path = Path(__file__).parent / "eval_dataset.json"
        with open(dataset_path) as f:
            data = json.load(f)

        result = run_eval_pipeline(data)
        assert result.dataset_size == len(data)
