"""Tests for the local inference benchmark script (Phase 6).

Validates benchmark data structures, cost computation, and aggregation
without requiring real providers.
"""

from __future__ import annotations

# Import benchmark components
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark_local import (
    BENCHMARK_PROMPTS,
    QueryResult,
    _aggregate_results,
    _mock_benchmark,
    compute_cost,
)


class TestBenchmarkData:
    """Benchmark data should cover sufficient categories with n>=5 per category."""

    def test_has_at_least_15_prompts(self):
        """Benchmark covers at least 15 diverse queries."""
        assert len(BENCHMARK_PROMPTS) >= 15

    def test_has_at_least_3_categories(self):
        """Benchmark covers at least 3 query categories."""
        categories = {p["category"] for p in BENCHMARK_PROMPTS}
        assert len(categories) >= 3

    def test_each_category_has_at_least_5_prompts(self):
        """Each category has n>=5 for statistical validity."""
        from collections import Counter

        counts = Counter(p["category"] for p in BENCHMARK_PROMPTS)
        for category, count in counts.items():
            assert count >= 5, f"Category {category!r} has only {count} prompts (need >=5)"

    def test_each_prompt_has_expected_contains(self):
        """Every prompt has expected keywords for accuracy checking."""
        for p in BENCHMARK_PROMPTS:
            assert "expected_contains" in p, f"Prompt {p['id']} missing expected_contains"
            assert len(p["expected_contains"]) > 0

    def test_all_prompts_have_unique_ids(self):
        """All prompt IDs are unique."""
        ids = [p["id"] for p in BENCHMARK_PROMPTS]
        assert len(ids) == len(set(ids))


class TestCostComputation:
    """Cost model computes accurate per-query costs."""

    def test_azure_gpt4o_cost(self):
        """GPT-4o cost matches expected pricing."""
        cost = compute_cost("gpt-4o", input_tokens=1000, output_tokens=500)
        # 1000 * 2.50/1M + 500 * 10.00/1M = 0.0025 + 0.005 = 0.0075
        assert abs(cost - 0.0075) < 0.0001

    def test_local_model_zero_cost(self):
        """Local models have zero per-query cost."""
        cost = compute_cost("qwen3:8b", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_unknown_model_zero_cost(self):
        """Unknown models default to zero cost."""
        cost = compute_cost("unknown-model", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_zero_tokens_zero_cost(self):
        """Zero tokens = zero cost."""
        cost = compute_cost("gpt-4o", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_gpt5_mini_cost(self):
        """GPT-5 mini cost matches expected pricing."""
        cost = compute_cost("gpt-5-mini", input_tokens=3000, output_tokens=500)
        # 3000 * 0.25/1M + 500 * 2.00/1M = 0.00075 + 0.001 = 0.00175
        assert abs(cost - 0.00175) < 0.00001


class TestResultAggregation:
    """Aggregate results compute correct statistics."""

    def test_perfect_results(self):
        """All queries successful, all expected keywords found."""
        results = [
            QueryResult(
                prompt_id=f"p{i}",
                category="simple",
                latency_ms=100 + i * 10,
                input_tokens=50,
                output_tokens=20,
                content="test response",
                expected_found=True,
            )
            for i in range(5)
        ]

        agg = _aggregate_results("test", "test-model", results)
        assert agg.total_queries == 5
        assert agg.successful_queries == 5
        assert agg.failed_queries == 0
        assert agg.accuracy == 1.0

    def test_partial_accuracy(self):
        """Some queries miss expected keywords."""
        results = [
            QueryResult(
                prompt_id=f"p{i}",
                category="extraction",
                latency_ms=200,
                input_tokens=50,
                output_tokens=20,
                content="response",
                expected_found=i < 3,  # 3/5 correct
            )
            for i in range(5)
        ]

        agg = _aggregate_results("test", "test-model", results)
        assert agg.accuracy == 0.6

    def test_failed_queries_tracked(self):
        """Failed queries are counted and errors recorded."""
        results = [
            QueryResult(
                prompt_id="ok",
                category="simple",
                latency_ms=100,
                input_tokens=50,
                output_tokens=20,
                content="response",
                expected_found=True,
            ),
            QueryResult(
                prompt_id="fail",
                category="simple",
                latency_ms=0,
                input_tokens=0,
                output_tokens=0,
                content="",
                expected_found=False,
                error="Connection refused",
            ),
        ]

        agg = _aggregate_results("test", "test-model", results)
        assert agg.total_queries == 2
        assert agg.successful_queries == 1
        assert agg.failed_queries == 1
        assert len(agg.errors) == 1

    def test_latency_statistics(self):
        """Latency p50, p95, and mean are computed correctly."""
        results = [
            QueryResult(
                prompt_id=f"p{i}",
                category="simple",
                latency_ms=float(100 * (i + 1)),  # 100, 200, 300, 400, 500
                input_tokens=50,
                output_tokens=20,
                content="response",
                expected_found=True,
            )
            for i in range(5)
        ]

        agg = _aggregate_results("test", "test-model", results)
        assert agg.latency_p50_ms == 300.0  # median
        assert agg.latency_mean_ms == 300.0  # mean

    def test_per_category_breakdown(self):
        """Results are broken down by category."""
        results = [
            QueryResult("s1", "simple", 100, 50, 20, "r", True),
            QueryResult("s2", "simple", 100, 50, 20, "r", True),
            QueryResult("e1", "extraction", 200, 50, 20, "r", False),
            QueryResult("e2", "extraction", 200, 50, 20, "r", True),
        ]

        agg = _aggregate_results("test", "test-model", results)
        assert "simple" in agg.results_by_category
        assert "extraction" in agg.results_by_category
        assert agg.results_by_category["simple"]["accuracy"] == 1.0
        assert agg.results_by_category["extraction"]["accuracy"] == 0.5


class TestMockBenchmark:
    """Mock benchmark provides reasonable synthetic data."""

    def test_mock_azure_results(self):
        """Mock Azure results have realistic values."""
        result = _mock_benchmark("azure")
        assert result.provider == "azure"
        assert result.model == "gpt-4o"
        assert result.accuracy > 0.8
        assert result.latency_p50_ms < 1000
        assert result.cost_per_query_eur > 0

    def test_mock_ollama_results(self):
        """Mock Ollama results have realistic values."""
        result = _mock_benchmark("ollama")
        assert result.provider == "ollama"
        assert result.model == "qwen3:8b"
        assert result.accuracy > 0.7
        assert result.latency_p50_ms > 0
        assert result.cost_per_query_eur == 0.0

    def test_mock_ollama_slower_than_azure(self):
        """Mock data reflects expected latency difference."""
        azure = _mock_benchmark("azure")
        ollama = _mock_benchmark("ollama")
        assert ollama.latency_p50_ms > azure.latency_p50_ms

    def test_mock_ollama_cheaper_than_azure(self):
        """Mock data reflects zero cost for local inference."""
        azure = _mock_benchmark("azure")
        ollama = _mock_benchmark("ollama")
        assert ollama.cost_per_query_eur < azure.cost_per_query_eur
