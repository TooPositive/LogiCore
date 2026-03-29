"""Unit tests for Phase 8 data lineage tracking.

Tests cover:
- record_document_version(): INSERT with parameterized SQL, returns DocumentVersion
- record_chunk_version(): INSERT with parameterized SQL, returns ChunkVersion
- get_document_versions(): fetch all versions for a document_id
- get_chunk_versions(): fetch chunks for a document_version_id
- get_full_lineage(): returns complete chain (doc versions -> chunks -> embedding info)
- verify_source_hash(): tamper detection for document source files
- Multiple document versions tracked (v1, v2, v3)
- SQL injection in document_id blocked
- Chunk versions reference correct document version

All tests use mocked asyncpg connections (no Docker dependencies).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import (
    ChunkVersion,
    DocumentVersion,
    LineageRecord,
)


def _make_doc_version_row(**overrides) -> dict:
    """Factory for document_versions database row."""
    defaults = {
        "id": uuid4(),
        "document_id": "CTR-2024-001",
        "version": 1,
        "ingested_at": datetime.now(UTC),
        "source_hash": "abc123def456" * 5 + "abcd",  # 64-char SHA-256 hex
        "chunk_count": 12,
    }
    defaults.update(overrides)
    return defaults


def _make_chunk_version_row(**overrides) -> dict:
    """Factory for chunk_versions database row."""
    doc_version_id = overrides.pop("document_version_id", uuid4())
    defaults = {
        "id": uuid4(),
        "document_version_id": doc_version_id,
        "chunk_index": 0,
        "content_hash": "fedcba987654" * 5 + "fedc",  # 64-char SHA-256 hex
        "qdrant_point_id": "q-47-v1",
        "embedding_model": "text-embedding-3-small",
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    return conn


class TestRecordDocumentVersion:
    """record_document_version(conn, document_id, version, source_hash, chunk_count)."""

    @pytest.mark.asyncio
    async def test_record_and_retrieve_document_version(self, mock_conn):
        """Records a document version and returns DocumentVersion model."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        row = _make_doc_version_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        tracker = DataLineageTracker()
        result = await tracker.record_document_version(
            mock_conn,
            document_id="CTR-2024-001",
            version=1,
            source_hash=row["source_hash"],
            chunk_count=12,
        )

        assert isinstance(result, DocumentVersion)
        assert result.document_id == "CTR-2024-001"
        assert result.version == 1
        assert result.chunk_count == 12

    @pytest.mark.asyncio
    async def test_record_document_version_uses_parameterized_sql(self, mock_conn):
        """INSERT uses $1, $2, etc. -- no string interpolation."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        row = _make_doc_version_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        tracker = DataLineageTracker()
        await tracker.record_document_version(
            mock_conn,
            document_id="CTR-2024-001",
            version=1,
            source_hash=row["source_hash"],
            chunk_count=12,
        )

        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO document_versions" in sql_arg
        assert "$1" in sql_arg
        assert "%s" not in sql_arg
        assert "f'" not in sql_arg


class TestRecordChunkVersion:
    """record_chunk_version parameterized SQL, returns ChunkVersion."""

    @pytest.mark.asyncio
    async def test_record_and_retrieve_chunk_version(self, mock_conn):
        """Records a chunk version and returns ChunkVersion model."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        doc_version_id = uuid4()
        row = _make_chunk_version_row(document_version_id=doc_version_id)
        mock_conn.fetchrow = AsyncMock(return_value=row)

        tracker = DataLineageTracker()
        result = await tracker.record_chunk_version(
            mock_conn,
            document_version_id=doc_version_id,
            chunk_index=0,
            content_hash=row["content_hash"],
            qdrant_point_id="q-47-v1",
            embedding_model="text-embedding-3-small",
        )

        assert isinstance(result, ChunkVersion)
        assert result.document_version_id == doc_version_id
        assert result.chunk_index == 0
        assert result.qdrant_point_id == "q-47-v1"
        assert result.embedding_model == "text-embedding-3-small"

    @pytest.mark.asyncio
    async def test_chunk_versions_reference_correct_document_version(self, mock_conn):
        """Chunk version FK points to the correct document version."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        doc_v1_id = uuid4()
        doc_v2_id = uuid4()

        # Record chunk for v1
        row_v1 = _make_chunk_version_row(
            document_version_id=doc_v1_id, chunk_index=0
        )
        mock_conn.fetchrow = AsyncMock(return_value=row_v1)

        tracker = DataLineageTracker()
        chunk_v1 = await tracker.record_chunk_version(
            mock_conn,
            document_version_id=doc_v1_id,
            chunk_index=0,
            content_hash=row_v1["content_hash"],
            qdrant_point_id="q-1-v1",
            embedding_model="text-embedding-3-small",
        )

        # Record chunk for v2
        row_v2 = _make_chunk_version_row(
            document_version_id=doc_v2_id, chunk_index=0
        )
        mock_conn.fetchrow = AsyncMock(return_value=row_v2)

        chunk_v2 = await tracker.record_chunk_version(
            mock_conn,
            document_version_id=doc_v2_id,
            chunk_index=0,
            content_hash=row_v2["content_hash"],
            qdrant_point_id="q-1-v2",
            embedding_model="text-embedding-3-small",
        )

        assert chunk_v1.document_version_id == doc_v1_id
        assert chunk_v2.document_version_id == doc_v2_id
        assert chunk_v1.document_version_id != chunk_v2.document_version_id

    @pytest.mark.asyncio
    async def test_record_chunk_version_uses_parameterized_sql(self, mock_conn):
        """INSERT uses $1, $2, etc. -- no string interpolation."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        doc_version_id = uuid4()
        row = _make_chunk_version_row(document_version_id=doc_version_id)
        mock_conn.fetchrow = AsyncMock(return_value=row)

        tracker = DataLineageTracker()
        await tracker.record_chunk_version(
            mock_conn,
            document_version_id=doc_version_id,
            chunk_index=0,
            content_hash=row["content_hash"],
            qdrant_point_id="q-47-v1",
            embedding_model="text-embedding-3-small",
        )

        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO chunk_versions" in sql_arg
        assert "$1" in sql_arg
        assert "%s" not in sql_arg


class TestGetDocumentVersions:
    """get_document_versions(conn, document_id) -> list[DocumentVersion]."""

    @pytest.mark.asyncio
    async def test_get_document_versions_returns_list(self, mock_conn):
        """Returns all versions for a document_id."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        rows = [
            _make_doc_version_row(version=1),
            _make_doc_version_row(version=2),
            _make_doc_version_row(version=3),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        tracker = DataLineageTracker()
        results = await tracker.get_document_versions(mock_conn, "CTR-2024-001")

        assert len(results) == 3
        assert all(isinstance(r, DocumentVersion) for r in results)
        assert results[0].version == 1
        assert results[1].version == 2
        assert results[2].version == 3

    @pytest.mark.asyncio
    async def test_multiple_document_versions_tracked(self, mock_conn):
        """v1, v2, v3 all tracked with distinct source_hash values."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        hash_v1 = "a" * 64
        hash_v2 = "b" * 64
        hash_v3 = "c" * 64
        rows = [
            _make_doc_version_row(version=1, source_hash=hash_v1),
            _make_doc_version_row(version=2, source_hash=hash_v2),
            _make_doc_version_row(version=3, source_hash=hash_v3),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        tracker = DataLineageTracker()
        results = await tracker.get_document_versions(mock_conn, "CTR-2024-001")

        assert results[0].source_hash == hash_v1
        assert results[1].source_hash == hash_v2
        assert results[2].source_hash == hash_v3


class TestGetChunkVersions:
    """get_chunk_versions(conn, document_version_id) -> list[ChunkVersion]."""

    @pytest.mark.asyncio
    async def test_get_chunk_versions_for_document_version(self, mock_conn):
        """Returns all chunks for a specific document version."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        doc_version_id = uuid4()
        rows = [
            _make_chunk_version_row(document_version_id=doc_version_id, chunk_index=0),
            _make_chunk_version_row(document_version_id=doc_version_id, chunk_index=1),
            _make_chunk_version_row(document_version_id=doc_version_id, chunk_index=2),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        tracker = DataLineageTracker()
        results = await tracker.get_chunk_versions(mock_conn, doc_version_id)

        assert len(results) == 3
        assert all(isinstance(r, ChunkVersion) for r in results)
        assert all(r.document_version_id == doc_version_id for r in results)


class TestGetFullLineage:
    """get_full_lineage(conn, document_id) -> LineageRecord."""

    @pytest.mark.asyncio
    async def test_get_full_lineage_returns_complete_chain(self, mock_conn):
        """Full lineage: doc versions -> chunks -> embedding info."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        doc_version_id = uuid4()
        doc_rows = [
            _make_doc_version_row(id=doc_version_id, version=1, chunk_count=2),
        ]
        chunk_rows = [
            _make_chunk_version_row(
                document_version_id=doc_version_id,
                chunk_index=0,
                qdrant_point_id="q-1",
                embedding_model="text-embedding-3-small",
            ),
            _make_chunk_version_row(
                document_version_id=doc_version_id,
                chunk_index=1,
                qdrant_point_id="q-2",
                embedding_model="text-embedding-3-small",
            ),
        ]

        # First fetch: document versions; second fetch: chunk versions
        mock_conn.fetch = AsyncMock(side_effect=[doc_rows, chunk_rows])

        tracker = DataLineageTracker()
        result = await tracker.get_full_lineage(mock_conn, "CTR-2024-001")

        assert isinstance(result, LineageRecord)
        assert result.document_id == "CTR-2024-001"
        assert len(result.versions) == 1
        assert len(result.chunks) == 2
        assert result.chunks[0].qdrant_point_id == "q-1"
        assert result.chunks[1].qdrant_point_id == "q-2"
        assert result.chunks[0].embedding_model == "text-embedding-3-small"


class TestVerifySourceHash:
    """verify_source_hash(conn, document_id, version, expected_hash) -> bool."""

    @pytest.mark.asyncio
    async def test_verify_source_hash_passes_for_matching_hash(self, mock_conn):
        """Returns True when stored hash matches expected hash."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        stored_hash = "a" * 64
        mock_conn.fetchval = AsyncMock(return_value=stored_hash)

        tracker = DataLineageTracker()
        result = await tracker.verify_source_hash(
            mock_conn, "CTR-2024-001", 1, stored_hash
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_verify_source_hash_fails_for_mismatched_hash(self, mock_conn):
        """Returns False when stored hash does not match -- tamper detection."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        mock_conn.fetchval = AsyncMock(return_value="a" * 64)

        tracker = DataLineageTracker()
        result = await tracker.verify_source_hash(
            mock_conn, "CTR-2024-001", 1, "b" * 64
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_verify_source_hash_false_for_nonexistent_version(self, mock_conn):
        """Returns False when the document version doesn't exist."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        mock_conn.fetchval = AsyncMock(return_value=None)

        tracker = DataLineageTracker()
        result = await tracker.verify_source_hash(
            mock_conn, "MISSING-DOC", 99, "a" * 64
        )

        assert result is False


class TestSQLInjectionProtection:
    """SQL injection in document_id is blocked by parameterized queries."""

    @pytest.mark.asyncio
    async def test_sql_injection_in_document_id_blocked(self, mock_conn):
        """Malicious document_id is passed as a parameter, not interpolated."""
        from apps.api.src.domains.logicore.compliance.data_lineage import (
            DataLineageTracker,
        )

        malicious_id = "'; DROP TABLE document_versions; --"
        mock_conn.fetch = AsyncMock(return_value=[])

        tracker = DataLineageTracker()
        await tracker.get_document_versions(mock_conn, malicious_id)

        sql_arg = mock_conn.fetch.call_args[0][0]
        assert "DROP TABLE" not in sql_arg
        assert "$1" in sql_arg
        # Malicious string passed as parameter, not in SQL
        params = mock_conn.fetch.call_args[0][1:]
        assert malicious_id in params
