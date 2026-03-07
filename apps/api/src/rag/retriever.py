"""Hybrid search retriever with RBAC filtering.

Three search modes:
- dense_only: Pure semantic search (text-embedding-3-small/large)
- sparse_only: Pure BM25 keyword search (exact matches for codes, IDs)
- hybrid (default): Prefetch both → fuse with Reciprocal Rank Fusion (RRF)

RBAC filters are applied at query time — the LLM never sees unauthorized documents.

Phase 2 adds enhanced_search() — a pipeline wrapper around hybrid_search() that
optionally applies: sanitize → route → transform → search → rerank.
hybrid_search() is unchanged for backward compatibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum

from qdrant_client import AsyncQdrantClient, models

from apps.api.src.domain.document import EnhancedSearchResult, SearchResult, UserContext
from apps.api.src.infrastructure.qdrant.collections import COLLECTION_NAME
from apps.api.src.rag.reranker import BaseReranker
from apps.api.src.rag.sparse import text_to_sparse_vector
from apps.api.src.security.rbac import build_qdrant_filter

logger = logging.getLogger(__name__)


class SearchMode(StrEnum):
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# Phase 1 — hybrid_search (UNCHANGED)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Phase 2 — Enhanced retrieval pipeline
# ---------------------------------------------------------------------------


@dataclass
class RetrievalPipelineConfig:
    """Configure which pipeline stages are active.

    Each field is optional. Set to None to skip that stage.
    The pipeline executes in order: sanitize -> route -> transform -> search -> rerank.
    """

    reranker: BaseReranker | None = None
    query_router: object | None = None  # QueryRouter (avoid circular import)
    hyde_transformer: object | None = None  # HyDETransformer
    multi_query_transformer: object | None = None  # MultiQueryTransformer
    query_decomposer: object | None = None  # QueryDecomposer
    sanitizer: object | None = None  # QuerySanitizer
    rerank_top_k: int = 20  # fetch this many from search, then rerank to top_k


async def _run_single_search(
    query: str,
    user: UserContext,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[str], Coroutine],
    top_k: int,
    mode: SearchMode,
) -> list[SearchResult]:
    """Run a single hybrid_search call. Thin wrapper for reuse."""
    return await hybrid_search(
        query=query,
        user=user,
        qdrant_client=qdrant_client,
        embed_fn=embed_fn,
        top_k=top_k,
        mode=mode,
    )


def _deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate by (document_id, chunk_index), keeping highest score."""
    seen: dict[tuple[str, int], SearchResult] = {}
    for r in results:
        key = (r.document_id, r.chunk_index)
        if key not in seen or r.score > seen[key].score:
            seen[key] = r
    # Return sorted by score descending
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


def _search_results_to_enhanced(
    results: list[SearchResult],
    query_category: str | None = None,
) -> list[EnhancedSearchResult]:
    """Convert SearchResult list to EnhancedSearchResult list (no reranking)."""
    return [
        EnhancedSearchResult(
            content=r.content,
            score=r.score,
            source=r.source,
            document_id=r.document_id,
            chunk_index=r.chunk_index,
            search_score=r.score,
            rerank_score=None,
            pipeline_stage="search",
            query_category=query_category,
        )
        for r in results
    ]


async def enhanced_search(
    query: str,
    user: UserContext,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[str], Coroutine],
    top_k: int = 5,
    mode: SearchMode = SearchMode.HYBRID,
    pipeline: RetrievalPipelineConfig | None = None,
) -> list[EnhancedSearchResult]:
    """Enhanced retrieval with optional re-ranking, query transforms, and routing.

    Pipeline: sanitize -> route -> transform -> search -> rerank -> return
    Each stage is optional. If pipeline is None, behaves like hybrid_search()
    but returns EnhancedSearchResult instead of SearchResult.
    """
    # No pipeline — simple passthrough
    if pipeline is None:
        results = await hybrid_search(
            query=query,
            user=user,
            qdrant_client=qdrant_client,
            embed_fn=embed_fn,
            top_k=top_k,
            mode=mode,
        )
        return _search_results_to_enhanced(results)

    # --- Stage 1: Sanitize ---
    working_query = query
    if pipeline.sanitizer is not None:
        working_query = pipeline.sanitizer.sanitize(query)

    # --- Stage 2: Route ---
    query_category: str | None = None
    skip_transforms = False
    skip_reranking = False

    if pipeline.query_router is not None:
        try:
            classification = await pipeline.query_router.classify(working_query)
            query_category = classification.category.value
        except Exception:
            logger.warning("Query router failed, defaulting to STANDARD")
            query_category = "standard"

        if query_category == "keyword":
            skip_transforms = True
            skip_reranking = True
    else:
        # No router — default behavior: apply whatever stages are configured
        pass

    # --- Stage 3: Transform ---
    search_query = working_query
    multi_queries: list[str] | None = None

    if not skip_transforms:
        # VAGUE -> HyDE
        if query_category == "vague" and pipeline.hyde_transformer is not None:
            try:
                transform_result = await pipeline.hyde_transformer.transform(working_query)
                if transform_result.transformed_queries:
                    search_query = transform_result.transformed_queries[0]
            except Exception:
                logger.warning("HyDE transform failed, using original query")

        # MULTI_HOP -> decompose
        elif query_category == "multi_hop" and pipeline.query_decomposer is not None:
            try:
                transform_result = await pipeline.query_decomposer.transform(working_query)
                if transform_result.transformed_queries:
                    multi_queries = transform_result.transformed_queries
            except Exception:
                logger.warning("Query decomposition failed, using original query")

        # No router but HyDE configured -> apply HyDE
        elif query_category is None and pipeline.hyde_transformer is not None:
            try:
                transform_result = await pipeline.hyde_transformer.transform(working_query)
                if transform_result.transformed_queries:
                    search_query = transform_result.transformed_queries[0]
            except Exception:
                logger.warning("HyDE transform failed, using original query")

        # No router but multi-query configured -> apply multi-query
        elif query_category is None and pipeline.multi_query_transformer is not None:
            try:
                transform_result = await pipeline.multi_query_transformer.transform(working_query)
                if transform_result.transformed_queries:
                    multi_queries = transform_result.transformed_queries
            except Exception:
                logger.warning("Multi-query transform failed, using original query")

    # --- Stage 4: Search ---
    # Determine search limit: if reranking, fetch more; otherwise top_k
    search_limit = top_k
    if pipeline.reranker is not None and not skip_reranking:
        search_limit = pipeline.rerank_top_k

    if multi_queries is not None:
        # Multi-query or decomposed: run multiple searches, merge
        all_results: list[SearchResult] = []
        for sub_query in multi_queries:
            sub_results = await _run_single_search(
                query=sub_query,
                user=user,
                qdrant_client=qdrant_client,
                embed_fn=embed_fn,
                top_k=search_limit,
                mode=mode,
            )
            all_results.extend(sub_results)
        search_results = _deduplicate_results(all_results)[:search_limit]
    else:
        # Single query search (possibly HyDE-transformed)
        # For HyDE: embed_fn receives the hypothetical answer
        if search_query != working_query:
            # HyDE: create a wrapper embed_fn that embeds the transformed query
            original_embed_fn = embed_fn

            async def _hyde_embed_fn(q: str) -> list[float]:
                return await original_embed_fn(search_query)

            search_results = await _run_single_search(
                query=working_query,  # original query for BM25
                user=user,
                qdrant_client=qdrant_client,
                embed_fn=_hyde_embed_fn,
                top_k=search_limit,
                mode=mode,
            )
        else:
            search_results = await _run_single_search(
                query=working_query,
                user=user,
                qdrant_client=qdrant_client,
                embed_fn=embed_fn,
                top_k=search_limit,
                mode=mode,
            )

    # --- Stage 5: Rerank ---
    if pipeline.reranker is not None and not skip_reranking and search_results:
        try:
            reranked = await pipeline.reranker.rerank(
                query=working_query,
                results=search_results,
                top_k=top_k,
            )
            # Convert RerankResult -> EnhancedSearchResult
            return [
                EnhancedSearchResult(
                    content=rr.content,
                    score=rr.rerank_score,
                    source=rr.source,
                    document_id=rr.document_id,
                    chunk_index=rr.chunk_index,
                    search_score=rr.original_score,
                    rerank_score=rr.rerank_score,
                    pipeline_stage="reranked",
                    query_category=query_category,
                )
                for rr in reranked
            ]
        except Exception:
            logger.warning("Reranker failed, returning un-reranked results")

    # Return un-reranked results (possibly truncated to top_k)
    return _search_results_to_enhanced(search_results[:top_k], query_category)
