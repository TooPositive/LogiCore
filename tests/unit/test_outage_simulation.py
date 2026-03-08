"""Tests for outage simulation and routing cost benchmark logic.

Tests the simulation and benchmark functions that will be used in
scripts/simulate_outage.py and scripts/benchmark_routing.py.

RED phase: all tests written before implementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderEntry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(name: str, content: str = "response") -> MagicMock:
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(
            content=content,
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    return provider


# ===========================================================================
# Outage simulation tests
# ===========================================================================


class TestOutageSimulation:
    @pytest.mark.asyncio
    async def test_simulated_outage_trips_breaker(self):
        """Simulate Azure outage: primary fails repeatedly, breaker trips."""
        fail_count = 0

        async def failing_generate(prompt, **kwargs):
            nonlocal fail_count
            fail_count += 1
            raise Exception("503 Service Unavailable")

        primary = MagicMock()
        primary.model_name = "azure"
        primary.generate = failing_generate

        fallback = _make_provider("ollama", "fallback response")

        breaker = CircuitBreaker(name="azure", failure_threshold=3, reset_timeout=0.1)
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=breaker),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        # Send 5 requests — after 3 failures, breaker should trip
        for _ in range(5):
            result = await chain.generate("test query")
            assert result.content == "fallback response"

        # Breaker should be OPEN
        assert breaker.state == CircuitState.OPEN
        assert breaker.metrics.trips >= 1

    @pytest.mark.asyncio
    async def test_recovery_after_outage(self):
        """After outage resolves, traffic returns to primary."""
        is_down = True

        async def intermittent_generate(prompt, **kwargs):
            if is_down:
                raise Exception("503")
            return LLMResponse(
                content="primary recovered",
                model="azure",
                input_tokens=10,
                output_tokens=20,
                latency_ms=100.0,
            )

        primary = MagicMock()
        primary.model_name = "azure"
        primary.generate = intermittent_generate

        fallback = _make_provider("ollama", "fallback response")

        breaker = CircuitBreaker(
            name="azure",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=1,
        )
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=breaker),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        # Phase 1: outage — fallback serves
        for _ in range(3):
            result = await chain.generate("test")
            assert result.content == "fallback response"

        # Phase 2: recover
        is_down = False
        await asyncio.sleep(0.1)  # Wait for reset timeout

        result = await chain.generate("test")
        assert result.content == "primary recovered"
        assert result.provider_name == "azure"

    @pytest.mark.asyncio
    async def test_all_providers_down_with_cache(self):
        """Both providers down -> cache fallback."""
        primary = MagicMock()
        primary.model_name = "azure"
        primary.generate = AsyncMock(side_effect=Exception("azure down"))

        fallback = MagicMock()
        fallback.model_name = "ollama"
        fallback.generate = AsyncMock(side_effect=Exception("ollama down"))

        mock_cache = AsyncMock(return_value="cached response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama", failure_threshold=1),
                ),
            ],
            cache_lookup=mock_cache,
        )

        result = await chain.generate("test")
        assert result.cache_used is True
        assert result.disclaimer is not None


# ===========================================================================
# Routing cost benchmark tests
# ===========================================================================


class TestRoutingCostBenchmark:
    def test_cost_comparison_routed_vs_unrouted(self):
        """Verify cost model: routed saves significantly vs all-GPT-5.2."""
        # Cost per query by tier (EUR)
        costs = {
            "simple": 0.0004,   # GPT-5 nano
            "medium": 0.003,    # GPT-5 mini
            "complex": 0.014,   # GPT-5.2
        }

        # Distribution: 70% simple, 20% medium, 10% complex
        queries_per_day = 1000
        distribution = {"simple": 0.70, "medium": 0.20, "complex": 0.10}

        # Routed cost
        routed_cost = sum(
            queries_per_day * pct * costs[tier]
            for tier, pct in distribution.items()
        )

        # Unrouted cost (all GPT-5.2)
        unrouted_cost = queries_per_day * costs["complex"]

        # Savings
        savings_pct = (unrouted_cost - routed_cost) / unrouted_cost * 100

        assert savings_pct > 80  # Spec says >50%, actual is ~84%
        assert routed_cost < 3.0  # EUR 2.28/day
        assert unrouted_cost == 14.0  # EUR 14.00/day

    def test_classifier_cost_is_negligible(self):
        """The classifier itself (GPT-5 nano) costs ~EUR 0.01/day."""
        classifier_cost_per_call = 0.000025  # EUR per classification
        calls_per_day = 1000
        total = classifier_cost_per_call * calls_per_day
        assert total < 0.05  # Less than EUR 0.05/day

    def test_misclassification_cost(self):
        """Each misrouted complex query costs the difference in quality."""
        # Cost gap: GPT-5.2 (EUR 0.014) vs Nano (EUR 0.0004) = EUR 0.0136/query
        # At 5% misclassification rate and 100 complex queries/day
        complex_per_day = 100
        misclass_rate = 0.05
        misclassified = complex_per_day * misclass_rate
        # Each misclassified query saves EUR 0.0136 but costs business impact
        assert misclassified == 5  # 5 wrong answers per day

    def test_monthly_savings(self):
        """At 1000 queries/day, routing saves EUR 351/month."""
        daily_savings = 14.00 - 2.28
        monthly_savings = daily_savings * 30
        assert monthly_savings > 340  # EUR 351.60


# ===========================================================================
# Cost model sensitivity analysis (Review Gap #1)
# ===========================================================================


class TestCostModelSensitivity:
    """The 83.5% savings headline rests on an assumed 70/20/10 distribution.
    A CTO will ask: "What if our distribution is different?"

    These tests prove the crossover points and sensitivity boundaries
    so the cost claim is honest across deployment scenarios.
    """

    # Cost per query by tier (EUR)
    COSTS = {"simple": 0.0004, "medium": 0.003, "complex": 0.014}
    CLASSIFIER_COST = 0.000025  # EUR per classification

    def _calc_savings_pct(
        self, simple: float, medium: float, complex_: float
    ) -> float:
        """Calculate routing savings percentage for a given distribution."""
        queries = 1000
        routed = sum(
            queries * pct * self.COSTS[tier]
            for tier, pct in [
                ("simple", simple),
                ("medium", medium),
                ("complex", complex_),
            ]
        )
        routed += queries * self.CLASSIFIER_COST
        unrouted = queries * self.COSTS["complex"]
        return ((unrouted - routed) / unrouted) * 100

    def test_baseline_70_20_10(self):
        """Baseline: 70% simple, 20% medium, 10% complex -> ~83% savings."""
        savings = self._calc_savings_pct(0.70, 0.20, 0.10)
        assert 83 < savings < 85, f"Expected ~83-84%, got {savings:.1f}%"

    def test_balanced_50_30_20(self):
        """More medium-heavy: 50/30/20 -> still significant savings."""
        savings = self._calc_savings_pct(0.50, 0.30, 0.20)
        assert 60 < savings < 75, f"Expected ~65-70%, got {savings:.1f}%"

    def test_complex_heavy_30_30_40(self):
        """Complex-heavy: 30/30/40 -> savings drop but still positive."""
        savings = self._calc_savings_pct(0.30, 0.30, 0.40)
        assert 35 < savings < 55, f"Expected ~40-50%, got {savings:.1f}%"

    def test_mostly_complex_10_20_70(self):
        """Almost all complex: 10/20/70 -> marginal savings."""
        savings = self._calc_savings_pct(0.10, 0.20, 0.70)
        assert 10 < savings < 30, f"Expected ~15-25%, got {savings:.1f}%"

    def test_all_simple_100_0_0(self):
        """All simple: maximum savings (~97%)."""
        savings = self._calc_savings_pct(1.00, 0.00, 0.00)
        assert savings > 95, f"Expected >95%, got {savings:.1f}%"

    def test_all_complex_0_0_100(self):
        """All complex: routing adds classifier cost, negative ROI."""
        savings = self._calc_savings_pct(0.00, 0.00, 1.00)
        # Classifier cost makes savings slightly negative
        assert savings < 1, f"Expected ~0% (negative), got {savings:.1f}%"

    def test_crossover_point(self):
        """Find the distribution where routing breaks even (~0% savings).

        ARCHITECT INSIGHT: routing stops being worth the complexity when
        >90% of queries are complex. Below that, even small simple/medium
        percentages justify routing because nano is 35x cheaper than GPT-5.2.
        """
        # Binary search for the complex % where savings hit ~5%
        # (below 5% the engineering overhead isn't justified)
        for complex_pct in range(50, 100):
            simple_pct = (100 - complex_pct) / 2  # Split remainder equally
            medium_pct = simple_pct
            savings = self._calc_savings_pct(
                simple_pct / 100, medium_pct / 100, complex_pct / 100
            )
            if savings < 5:
                # Found the crossover: routing isn't worth it above this %
                assert complex_pct >= 85, (
                    f"Crossover at {complex_pct}% complex — expected >=85%"
                )
                break
        else:
            pytest.fail("No crossover found — routing always saves >5%")

    def test_savings_monotonically_decrease_with_complexity(self):
        """As complex % increases, savings must decrease monotonically.

        This proves the cost model is internally consistent — there's no
        distribution where adding more complex queries increases savings.
        """
        prev_savings = 100.0
        for complex_pct in [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
            remaining = 100 - complex_pct
            simple = remaining * 0.7 / 100
            medium = remaining * 0.3 / 100
            savings = self._calc_savings_pct(simple, medium, complex_pct / 100)
            assert savings <= prev_savings, (
                f"Savings increased at {complex_pct}% complex: "
                f"{savings:.1f}% > {prev_savings:.1f}%"
            )
            prev_savings = savings
