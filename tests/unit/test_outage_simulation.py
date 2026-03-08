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
