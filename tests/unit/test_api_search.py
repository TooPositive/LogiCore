"""Tests for the search and ingest API endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.core.domain.document import UserContext
from apps.api.src.main import app

MOCK_USERS = {
    "max.weber": UserContext(user_id="max.weber", clearance_level=1, departments=["warehouse"]),
    "katrin.fischer": UserContext(
        user_id="katrin.fischer", clearance_level=3, departments=["hr", "management"]
    ),
}


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestSearchEndpoint:
    async def test_search_returns_results(self, client):
        from apps.api.src.core.domain.document import SearchResult

        mock_results = [
            SearchResult(
                content="ISO 9001 quality manual",
                score=0.95,
                source="quality.pdf",
                document_id="DOC-001",
                chunk_index=0,
            )
        ]

        with (
            patch(
                "apps.api.src.core.api.v1.search.resolve_user_context",
                new_callable=AsyncMock,
                return_value=MOCK_USERS["max.weber"],
            ),
            patch(
                "apps.api.src.core.api.v1.search.get_qdrant_client",
                new_callable=AsyncMock,
            ),
            patch(
                "apps.api.src.core.api.v1.search.get_embeddings",
            ),
            patch(
                "apps.api.src.core.api.v1.search.hybrid_search",
                new_callable=AsyncMock,
                return_value=mock_results,
            ),
        ):
            resp = await client.post(
                "/api/v1/search",
                json={"query": "ISO-9001", "user_id": "max.weber", "top_k": 5},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["document_id"] == "DOC-001"
        assert data["query"] == "ISO-9001"

    async def test_search_unknown_user_returns_403(self, client):
        with patch(
            "apps.api.src.core.api.v1.search.resolve_user_context",
            new_callable=AsyncMock,
            side_effect=ValueError("Unknown user: nobody"),
        ):
            resp = await client.post(
                "/api/v1/search",
                json={"query": "test", "user_id": "nobody"},
            )

        assert resp.status_code == 403

    async def test_search_missing_query_returns_422(self, client):
        resp = await client.post(
            "/api/v1/search",
            json={"user_id": "max.weber"},
        )
        assert resp.status_code == 422


class TestIngestEndpoint:
    async def test_ingest_returns_chunk_count(self, client):
        from apps.api.src.core.api.v1.ingest import ALLOWED_DATA_DIR
        from apps.api.src.core.domain.document import IngestResponse

        mock_response = IngestResponse(document_id="DOC-NEW-001", chunks_created=5)
        # Use a path inside the allowed data directory
        fake_path = str(ALLOWED_DATA_DIR / "contracts" / "pharma.pdf")

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value="Contract content goes here."),
            patch(
                "apps.api.src.core.api.v1.ingest.get_qdrant_client",
                new_callable=AsyncMock,
            ),
            patch("apps.api.src.core.api.v1.ingest.get_embeddings"),
            patch(
                "apps.api.src.core.api.v1.ingest.ingest_document",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            resp = await client.post(
                "/api/v1/ingest",
                json={
                    "file_path": fake_path,
                    "department_id": "legal",
                    "clearance_level": 3,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "DOC-NEW-001"
        assert data["chunks_created"] == 5

    async def test_ingest_rejects_path_traversal(self, client):
        """Arbitrary file paths outside data/ are rejected."""
        resp = await client.post(
            "/api/v1/ingest",
            json={
                "file_path": "/etc/passwd",
                "department_id": "legal",
                "clearance_level": 2,
            },
        )
        assert resp.status_code == 403
