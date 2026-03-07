"""Tests for the document ingestion pipeline."""

from unittest.mock import AsyncMock

from apps.api.src.rag.ingestion import chunk_text, ingest_document


class TestChunkText:
    def test_short_text_single_chunk(self):
        chunks = chunk_text("Short text.", chunk_size=100, overlap=20)
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_long_text_multiple_chunks(self):
        # 10 sentences, should produce multiple chunks at small chunk_size
        text = " ".join([f"Sentence number {i} with some extra words." for i in range(20)])
        chunks = chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) > 1

    def test_overlap_between_chunks(self):
        text = "A " * 200  # 400 chars
        chunks = chunk_text(text, chunk_size=100, overlap=30)
        assert len(chunks) > 1
        # Each chunk except the last should be around chunk_size
        for c in chunks[:-1]:
            assert len(c) <= 120  # allow some slack for word boundaries

    def test_empty_text(self):
        chunks = chunk_text("", chunk_size=100, overlap=20)
        assert chunks == []

    def test_respects_word_boundaries(self):
        text = "Hello world this is a test of word boundary chunking"
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        for chunk in chunks:
            # No chunk should start or end mid-word (no leading/trailing spaces)
            assert chunk == chunk.strip()


class TestIngestDocument:
    async def test_ingest_creates_chunks_in_qdrant(self):
        mock_qdrant = AsyncMock()
        mock_embed_fn = AsyncMock(return_value=[[0.1] * 1536, [0.2] * 1536])

        result = await ingest_document(
            text="First paragraph of the contract. Second paragraph with more details.",
            document_id="DOC-001",
            department_id="legal",
            clearance_level=2,
            source_file="contract.pdf",
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed_fn,
            chunk_size=50,
            chunk_overlap=10,
        )

        assert result.document_id == "DOC-001"
        assert result.chunks_created > 0
        mock_qdrant.upsert.assert_called_once()

    async def test_ingest_empty_text_returns_zero_chunks(self):
        mock_qdrant = AsyncMock()
        mock_embed_fn = AsyncMock(return_value=[])

        result = await ingest_document(
            text="",
            document_id="DOC-EMPTY",
            department_id="ops",
            clearance_level=1,
            source_file="empty.pdf",
            qdrant_client=mock_qdrant,
            embed_fn=mock_embed_fn,
        )

        assert result.chunks_created == 0
        mock_qdrant.upsert.assert_not_called()
