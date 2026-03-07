"""Tests for the RBAC-filtered hybrid retriever.

Key test: same query, different users, different results.
The LLM never sees documents outside the user's authorization tier.
"""

from unittest.mock import AsyncMock, MagicMock

from qdrant_client.models import ScoredPoint

from apps.api.src.domain.document import SearchResult, UserContext
from apps.api.src.rag.retriever import SearchMode, hybrid_search


def _make_scored_point(
    doc_id: str,
    content: str,
    department_id: str,
    clearance_level: int,
    source_file: str,
    score: float = 0.9,
    chunk_index: int = 0,
) -> ScoredPoint:
    return ScoredPoint(
        id="fake-uuid",
        version=0,
        score=score,
        payload={
            "content": content,
            "document_id": doc_id,
            "department_id": department_id,
            "clearance_level": clearance_level,
            "source_file": source_file,
            "chunk_index": chunk_index,
        },
        vector=None,
    )


# Mock users
WAREHOUSE_WORKER = UserContext(user_id="max.weber", clearance_level=1, departments=["warehouse"])
HR_DIRECTOR = UserContext(
    user_id="katrin.fischer", clearance_level=3, departments=["hr", "management"]
)
CEO = UserContext(
    user_id="eva.richter",
    clearance_level=4,
    departments=["hr", "management", "legal", "logistics", "warehouse", "executive"],
)


class TestHybridSearch:
    async def test_returns_search_results(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(
            points=[
                _make_scored_point(
                    "DOC-001", "ISO 9001 quality manual", "warehouse", 1, "quality.pdf", 0.95
                ),
            ]
        )
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        results = await hybrid_search(
            query="ISO-9001",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
            top_k=5,
        )

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].document_id == "DOC-001"
        assert results[0].score == 0.95

    async def test_rbac_filter_passed_to_qdrant(self):
        """Verify the RBAC filter is applied at query time."""
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="compensation",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
        )

        # Verify query_points was called with a filter
        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        qdrant_filter = call_kwargs["query_filter"]
        assert qdrant_filter is not None
        assert len(qdrant_filter.must) == 2

        # Clearance filter should be lte=1 for warehouse worker
        clearance_cond = qdrant_filter.must[1]
        assert clearance_cond.range.lte == 1

    async def test_ceo_filter_allows_higher_clearance(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="compensation",
            user=CEO,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        clearance_cond = call_kwargs["query_filter"].must[1]
        assert clearance_cond.range.lte == 4

    async def test_empty_results(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        results = await hybrid_search(
            query="nonexistent topic",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
        )

        assert results == []

    async def test_results_ordered_by_score(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(
            points=[
                _make_scored_point("DOC-001", "High score", "warehouse", 1, "a.pdf", 0.95),
                _make_scored_point("DOC-002", "Low score", "warehouse", 1, "b.pdf", 0.70),
            ]
        )
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        results = await hybrid_search(
            query="test",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
        )

        assert len(results) == 2
        assert results[0].score >= results[1].score

    async def test_top_k_respected(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="test",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
            top_k=3,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        assert call_kwargs["limit"] == 3


class TestSearchModes:
    """Verify the three search modes call Qdrant differently."""

    async def test_dense_only_uses_dense_vector(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="quality standards",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
            mode=SearchMode.DENSE_ONLY,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        assert call_kwargs["using"] == "dense"
        assert "prefetch" not in call_kwargs
        mock_embed.assert_awaited_once()

    async def test_sparse_only_uses_bm25_vector(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="ISO-9001",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
            mode=SearchMode.SPARSE_ONLY,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        assert call_kwargs["using"] == "bm25"
        assert "prefetch" not in call_kwargs
        mock_embed.assert_not_awaited()  # No embedding needed for sparse

    async def test_hybrid_uses_prefetch_with_rrf(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="PharmaCorp penalty",
            user=CEO,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
            mode=SearchMode.HYBRID,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        assert "prefetch" in call_kwargs
        assert len(call_kwargs["prefetch"]) == 2  # dense + sparse
        mock_embed.assert_awaited_once()

    async def test_default_mode_is_hybrid(self):
        mock_qdrant = AsyncMock()
        mock_qdrant.query_points.return_value = MagicMock(points=[])
        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        await hybrid_search(
            query="test",
            user=WAREHOUSE_WORKER,
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed,
        )

        call_kwargs = mock_qdrant.query_points.call_args.kwargs
        assert "prefetch" in call_kwargs  # hybrid mode uses prefetch
