"""Data lineage tracking for EU AI Act Article 12 compliance.

Tracks the full chain: source document -> document version -> chunk -> embedding.
Every re-ingestion creates a new document version. Old versions are preserved
so audit entries can reference the exact document state at decision time.

Security model:
  1. Parameterized queries only ($1, $2, ...) -- no string interpolation
  2. source_hash enables tamper detection: re-hash the file and compare
  3. All methods accept an asyncpg connection for transaction sharing
"""

from uuid import UUID

from apps.api.src.domains.logicore.models.compliance import (
    ChunkVersion,
    DocumentVersion,
    LineageRecord,
)

# --- SQL (parameterized) ---

_INSERT_DOCUMENT_VERSION_SQL = """
INSERT INTO document_versions (
    document_id, version, source_hash, chunk_count
) VALUES (
    $1, $2, $3, $4
) RETURNING
    id, document_id, version, ingested_at, source_hash, chunk_count
"""

_INSERT_CHUNK_VERSION_SQL = """
INSERT INTO chunk_versions (
    document_version_id, chunk_index, content_hash, qdrant_point_id, embedding_model
) VALUES (
    $1, $2, $3, $4, $5
) RETURNING
    id, document_version_id, chunk_index, content_hash, qdrant_point_id, embedding_model
"""

_SELECT_DOCUMENT_VERSIONS_SQL = """
SELECT id, document_id, version, ingested_at, source_hash, chunk_count
FROM document_versions
WHERE document_id = $1
ORDER BY version ASC
"""

_SELECT_CHUNK_VERSIONS_SQL = """
SELECT id, document_version_id, chunk_index, content_hash, qdrant_point_id, embedding_model
FROM chunk_versions
WHERE document_version_id = $1
ORDER BY chunk_index ASC
"""

_SELECT_CHUNKS_FOR_DOCUMENT_SQL = """
SELECT cv.id, cv.document_version_id, cv.chunk_index, cv.content_hash,
       cv.qdrant_point_id, cv.embedding_model
FROM chunk_versions cv
JOIN document_versions dv ON cv.document_version_id = dv.id
WHERE dv.document_id = $1
ORDER BY dv.version ASC, cv.chunk_index ASC
"""

_SELECT_SOURCE_HASH_SQL = """
SELECT source_hash
FROM document_versions
WHERE document_id = $1 AND version = $2
"""


def _row_to_document_version(row: dict) -> DocumentVersion:
    """Convert a database row to a DocumentVersion model."""
    return DocumentVersion(
        id=row["id"],
        document_id=row["document_id"],
        version=row["version"],
        ingested_at=row["ingested_at"],
        source_hash=row["source_hash"],
        chunk_count=row["chunk_count"],
    )


def _row_to_chunk_version(row: dict) -> ChunkVersion:
    """Convert a database row to a ChunkVersion model."""
    return ChunkVersion(
        id=row["id"],
        document_version_id=row["document_version_id"],
        chunk_index=row["chunk_index"],
        content_hash=row["content_hash"],
        qdrant_point_id=row["qdrant_point_id"],
        embedding_model=row["embedding_model"],
    )


class DataLineageTracker:
    """Track data lineage: source document -> version -> chunks -> embeddings.

    All methods accept an asyncpg connection (not pool) so callers
    can wrap operations in the same transaction as audit writes.
    """

    async def record_document_version(
        self,
        conn,
        document_id: str,
        version: int,
        source_hash: str,
        chunk_count: int,
    ) -> DocumentVersion:
        """Record a new document version.

        Args:
            conn: asyncpg connection
            document_id: stable document identifier (e.g., "CTR-2024-001")
            version: version number (monotonically increasing)
            source_hash: SHA-256 of the source file content
            chunk_count: number of chunks produced from this version

        Returns:
            The persisted DocumentVersion with server-generated id and ingested_at.
        """
        row = await conn.fetchrow(
            _INSERT_DOCUMENT_VERSION_SQL,
            document_id,   # $1
            version,       # $2
            source_hash,   # $3
            chunk_count,   # $4
        )
        return _row_to_document_version(row)

    async def record_chunk_version(
        self,
        conn,
        document_version_id: UUID,
        chunk_index: int,
        content_hash: str,
        qdrant_point_id: str,
        embedding_model: str,
    ) -> ChunkVersion:
        """Record a chunk version linked to a document version.

        Args:
            conn: asyncpg connection
            document_version_id: FK to document_versions.id
            chunk_index: position of this chunk within the document
            content_hash: SHA-256 of the chunk text content
            qdrant_point_id: ID of the vector in Qdrant
            embedding_model: name of the embedding model used

        Returns:
            The persisted ChunkVersion with server-generated id.
        """
        row = await conn.fetchrow(
            _INSERT_CHUNK_VERSION_SQL,
            document_version_id,  # $1
            chunk_index,          # $2
            content_hash,         # $3
            qdrant_point_id,      # $4
            embedding_model,      # $5
        )
        return _row_to_chunk_version(row)

    async def get_document_versions(
        self, conn, document_id: str
    ) -> list[DocumentVersion]:
        """Get all versions of a document, ordered by version number.

        Args:
            conn: asyncpg connection
            document_id: stable document identifier

        Returns:
            List of DocumentVersion, oldest first.
        """
        rows = await conn.fetch(_SELECT_DOCUMENT_VERSIONS_SQL, document_id)
        return [_row_to_document_version(row) for row in rows]

    async def get_chunk_versions(
        self, conn, document_version_id: UUID
    ) -> list[ChunkVersion]:
        """Get all chunk versions for a specific document version.

        Args:
            conn: asyncpg connection
            document_version_id: FK to document_versions.id

        Returns:
            List of ChunkVersion, ordered by chunk_index.
        """
        rows = await conn.fetch(_SELECT_CHUNK_VERSIONS_SQL, document_version_id)
        return [_row_to_chunk_version(row) for row in rows]

    async def get_full_lineage(
        self, conn, document_id: str
    ) -> LineageRecord:
        """Get the full lineage for a document: all versions and all chunks.

        This is the key compliance query: given a document_id, return
        every version ever ingested and every chunk produced, with
        embedding model and Qdrant point references.

        Args:
            conn: asyncpg connection
            document_id: stable document identifier

        Returns:
            LineageRecord with versions and chunks populated.
        """
        doc_rows = await conn.fetch(_SELECT_DOCUMENT_VERSIONS_SQL, document_id)
        versions = [_row_to_document_version(row) for row in doc_rows]

        chunk_rows = await conn.fetch(_SELECT_CHUNKS_FOR_DOCUMENT_SQL, document_id)
        chunks = [_row_to_chunk_version(row) for row in chunk_rows]

        return LineageRecord(
            document_id=document_id,
            versions=versions,
            chunks=chunks,
        )

    async def verify_source_hash(
        self,
        conn,
        document_id: str,
        version: int,
        expected_hash: str,
    ) -> bool:
        """Verify a document version's source hash against an expected value.

        This is the tamper detection check: re-hash the source file and
        compare to the stored hash. If they differ, the source file was
        modified after ingestion.

        Args:
            conn: asyncpg connection
            document_id: stable document identifier
            version: version number to check
            expected_hash: SHA-256 hash to compare against

        Returns:
            True if hashes match, False if mismatch or version not found.
        """
        stored_hash = await conn.fetchval(
            _SELECT_SOURCE_HASH_SQL,
            document_id,    # $1
            version,        # $2
        )

        if stored_hash is None:
            return False

        return stored_hash == expected_hash
