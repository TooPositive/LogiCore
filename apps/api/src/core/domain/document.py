"""Domain models for the Corporate Brain (RAG + RBAC) system."""

from pydantic import BaseModel, Field


class Document(BaseModel):
    document_id: str
    source_file: str
    department_id: str
    clearance_level: int = Field(ge=1, le=4)
    title: str


class Chunk(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    chunk_index: int = Field(ge=0)
    department_id: str
    clearance_level: int = Field(ge=1, le=4)
    source_file: str


class UserContext(BaseModel):
    user_id: str
    clearance_level: int = Field(ge=1, le=4)
    departments: list[str]


class SearchRequest(BaseModel):
    query: str
    user_id: str
    top_k: int = Field(default=5, ge=1, le=50)


class SearchResult(BaseModel):
    content: str
    score: float
    source: str
    document_id: str
    chunk_index: int


class EnhancedSearchResult(BaseModel):
    """Extended search result with pipeline metadata.

    Extends SearchResult fields with reranking scores and pipeline stage info.
    Used by enhanced_search() in Phase 2+. SearchResult remains for Phase 1.
    """

    content: str
    score: float  # final score (rerank_score if reranked, search_score if not)
    source: str
    document_id: str
    chunk_index: int
    search_score: float  # original vector/hybrid search score
    rerank_score: float | None = None  # cross-encoder score if reranked
    pipeline_stage: str = "search"  # "search" or "reranked"
    query_category: str | None = None  # from router: keyword/standard/vague/multi_hop


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str


class IngestRequest(BaseModel):
    file_path: str
    department_id: str
    clearance_level: int = Field(ge=1, le=4)
    title: str = ""


class IngestResponse(BaseModel):
    document_id: str
    chunks_created: int
