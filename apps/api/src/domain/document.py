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
