"""Tests for Phase 1 domain models."""

import uuid

from apps.api.src.domain.document import (
    Chunk,
    Document,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UserContext,
)


class TestDocument:
    def test_create_document(self):
        doc = Document(
            document_id="DOC-HR-001",
            source_file="hr-manual.pdf",
            department_id="hr",
            clearance_level=2,
            title="HR Policy Manual",
        )
        assert doc.document_id == "DOC-HR-001"
        assert doc.clearance_level == 2

    def test_clearance_level_bounds(self):
        doc = Document(
            document_id="DOC-001",
            source_file="test.pdf",
            department_id="ops",
            clearance_level=1,
            title="Test",
        )
        assert 1 <= doc.clearance_level <= 4


class TestChunk:
    def test_create_chunk(self):
        chunk = Chunk(
            chunk_id=str(uuid.uuid4()),
            document_id="DOC-HR-001",
            content="Section 4.2: Quality management requirements...",
            chunk_index=0,
            department_id="hr",
            clearance_level=2,
            source_file="hr-manual.pdf",
        )
        assert chunk.chunk_index == 0
        assert chunk.department_id == "hr"

    def test_chunk_content_not_empty(self):
        chunk = Chunk(
            chunk_id="c1",
            document_id="DOC-001",
            content="Some content",
            chunk_index=0,
            department_id="ops",
            clearance_level=1,
            source_file="test.pdf",
        )
        assert len(chunk.content) > 0


class TestUserContext:
    def test_user_with_single_department(self):
        user = UserContext(
            user_id="max.weber",
            clearance_level=1,
            departments=["warehouse"],
        )
        assert user.clearance_level == 1
        assert "warehouse" in user.departments

    def test_user_with_multiple_departments(self):
        user = UserContext(
            user_id="katrin.fischer",
            clearance_level=3,
            departments=["hr", "management"],
        )
        assert len(user.departments) == 2


class TestSearchModels:
    def test_search_request(self):
        req = SearchRequest(
            query="ISO-9001 quality requirements",
            user_id="max.weber",
            top_k=5,
        )
        assert req.top_k == 5

    def test_search_request_defaults(self):
        req = SearchRequest(query="test", user_id="user1")
        assert req.top_k == 5  # default

    def test_search_result(self):
        result = SearchResult(
            content="Quality management section...",
            score=0.92,
            source="hr-manual.pdf",
            document_id="DOC-HR-001",
            chunk_index=0,
        )
        assert result.score == 0.92

    def test_search_response(self):
        resp = SearchResponse(
            results=[
                SearchResult(
                    content="test",
                    score=0.9,
                    source="test.pdf",
                    document_id="DOC-001",
                    chunk_index=0,
                )
            ],
            query="test query",
        )
        assert len(resp.results) == 1


class TestIngestModels:
    def test_ingest_request(self):
        req = IngestRequest(
            file_path="/data/contracts/pharma.pdf",
            department_id="legal",
            clearance_level=3,
        )
        assert req.clearance_level == 3

    def test_ingest_response(self):
        resp = IngestResponse(
            document_id="DOC-LEGAL-001",
            chunks_created=12,
        )
        assert resp.chunks_created == 12
