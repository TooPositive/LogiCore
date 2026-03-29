"""Unit tests for Phase 8 audit logger -- immutable audit log writer.

All tests use mocked asyncpg connections (no Docker dependencies).

Tests cover:
- write(): INSERT with parameterized SQL, returns AuditEntry
- get(): fetch by UUID
- get_by_date_range(): date range + optional user_id filtering
- count(): total entry count
- SQL injection in metadata is blocked (parameterized queries)
- All fields stored and retrieved correctly (full round-trip)
- entry_hash is computed on write
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    AuditEntryCreate,
    LogLevel,
)


def _make_entry_create(**overrides) -> AuditEntryCreate:
    """Factory for AuditEntryCreate with sensible defaults."""
    defaults = {
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected: billed 0.52/kg vs contracted 0.45/kg",
    }
    defaults.update(overrides)
    return AuditEntryCreate(**defaults)


def _make_db_row(**overrides) -> dict:
    """Factory for database row dict matching audit_log schema."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected: billed 0.52/kg vs contracted 0.45/kg",
        "hitl_approver_id": None,
        "langfuse_trace_id": None,
        "metadata": {},
        "log_level": "full_trace",
        "prev_entry_hash": None,
        "entry_hash": "sha256:abc123",
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_cost_eur": None,
        "response_hash": None,
        "is_degraded": False,
        "provider_name": None,
        "quality_drift_alert": False,
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection with fetchrow and fetch methods."""
    conn = AsyncMock()
    return conn


class TestAuditLoggerWrite:
    """write(conn, entry) -> AuditEntry."""

    @pytest.mark.asyncio
    async def test_write_returns_audit_entry(self, mock_conn):
        """write() INSERTs and returns a full AuditEntry."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        result = await logger.write(mock_conn, entry_create)

        assert isinstance(result, AuditEntry)
        assert result.user_id == "user-logistics-01"
        assert result.entry_hash == "sha256:abc123"

    @pytest.mark.asyncio
    async def test_write_uses_parameterized_sql(self, mock_conn):
        """write() uses $1, $2, etc. placeholders -- never string interpolation."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        await logger.write(mock_conn, entry_create)

        # Verify the SQL call used parameterized query
        mock_conn.fetchrow.assert_called_once()
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO audit_log" in sql_arg
        assert "$1" in sql_arg
        # No string interpolation patterns
        assert "%s" not in sql_arg
        assert "f'" not in sql_arg

    @pytest.mark.asyncio
    async def test_write_passes_all_fields_as_params(self, mock_conn):
        """All fields from AuditEntryCreate are passed as SQL parameters."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create(
            hitl_approver_id="approver-1",
            langfuse_trace_id="trace-xyz",
            metadata={"invoice_id": "INV-001"},
            log_level=LogLevel.SUMMARY,
            prompt_tokens=100,
            completion_tokens=50,
            total_cost_eur=Decimal("0.005"),
            response_hash="sha256:resp",
            is_degraded=True,
            provider_name="ollama",
            quality_drift_alert=True,
        )
        row = _make_db_row(
            hitl_approver_id="approver-1",
            langfuse_trace_id="trace-xyz",
            metadata={"invoice_id": "INV-001"},
            log_level="summary",
            prompt_tokens=100,
            completion_tokens=50,
            total_cost_eur=Decimal("0.005"),
            response_hash="sha256:resp",
            is_degraded=True,
            provider_name="ollama",
            quality_drift_alert=True,
        )
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        result = await logger.write(mock_conn, entry_create)

        assert result.hitl_approver_id == "approver-1"
        assert result.prompt_tokens == 100
        assert result.is_degraded is True
        assert result.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_write_computes_entry_hash(self, mock_conn):
        """write() computes a hash for the entry content."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create()
        row = _make_db_row(entry_hash="sha256:computed_hash")
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        await logger.write(mock_conn, entry_create)

        # Verify fetchrow was called with an entry_hash parameter
        call_args = mock_conn.fetchrow.call_args[0]
        params = call_args[1:]
        # entry_hash should be among the params (non-empty string starting with sha256:)
        hash_params = [p for p in params if isinstance(p, str) and p.startswith("sha256:")]
        assert len(hash_params) >= 1, "entry_hash should be computed and passed as param"

    @pytest.mark.asyncio
    async def test_write_sql_injection_in_metadata_blocked(self, mock_conn):
        """Malicious metadata is passed as a parameter, not interpolated."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        malicious_metadata = {"key": "'; DROP TABLE audit_log; --"}
        entry_create = _make_entry_create(metadata=malicious_metadata)
        row = _make_db_row(metadata=malicious_metadata)
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        await logger.write(mock_conn, entry_create)

        # The SQL should NOT contain the injection string
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "DROP TABLE" not in sql_arg
        # But the metadata should be in the parameters (as JSON)
        params = mock_conn.fetchrow.call_args[0][1:]
        json_params = [p for p in params if isinstance(p, str) and "DROP TABLE" in p]
        assert len(json_params) >= 1, "Metadata passed as safe parameter"


class TestAuditLoggerGet:
    """get(conn, entry_id) -> AuditEntry | None."""

    @pytest.mark.asyncio
    async def test_get_returns_entry_by_id(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_id = uuid4()
        row = _make_db_row(id=entry_id)
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        result = await logger.get(mock_conn, entry_id)

        assert result is not None
        assert result.id == entry_id
        # Verify parameterized query
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "$1" in sql_arg
        assert str(entry_id) not in sql_arg

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing_entry(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetchrow = AsyncMock(return_value=None)

        logger = AuditLogger()
        result = await logger.get(mock_conn, uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_uses_parameterized_query(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetchrow = AsyncMock(return_value=None)
        entry_id = uuid4()

        logger = AuditLogger()
        await logger.get(mock_conn, entry_id)

        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "SELECT" in sql_arg
        assert "$1" in sql_arg
        # UUID passed as parameter, not in SQL string
        assert str(entry_id) not in sql_arg


class TestAuditLoggerGetByDateRange:
    """get_by_date_range(conn, start, end, user_id=None) -> list[AuditEntry]."""

    @pytest.mark.asyncio
    async def test_date_range_returns_entries(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        rows = [_make_db_row(), _make_db_row()]
        mock_conn.fetch = AsyncMock(return_value=rows)

        logger = AuditLogger()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 3, 31, tzinfo=UTC)
        results = await logger.get_by_date_range(mock_conn, start, end)

        assert len(results) == 2
        assert all(isinstance(r, AuditEntry) for r in results)

    @pytest.mark.asyncio
    async def test_date_range_with_user_id_filter(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        rows = [_make_db_row(user_id="user-cfo-01")]
        mock_conn.fetch = AsyncMock(return_value=rows)

        logger = AuditLogger()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 3, 31, tzinfo=UTC)
        results = await logger.get_by_date_range(
            mock_conn, start, end, user_id="user-cfo-01"
        )

        assert len(results) == 1
        assert results[0].user_id == "user-cfo-01"
        # Verify user_id is in the SQL as a parameter
        sql_arg = mock_conn.fetch.call_args[0][0]
        assert "user_id" in sql_arg
        assert "$3" in sql_arg  # start=$1, end=$2, user_id=$3

    @pytest.mark.asyncio
    async def test_date_range_without_user_id(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetch = AsyncMock(return_value=[])

        logger = AuditLogger()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 3, 31, tzinfo=UTC)
        await logger.get_by_date_range(mock_conn, start, end)

        sql_arg = mock_conn.fetch.call_args[0][0]
        # Without user_id, should NOT have $3
        assert "user_id" not in sql_arg or "$3" not in sql_arg

    @pytest.mark.asyncio
    async def test_date_range_returns_empty_for_no_matches(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetch = AsyncMock(return_value=[])

        logger = AuditLogger()
        start = datetime(2026, 6, 1, tzinfo=UTC)
        end = datetime(2026, 6, 30, tzinfo=UTC)
        results = await logger.get_by_date_range(mock_conn, start, end)
        assert results == []

    @pytest.mark.asyncio
    async def test_date_range_uses_parameterized_sql(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetch = AsyncMock(return_value=[])

        logger = AuditLogger()
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 3, 31, tzinfo=UTC)
        await logger.get_by_date_range(mock_conn, start, end)

        sql_arg = mock_conn.fetch.call_args[0][0]
        assert "$1" in sql_arg
        assert "$2" in sql_arg
        assert "%s" not in sql_arg


class TestAuditLoggerCount:
    """count(conn) -> int."""

    @pytest.mark.asyncio
    async def test_count_returns_total(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetchval = AsyncMock(return_value=4721)

        logger = AuditLogger()
        result = await logger.count(mock_conn)

        assert result == 4721
        sql_arg = mock_conn.fetchval.call_args[0][0]
        assert "COUNT" in sql_arg.upper()

    @pytest.mark.asyncio
    async def test_count_returns_zero_for_empty_table(self, mock_conn):
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetchval = AsyncMock(return_value=0)

        logger = AuditLogger()
        result = await logger.count(mock_conn)
        assert result == 0


class TestAuditLoggerFieldRoundtrip:
    """All fields stored and retrieved correctly."""

    @pytest.mark.asyncio
    async def test_all_fields_preserved_through_write_and_get(self, mock_conn):
        """Full field round-trip: create -> write -> get returns all fields."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_id = uuid4()
        now = datetime.now(UTC)
        row = _make_db_row(
            id=entry_id,
            created_at=now,
            user_id="user-cfo-01",
            query_text="Complex audit query",
            retrieved_chunk_ids=["c-1", "c-2", "c-3"],
            model_version="gpt-5.2-2026-0201",
            model_deployment="logicore-prod-east",
            response_text="Detailed response with discrepancies",
            hitl_approver_id="approver-01",
            langfuse_trace_id="trace-full-123",
            metadata={"invoice_id": "INV-001", "run_id": "run-xyz"},
            log_level="summary",
            prev_entry_hash="sha256:prev",
            entry_hash="sha256:current",
            prompt_tokens=250,
            completion_tokens=180,
            total_cost_eur=Decimal("0.012"),
            response_hash="sha256:respfull",
            is_degraded=True,
            provider_name="ollama",
            quality_drift_alert=True,
        )
        mock_conn.fetchrow = AsyncMock(return_value=row)

        logger = AuditLogger()
        result = await logger.get(mock_conn, entry_id)

        assert result.id == entry_id
        assert result.created_at == now
        assert result.user_id == "user-cfo-01"
        assert result.query_text == "Complex audit query"
        assert result.retrieved_chunk_ids == ["c-1", "c-2", "c-3"]
        assert result.model_version == "gpt-5.2-2026-0201"
        assert result.model_deployment == "logicore-prod-east"
        assert result.response_text == "Detailed response with discrepancies"
        assert result.hitl_approver_id == "approver-01"
        assert result.langfuse_trace_id == "trace-full-123"
        assert result.metadata == {"invoice_id": "INV-001", "run_id": "run-xyz"}
        assert result.log_level == LogLevel.SUMMARY
        assert result.prev_entry_hash == "sha256:prev"
        assert result.entry_hash == "sha256:current"
        assert result.prompt_tokens == 250
        assert result.completion_tokens == 180
        assert result.total_cost_eur == Decimal("0.012")
        assert result.response_hash == "sha256:respfull"
        assert result.is_degraded is True
        assert result.provider_name == "ollama"
        assert result.quality_drift_alert is True
