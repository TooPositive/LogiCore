"""Tests for resilience analytics endpoint.

GET /api/v1/analytics/resilience — circuit breaker states, routing distribution,
fallback counts, cache fallback hits.

RED phase: all tests written before implementation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
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


def _make_test_chain() -> ProviderChain:
    """Build a chain with known state for testing."""
    p1 = _make_provider("azure")
    p2 = _make_provider("ollama")
    return ProviderChain(
        providers=[
            ProviderEntry(provider=p1, breaker=CircuitBreaker(name="azure")),
            ProviderEntry(provider=p2, breaker=CircuitBreaker(name="ollama")),
        ]
    )


# ===========================================================================
# Analytics endpoint
# ===========================================================================


class TestResilienceAnalytics:
    @pytest.mark.asyncio
    async def test_endpoint_returns_200(self):
        from apps.api.src.core.api.v1.analytics import create_analytics_router
        from apps.api.src.core.telemetry.cost_tracker import CostTracker

        from fastapi import FastAPI

        chain = _make_test_chain()
        app = FastAPI()
        cost_tracker = CostTracker()
        router = create_analytics_router(
            cost_tracker=cost_tracker,
            eval_scores=None,
            provider_chain=chain,
        )
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/resilience")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_endpoint_returns_provider_states(self):
        from apps.api.src.core.api.v1.analytics import create_analytics_router
        from apps.api.src.core.telemetry.cost_tracker import CostTracker

        from fastapi import FastAPI

        chain = _make_test_chain()
        app = FastAPI()
        cost_tracker = CostTracker()
        router = create_analytics_router(
            cost_tracker=cost_tracker,
            eval_scores=None,
            provider_chain=chain,
        )
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/resilience")

        data = response.json()
        assert "provider_states" in data
        assert len(data["provider_states"]) == 2
        assert data["provider_states"][0]["name"] == "azure"
        assert data["provider_states"][0]["state"] == "CLOSED"

    @pytest.mark.asyncio
    async def test_endpoint_returns_routing_stats(self):
        from apps.api.src.core.api.v1.analytics import create_analytics_router
        from apps.api.src.core.telemetry.cost_tracker import CostTracker

        from fastapi import FastAPI

        chain = _make_test_chain()
        # Generate some traffic
        await chain.generate("hello")
        await chain.generate("world")

        app = FastAPI()
        cost_tracker = CostTracker()
        router = create_analytics_router(
            cost_tracker=cost_tracker,
            eval_scores=None,
            provider_chain=chain,
        )
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/resilience")

        data = response.json()
        assert "routing_stats" in data
        assert data["routing_stats"]["total_requests"] == 2
        assert "azure" in data["routing_stats"]["by_provider"]

    @pytest.mark.asyncio
    async def test_endpoint_without_chain_returns_empty(self):
        """If no chain is provided, endpoint returns empty state."""
        from apps.api.src.core.api.v1.analytics import create_analytics_router
        from apps.api.src.core.telemetry.cost_tracker import CostTracker

        from fastapi import FastAPI

        app = FastAPI()
        cost_tracker = CostTracker()
        router = create_analytics_router(
            cost_tracker=cost_tracker,
            eval_scores=None,
        )
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/resilience")

        data = response.json()
        assert data["provider_states"] == []
        assert data["routing_stats"]["total_requests"] == 0
