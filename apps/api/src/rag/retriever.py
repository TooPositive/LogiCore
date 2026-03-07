"""Hybrid search retriever with RBAC filtering.

Three search modes:
- dense_only: Pure semantic search (text-embedding-3-small/large)
- sparse_only: Pure BM25 keyword search (exact matches for codes, IDs)
- hybrid (default): Prefetch both → fuse with Reciprocal Rank Fusion (RRF)

RBAC filters are applied at query time — the LLM never sees unauthorized documents.
"""

from collections.abc import Callable, Coroutine
from enum import StrEnum

from qdrant_client import AsyncQdrantClient, models

from apps.api.src.domain.document import SearchResult, UserContext
from apps.api.src.infrastructure.qdrant.collections import COLLECTION_NAME
from apps.api.src.rag.sparse import text_to_sparse_vector
from apps.api.src.security.rbac import build_qdrant_filter


class SearchMode(StrEnum):
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"


async def hybrid_search(
    query: str,
    user: UserContext,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[str], Coroutine],
    top_k: int = 5,
    mode: SearchMode = SearchMode.HYBRID,
) -> list[SearchResult]:
    """Execute RBAC-filtered search against Qdrant.

    Args:
        query: User's search query
        user: Authenticated user context (clearance + departments)
        qdrant_client: Qdrant async client
        embed_fn: Async function that embeds a query string -> vector
        top_k: Number of results to return
        mode: Search strategy — dense_only, sparse_only, or hybrid (RRF)
    """
    rbac_filter = build_qdrant_filter(user)
    prefetch_limit = top_k * 4  # Over-fetch for better fusion quality

    if mode == SearchMode.DENSE_ONLY:
        query_vector = await embed_fn(query)
        response = await qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            using="dense",
            query_filter=rbac_filter,
            limit=top_k,
            with_payload=True,
        )

    elif mode == SearchMode.SPARSE_ONLY:
        sparse_vector = text_to_sparse_vector(query)
        response = await qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            query=sparse_vector,
            using="bm25",
            query_filter=rbac_filter,
            limit=top_k,
            with_payload=True,
        )

    else:  # HYBRID — prefetch both, fuse with RRF
        query_vector = await embed_fn(query)
        sparse_vector = text_to_sparse_vector(query)

        response = await qdrant_client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=query_vector,
                    using="dense",
                    limit=prefetch_limit,
                ),
                models.Prefetch(
                    query=sparse_vector,
                    using="bm25",
                    limit=prefetch_limit,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=rbac_filter,
            limit=top_k,
            with_payload=True,
        )

    results = []
    for point in response.points:
        results.append(
            SearchResult(
                content=point.payload["content"],
                score=point.score,
                source=point.payload["source_file"],
                document_id=point.payload["document_id"],
                chunk_index=point.payload["chunk_index"],
            )
        )

    return results
