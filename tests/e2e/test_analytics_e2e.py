"""E2E tests for analytics endpoints through the main app."""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


class TestAnalyticsE2E:
    """Analytics endpoints accessible through the main FastAPI app."""

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_costs_endpoint_reachable(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=7d")
        assert response.status_code == 200
        data = response.json()
        assert "total_cost" in data
        assert "cache_hit_rate" in data

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_quality_endpoint_returns_404_no_scores(self):
        """No eval scores loaded yet -> 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/quality")
        assert response.status_code == 404

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_costs_invalid_period_returns_422(self):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/analytics/costs?period=abc")
        assert response.status_code == 422

    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_health_still_works(self):
        """Regression: adding analytics doesn't break existing routes."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/health")
        assert response.status_code == 200
