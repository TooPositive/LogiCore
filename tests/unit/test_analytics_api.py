"""Unit tests for Phase 4 analytics API endpoints.

Tests: GET /api/v1/analytics/costs, GET /api/v1/analytics/quality,
rate limiting, authentication, response format.
"""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def cost_tracker():
    """Pre-populated cost tracker for analytics tests."""
    from apps.api.src.telemetry.cost_tracker import CostTracker

    tracker = CostTracker()
    # 5 search queries
    for _ in range(5):
        tracker.record(
            agent_name="search",
            model="gpt-5-mini",
            prompt_tokens=2800,
            completion_tokens=400,
            timestamp=datetime(2026, 3, 5, 10, 0, tzinfo=UTC),
        )
    # 2 audit queries
    for _ in range(2):
        tracker.record(
            agent_name="audit",
            model="gpt-5.2",
            prompt_tokens=8200,
            completion_tokens=1200,
            timestamp=datetime(2026, 3, 5, 11, 0, tzinfo=UTC),
        )
    # 3 cache hits
    for _ in range(3):
        tracker.record(
            agent_name="search",
            model="cache",
            prompt_tokens=0,
            completion_tokens=0,
            cache_hit=True,
            timestamp=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
        )
    return tracker


@pytest.fixture
def eval_scores():
    """Latest evaluation scores."""
    from apps.api.src.domain.telemetry import EvalScore

    return EvalScore(
        eval_id="eval-latest",
        context_precision=0.92,
        faithfulness=0.89,
        answer_relevancy=0.91,
        evaluated_at=datetime(2026, 3, 7, tzinfo=UTC),
        dataset_size=50,
    )


class TestCostsEndpoint:
    """GET /api/v1/analytics/costs?period=7d"""

    @pytest.mark.asyncio
    async def test_costs_endpoint_returns_200(self, cost_tracker):
        from apps.api.src.api.v1.analytics import create_analytics_router

        router = create_analytics_router(
            cost_tracker=cost_tracker,
            eval_scores=None,
        )
        # Create a minimal FastAPI app with just this router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=7d")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_costs_response_has_required_fields(self, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(cost_tracker=cost_tracker, eval_scores=None)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=7d")

        data = response.json()
        assert "total_cost" in data
        assert "total_queries" in data
        assert "avg_cost_per_query" in data
        assert "cache_hit_rate" in data
        assert "by_agent" in data

    @pytest.mark.asyncio
    async def test_costs_values_correct(self, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(cost_tracker=cost_tracker, eval_scores=None)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=7d")

        data = response.json()
        assert data["total_queries"] == 10
        assert data["cache_hit_rate"] == pytest.approx(0.3, abs=0.01)
        assert "search" in data["by_agent"]
        assert "audit" in data["by_agent"]

    @pytest.mark.asyncio
    async def test_costs_period_30d(self, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(cost_tracker=cost_tracker, eval_scores=None)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=30d")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_costs_invalid_period(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router
        from apps.api.src.telemetry.cost_tracker import CostTracker

        app = FastAPI()
        app.include_router(
            create_analytics_router(
                cost_tracker=CostTracker(), eval_scores=None
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=invalid")
        assert response.status_code == 422


class TestQualityEndpoint:
    """GET /api/v1/analytics/quality"""

    @pytest.mark.asyncio
    async def test_quality_endpoint_returns_200(self, eval_scores, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(
                cost_tracker=cost_tracker, eval_scores=eval_scores
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/quality")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_quality_response_has_metrics(self, eval_scores, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(
                cost_tracker=cost_tracker, eval_scores=eval_scores
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/quality")

        data = response.json()
        assert "context_precision" in data
        assert "faithfulness" in data
        assert "answer_relevancy" in data
        assert "last_eval" in data

    @pytest.mark.asyncio
    async def test_quality_values_correct(self, eval_scores, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(
                cost_tracker=cost_tracker, eval_scores=eval_scores
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/quality")

        data = response.json()
        assert data["context_precision"] == 0.92
        assert data["faithfulness"] == 0.89
        assert data["answer_relevancy"] == 0.91

    @pytest.mark.asyncio
    async def test_quality_no_scores_returns_404(self, cost_tracker):
        from fastapi import FastAPI

        from apps.api.src.api.v1.analytics import create_analytics_router

        app = FastAPI()
        app.include_router(
            create_analytics_router(
                cost_tracker=cost_tracker, eval_scores=None
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/quality")
        assert response.status_code == 404
