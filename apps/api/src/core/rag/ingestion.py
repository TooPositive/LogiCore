"""Document ingestion pipeline — chunking + embedding + Qdrant upsert."""

import uuid
from collections.abc import Callable, Coroutine

from qdrant_client import AsyncQdrantClient, models

from apps.api.src.core.domain.document import IngestResponse
from apps.api.src.core.infrastructure.qdrant.collections import COLLECTION_NAME
from apps.api.src.core.rag.sparse import text_to_sparse_vector


def chunk_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 50,
) -> list[str]:
    """Split text into overlapping chunks at word boundaries."""
    if not text or not text.strip():
        return []

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0

    while start < len(words):
        # Take chunk_size worth of characters, but count by building up words
        end = start
        current_len = 0
        while end < len(words):
            sep = 1 if current_len > 0 else 0
            if current_len + len(words[end]) + sep > chunk_size:
                break
            current_len += len(words[end]) + sep
            end += 1

        # If we couldn't fit even one word, take at least one
        if end == start:
            end = start + 1

        chunk = " ".join(words[start:end])
        chunks.append(chunk)

        # Move forward by (end - start) words minus overlap words
        overlap_words = max(1, overlap // 5)  # approximate overlap in words
        advance = max(1, (end - start) - overlap_words)
        start += advance

        if end >= len(words):
            break

    return chunks


async def ingest_document(
    text: str,
    document_id: str,
    department_id: str,
    clearance_level: int,
    source_file: str,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[list[str]], Coroutine],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> IngestResponse:
    """Chunk text, embed, and upsert into Qdrant."""
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)

    if not chunks:
        return IngestResponse(document_id=document_id, chunks_created=0)

    # Embed all chunks
    embeddings = await embed_fn(chunks)

    # Build Qdrant points with both dense + BM25 sparse vectors
    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid4())
        sparse = text_to_sparse_vector(chunk)
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": embedding,
                    "bm25": sparse,
                },
                payload={
                    "content": chunk,
                    "document_id": document_id,
                    "department_id": department_id,
                    "clearance_level": clearance_level,
                    "source_file": source_file,
                    "chunk_index": i,
                },
            )
        )

    await qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
    )

    return IngestResponse(document_id=document_id, chunks_created=len(chunks))
