"""E2E test fixtures — full app with real services."""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


@pytest.fixture
async def test_client():
    """Async HTTP client against the real FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
