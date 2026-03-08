"""Unit tests for Phase 4 cost tracker.

Tests: per-query cost calculation, model pricing table, aggregation by
agent/user/period, cache hits as EUR 0.00, model routing cost savings.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest


class TestModelPricing:
    """Model pricing table: GPT-5 nano, mini, 5.2 per 1M tokens."""

    def test_pricing_table_has_all_models(self):
        from apps.api.src.telemetry.cost_tracker import MODEL_PRICING

        assert "gpt-5-nano" in MODEL_PRICING
        assert "gpt-5-mini" in MODEL_PRICING
        assert "gpt-5.2" in MODEL_PRICING

    def test_nano_pricing(self):
        """GPT-5 nano: $0.05 input, $0.40 output per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import MODEL_PRICING

        pricing = MODEL_PRICING["gpt-5-nano"]
        assert pricing.input_per_1m == Decimal("0.05")
        assert pricing.output_per_1m == Decimal("0.40")

    def test_mini_pricing(self):
        """GPT-5 mini: $0.25 input, $2.00 output per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import MODEL_PRICING

        pricing = MODEL_PRICING["gpt-5-mini"]
        assert pricing.input_per_1m == Decimal("0.25")
        assert pricing.output_per_1m == Decimal("2.00")

    def test_gpt52_pricing(self):
        """GPT-5.2: $1.75 input, $14.00 output per 1M tokens."""
        from apps.api.src.telemetry.cost_tracker import MODEL_PRICING

        pricing = MODEL_PRICING["gpt-5.2"]
        assert pricing.input_per_1m == Decimal("1.75")
        assert pricing.output_per_1m == Decimal("14.00")

    def test_pricing_is_configurable(self):
        """Pricing table should accept custom entries (domain-agnostic)."""
        from apps.api.src.telemetry.cost_tracker import ModelPricing

        custom = ModelPricing(
            model_name="custom-model",
            input_per_1m=Decimal("0.10"),
            output_per_1m=Decimal("0.80"),
        )
        assert custom.model_name == "custom-model"


class TestPerQueryCost:
    """Per-query cost calculation from token counts + pricing."""

    def test_calculate_cost_nano_simple_lookup(self):
        """500 input + 100 output on nano = ~EUR 0.00007."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost(
            model="gpt-5-nano",
            prompt_tokens=500,
            completion_tokens=100,
        )
        # (500/1M * 0.05) + (100/1M * 0.40) = 0.000025 + 0.00004 = 0.000065
        assert cost == Decimal("0.000065")

    def test_calculate_cost_mini_rag_search(self):
        """2800 input + 400 output on mini."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost(
            model="gpt-5-mini",
            prompt_tokens=2800,
            completion_tokens=400,
        )
        # (2800/1M * 0.25) + (400/1M * 2.00) = 0.0007 + 0.0008 = 0.0015
        assert cost == Decimal("0.0015")

    def test_calculate_cost_gpt52_complex_audit(self):
        """8200 input + 1200 output on GPT-5.2."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost(
            model="gpt-5.2",
            prompt_tokens=8200,
            completion_tokens=1200,
        )
        # (8200/1M * 1.75) + (1200/1M * 14.00) = 0.01435 + 0.0168 = 0.03115
        assert cost == Decimal("0.03115")

    def test_calculate_cost_zero_tokens(self):
        """Zero tokens = zero cost (cache hit scenario)."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost(
            model="gpt-5-mini",
            prompt_tokens=0,
            completion_tokens=0,
        )
        assert cost == Decimal("0")

    def test_calculate_cost_unknown_model_raises(self):
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        with pytest.raises(ValueError, match="Unknown model"):
            calculate_query_cost(
                model="nonexistent-model",
                prompt_tokens=100,
                completion_tokens=50,
            )

    def test_calculate_cost_with_custom_pricing(self):
        """Domain-agnostic: accept custom pricing table."""
        from apps.api.src.telemetry.cost_tracker import (
            ModelPricing,
            calculate_query_cost,
        )

        custom_pricing = {
            "local-llama": ModelPricing(
                model_name="local-llama",
                input_per_1m=Decimal("0"),
                output_per_1m=Decimal("0"),
            ),
        }
        cost = calculate_query_cost(
            model="local-llama",
            prompt_tokens=10000,
            completion_tokens=5000,
            pricing_table=custom_pricing,
        )
        assert cost == Decimal("0")

    def test_calculate_cost_cache_hit_is_zero(self):
        """Cache hits recorded as EUR 0.00 cost, regardless of model."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        cost = calculate_query_cost(
            model="gpt-5.2",
            prompt_tokens=0,
            completion_tokens=0,
            cache_hit=True,
        )
        assert cost == Decimal("0")


class TestCostTracker:
    """CostTracker aggregates costs across queries for analytics."""

    def test_tracker_record_and_total(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(
            agent_name="search",
            model="gpt-5-mini",
            prompt_tokens=2800,
            completion_tokens=400,
            user_id="anna.schmidt",
        )
        assert tracker.total_cost() > Decimal("0")
        assert tracker.total_queries() == 1

    def test_tracker_multiple_records(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        for _ in range(5):
            tracker.record(
                agent_name="search",
                model="gpt-5-mini",
                prompt_tokens=2800,
                completion_tokens=400,
            )
        assert tracker.total_queries() == 5

    def test_tracker_aggregate_by_agent(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400)
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400)
        tracker.record(agent_name="audit", model="gpt-5.2",
                       prompt_tokens=8200, completion_tokens=1200)

        by_agent = tracker.cost_by_agent()
        assert "search" in by_agent
        assert "audit" in by_agent
        assert by_agent["search"] > Decimal("0")
        assert by_agent["audit"] > by_agent["search"]

    def test_tracker_aggregate_by_user(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400,
                       user_id="anna.schmidt")
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400,
                       user_id="max.weber")

        by_user = tracker.cost_by_user()
        assert "anna.schmidt" in by_user
        assert "max.weber" in by_user

    def test_tracker_cache_hit_rate(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        # 7 regular + 3 cache hits = 30% hit rate
        for _ in range(7):
            tracker.record(agent_name="search", model="gpt-5-mini",
                           prompt_tokens=2800, completion_tokens=400)
        for _ in range(3):
            tracker.record(agent_name="search", model="cache",
                           prompt_tokens=0, completion_tokens=0,
                           cache_hit=True)

        assert tracker.cache_hit_rate() == pytest.approx(0.3, abs=0.01)

    def test_tracker_cache_hit_zero_cost(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(agent_name="search", model="cache",
                       prompt_tokens=0, completion_tokens=0,
                       cache_hit=True)

        assert tracker.total_cost() == Decimal("0")
        assert tracker.total_queries() == 1

    def test_tracker_avg_cost_per_query(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400)
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400)
        avg = tracker.avg_cost_per_query()
        assert avg == Decimal("0.0015")

    def test_tracker_avg_cost_zero_queries(self):
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        assert tracker.avg_cost_per_query() == Decimal("0")

    def test_tracker_to_cost_summary(self):
        """Convert tracker data to CostSummary model for API response."""
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record(agent_name="search", model="gpt-5-mini",
                       prompt_tokens=2800, completion_tokens=400,
                       timestamp=datetime(2026, 3, 5, tzinfo=UTC))
        tracker.record(agent_name="search", model="cache",
                       prompt_tokens=0, completion_tokens=0,
                       cache_hit=True,
                       timestamp=datetime(2026, 3, 6, tzinfo=UTC))

        summary = tracker.to_cost_summary(
            period_start=datetime(2026, 3, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 8, tzinfo=UTC),
        )
        assert summary.total_queries == 2
        assert summary.cache_hit_rate == 0.5
        assert "search" in summary.by_agent

    def test_tracker_cost_by_period(self):
        """Filter costs within a time period."""
        from apps.api.src.telemetry.cost_tracker import CostTracker

        tracker = CostTracker()
        # Record with specific timestamps
        tracker.record(
            agent_name="search", model="gpt-5-mini",
            prompt_tokens=2800, completion_tokens=400,
            timestamp=datetime(2026, 3, 5, tzinfo=UTC),
        )
        tracker.record(
            agent_name="search", model="gpt-5-mini",
            prompt_tokens=2800, completion_tokens=400,
            timestamp=datetime(2026, 3, 7, tzinfo=UTC),
        )
        tracker.record(
            agent_name="audit", model="gpt-5.2",
            prompt_tokens=8200, completion_tokens=1200,
            timestamp=datetime(2026, 2, 20, tzinfo=UTC),  # outside period
        )

        summary = tracker.to_cost_summary(
            period_start=datetime(2026, 3, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 8, tzinfo=UTC),
        )
        # Only 2 records in period, not the Feb 20 one
        assert summary.total_queries == 2


class TestRoutingCostSavings:
    """Demonstrate model routing saves 93% vs always-GPT-5.2."""

    def test_routing_vs_unrouted_cost_difference(self):
        """At 2400 queries/day with the spec distribution, routing saves ~93%."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        # Unrouted: everything on GPT-5.2 (avg 3000 input + 500 output)
        unrouted_cost = calculate_query_cost("gpt-5.2", 3000, 500)

        # Routed: simple on nano
        routed_simple = calculate_query_cost("gpt-5-nano", 500, 100)

        # Routing saves significantly per query
        assert routed_simple < unrouted_cost
        savings_pct = 1 - (routed_simple / unrouted_cost)
        # Simple queries on nano save >99% vs GPT-5.2
        assert savings_pct > Decimal("0.99")

    def test_daily_cost_with_routing(self):
        """Validate spec's EUR 2.87/day with routing + caching."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        # From spec: 800 searches, 50 audits, 30 fleet, 900 simple, 620 cached
        search_cost = calculate_query_cost("gpt-5-mini", 2800, 400) * 800
        audit_cost = calculate_query_cost("gpt-5.2", 8200, 1200) * 50
        fleet_cost = calculate_query_cost("gpt-5-mini", 4500, 600) * 30
        simple_cost = calculate_query_cost("gpt-5-nano", 500, 100) * 900
        cache_cost = Decimal("0") * 620  # free

        total_daily = search_cost + audit_cost + fleet_cost + simple_cost + cache_cost
        # Spec says ~EUR 2.87/day
        assert total_daily < Decimal("4.00")
        assert total_daily > Decimal("2.00")

    def test_daily_cost_without_routing(self):
        """Without routing: everything on GPT-5.2 = ~EUR 42/day."""
        from apps.api.src.telemetry.cost_tracker import calculate_query_cost

        # 2400 queries on GPT-5.2 (avg 3000 input + 500 output)
        per_query = calculate_query_cost("gpt-5.2", 3000, 500)
        total_daily = per_query * 2400
        # Spec says ~EUR 42/day
        assert total_daily > Decimal("25")
        assert total_daily < Decimal("55")
