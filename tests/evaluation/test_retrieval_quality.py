"""Automated retrieval quality gate tests.

Tests the metrics functions (precision@k, recall@k, MRR) and runs
the ground truth dataset through a mock pipeline to verify quality thresholds.

For CI gating: uses mock embeddings + mock search (no external services).
For live benchmarks: use the benchmark scripts in scripts/.

Run: uv run pytest tests/evaluation/test_retrieval_quality.py -v
"""

from __future__ import annotations

import pytest

from tests.evaluation.ground_truth import (
    GROUND_TRUTH,
    GroundTruthQuery,
    get_all_categories,
    get_queries_by_category,
)
from tests.evaluation.metrics import (
    RetrievalEvalResult,
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
    run_evaluation,
)

# =============================================================================
# Unit tests for metric functions
# =============================================================================


class TestPrecisionAtK:
    """Precision@k = (relevant docs in top-k) / k."""

    def test_perfect_precision(self):
        retrieved = ["DOC-1", "DOC-2", "DOC-3"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        assert compute_precision_at_k(retrieved, relevant, k=3) == 1.0

    def test_zero_precision(self):
        retrieved = ["DOC-4", "DOC-5", "DOC-6"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        assert compute_precision_at_k(retrieved, relevant, k=3) == 0.0

    def test_partial_precision(self):
        retrieved = ["DOC-1", "DOC-4", "DOC-2", "DOC-5", "DOC-6"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        # At k=5: 2 relevant out of 5 = 0.4
        assert compute_precision_at_k(retrieved, relevant, k=5) == pytest.approx(0.4)

    def test_k_larger_than_retrieved(self):
        retrieved = ["DOC-1", "DOC-2"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        # k=5 but only 2 retrieved: 2 relevant / 5 = 0.4
        assert compute_precision_at_k(retrieved, relevant, k=5) == pytest.approx(0.4)

    def test_k_truncates_retrieved(self):
        retrieved = ["DOC-1", "DOC-2", "DOC-3", "DOC-4", "DOC-5"]
        relevant = ["DOC-1"]
        # At k=1: 1 relevant / 1 = 1.0
        assert compute_precision_at_k(retrieved, relevant, k=1) == 1.0
        # At k=5: 1 relevant / 5 = 0.2
        assert compute_precision_at_k(retrieved, relevant, k=5) == pytest.approx(0.2)

    def test_empty_retrieved(self):
        assert compute_precision_at_k([], ["DOC-1"], k=5) == 0.0

    def test_empty_relevant(self):
        assert compute_precision_at_k(["DOC-1"], [], k=5) == 0.0


class TestRecallAtK:
    """Recall@k = (relevant docs in top-k) / total relevant docs."""

    def test_perfect_recall(self):
        retrieved = ["DOC-1", "DOC-2", "DOC-3"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        assert compute_recall_at_k(retrieved, relevant, k=3) == 1.0

    def test_zero_recall(self):
        retrieved = ["DOC-4", "DOC-5", "DOC-6"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        assert compute_recall_at_k(retrieved, relevant, k=3) == 0.0

    def test_partial_recall(self):
        retrieved = ["DOC-1", "DOC-4", "DOC-2"]
        relevant = ["DOC-1", "DOC-2", "DOC-3"]
        # 2 of 3 relevant found = 0.667
        assert compute_recall_at_k(retrieved, relevant, k=3) == pytest.approx(2 / 3)

    def test_k_truncates(self):
        retrieved = ["DOC-1", "DOC-4", "DOC-2"]
        relevant = ["DOC-1", "DOC-2"]
        # At k=1: only DOC-1 found -> 1/2 = 0.5
        assert compute_recall_at_k(retrieved, relevant, k=1) == 0.5

    def test_empty_retrieved(self):
        assert compute_recall_at_k([], ["DOC-1"], k=5) == 0.0

    def test_empty_relevant(self):
        # No relevant docs -> recall is 0 to avoid misleading metrics
        assert compute_recall_at_k(["DOC-1"], [], k=5) == 0.0


class TestMRR:
    """MRR = 1 / rank of first relevant result."""

    def test_first_result_relevant(self):
        retrieved = ["DOC-1", "DOC-2", "DOC-3"]
        relevant = ["DOC-1"]
        assert compute_mrr(retrieved, relevant) == 1.0

    def test_second_result_relevant(self):
        retrieved = ["DOC-4", "DOC-1", "DOC-3"]
        relevant = ["DOC-1"]
        assert compute_mrr(retrieved, relevant) == 0.5

    def test_third_result_relevant(self):
        retrieved = ["DOC-4", "DOC-5", "DOC-1"]
        relevant = ["DOC-1"]
        assert compute_mrr(retrieved, relevant) == pytest.approx(1 / 3)

    def test_no_relevant_result(self):
        retrieved = ["DOC-4", "DOC-5", "DOC-6"]
        relevant = ["DOC-1"]
        assert compute_mrr(retrieved, relevant) == 0.0

    def test_multiple_relevant_uses_first(self):
        retrieved = ["DOC-4", "DOC-1", "DOC-2"]
        relevant = ["DOC-1", "DOC-2"]
        # First relevant is DOC-1 at position 2 -> 1/2 = 0.5
        assert compute_mrr(retrieved, relevant) == 0.5

    def test_empty_retrieved(self):
        assert compute_mrr([], ["DOC-1"]) == 0.0

    def test_empty_relevant(self):
        assert compute_mrr(["DOC-1"], []) == 0.0


# =============================================================================
# Full retrieval scoring tests
# =============================================================================


class TestRunRetrieval:
    """Test the full run_evaluation function that aggregates metrics."""

    def test_perfect_retrieval(self):
        """All queries return their expected docs at rank 1."""
        queries = [
            GroundTruthQuery("q1", "test", ["DOC-1"]),
            GroundTruthQuery("q2", "test", ["DOC-2"]),
        ]

        def mock_search(query: str) -> list[str]:
            if query == "q1":
                return ["DOC-1", "DOC-3"]
            return ["DOC-2", "DOC-4"]

        result = run_evaluation(queries, mock_search, k=5)
        assert isinstance(result, RetrievalEvalResult)
        assert result.mean_mrr == 1.0
        assert result.mean_precision_at_k == pytest.approx(0.2)  # 1/5 per query
        assert result.mean_recall_at_k == 1.0
        assert result.total_queries == 2

    def test_zero_retrieval(self):
        """No queries return relevant docs."""
        queries = [GroundTruthQuery("q1", "test", ["DOC-1"])]

        def mock_search(query: str) -> list[str]:
            return ["DOC-99"]

        result = run_evaluation(queries, mock_search, k=5)
        assert result.mean_mrr == 0.0
        assert result.mean_precision_at_k == 0.0
        assert result.mean_recall_at_k == 0.0

    def test_per_category_breakdown(self):
        """Produces per-category metrics."""
        queries = [
            GroundTruthQuery("code query", "exact_code", ["DOC-1"]),
            GroundTruthQuery("vague query", "vague", ["DOC-2", "DOC-3"]),
        ]

        def mock_search(query: str) -> list[str]:
            if "code" in query:
                return ["DOC-1"]
            return ["DOC-2"]

        result = run_evaluation(queries, mock_search, k=5)
        assert "exact_code" in result.per_category
        assert "vague" in result.per_category
        assert result.per_category["exact_code"].mean_mrr == 1.0
        assert result.per_category["vague"].mean_recall_at_k == 0.5  # 1 of 2

    def test_handles_empty_search_results(self):
        """Handles queries that return zero results."""
        queries = [GroundTruthQuery("q1", "test", ["DOC-1"])]

        def mock_search(query: str) -> list[str]:
            return []

        result = run_evaluation(queries, mock_search, k=5)
        assert result.mean_mrr == 0.0
        assert result.mean_recall_at_k == 0.0


# =============================================================================
# Ground truth dataset validation
# =============================================================================


class TestGroundTruthDataset:
    """Verify ground truth dataset is well-formed."""

    def test_minimum_query_count(self):
        assert len(GROUND_TRUTH) >= 50, f"Expected 50+ queries, got {len(GROUND_TRUTH)}"

    def test_all_categories_present(self):
        categories = get_all_categories()
        expected = {
            "exact_code", "natural_language", "vague", "negation",
            "german", "synonym", "typo", "jargon", "ranking", "multi_hop",
        }
        assert set(categories) == expected

    def test_minimum_per_category(self):
        """Each category has at least 4 queries."""
        for cat in get_all_categories():
            queries = get_queries_by_category(cat)
            assert len(queries) >= 4, f"Category {cat} has only {len(queries)} queries"

    def test_all_queries_have_relevant_docs(self):
        """Every query has at least one expected relevant document."""
        for q in GROUND_TRUTH:
            assert len(q.relevant_doc_ids) >= 1, (
                f"Query '{q.query}' has no relevant doc IDs"
            )

    def test_all_doc_ids_valid(self):
        """All referenced doc IDs follow valid corpus document IDs."""
        valid_doc_ids = {
            "DOC-SAFETY-001", "DOC-HR-003", "DOC-SAFETY-002", "DOC-SAFETY-003",
            "DOC-HR-002", "DOC-HR-004", "DOC-HR-005",
            "DOC-LEGAL-001", "DOC-LEGAL-002", "DOC-LEGAL-003",
            "DOC-LEGAL-004", "DOC-LEGAL-005",
        }
        for q in GROUND_TRUTH:
            for doc_id in q.relevant_doc_ids:
                assert doc_id in valid_doc_ids, (
                    f"Query '{q.query}' references unknown doc ID: {doc_id}"
                )

    def test_queries_are_unique(self):
        """No duplicate queries."""
        queries = [q.query for q in GROUND_TRUTH]
        assert len(queries) == len(set(queries)), "Duplicate queries found"
