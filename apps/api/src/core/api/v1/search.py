"""POST /api/v1/search — RBAC-filtered hybrid search."""

from fastapi import APIRouter, HTTPException

from apps.api.src.core.domain.document import SearchRequest, SearchResponse
from apps.api.src.core.infrastructure.qdrant.client import get_qdrant_client
from apps.api.src.core.rag.embeddings import get_embeddings
from apps.api.src.core.rag.retriever import hybrid_search
from apps.api.src.core.security.rbac import resolve_user_context

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    try:
        user = await resolve_user_context(request.user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    qdrant = await get_qdrant_client()
    embeddings = get_embeddings()

    results = await hybrid_search(
        query=request.query,
        user=user,
        qdrant_client=qdrant,
        embed_fn=embeddings.aembed_query,
        top_k=request.top_k,
    )

    return SearchResponse(results=results, query=request.query)
