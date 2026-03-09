"""Unit tests for atomic audit write pattern.

The critical requirement: LangGraph checkpoint save + audit log write
MUST happen in the same database transaction. A crash between separate
writes creates a compliance gap (workflow resumes but audit entry missing).

Cost of gap: EUR 100,000-3,500,000 (EU AI Act fine: up to 7% global turnover).

Tests cover:
- Both operations succeed in same transaction
- If audit write fails, both roll back (nothing persisted)
- If checkpoint fails, audit entry also rolls back
- Transaction context manager pattern works correctly
- Helper accepts connection and writes both atomically
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntryCreate,
)


def _make_entry_create(**overrides) -> AuditEntryCreate:
    """Factory for AuditEntryCreate with sensible defaults."""
    defaults = {
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
    }
    defaults.update(overrides)
    return AuditEntryCreate(**defaults)


def _make_db_row(**overrides) -> dict:
    """Factory for database row dict."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
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


class MockTransactionContext:
    """Mock for asyncpg's conn.transaction() async context manager."""

    def __init__(self, should_fail_on_exit: bool = False):
        self._should_fail_on_exit = should_fail_on_exit
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rolled_back = True
        else:
            self.committed = True
        return False  # Don't suppress exceptions


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection with transaction support."""
    conn = AsyncMock()
    txn_ctx = MockTransactionContext()
    conn.transaction = MagicMock(return_value=txn_ctx)
    conn._txn_ctx = txn_ctx  # Expose for assertions
    return conn


class TestAtomicAuditWrite:
    """atomic_audit_write: checkpoint + audit in same transaction."""

    @pytest.mark.asyncio
    async def test_both_succeed_in_same_transaction(self, mock_conn):
        """When both checkpoint and audit succeed, both are committed."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        checkpoint_fn = AsyncMock()  # Simulates checkpointer.save(state, conn)

        result = await atomic_audit_write(
            conn=mock_conn,
            checkpoint_fn=checkpoint_fn,
            audit_entry=entry_create,
        )

        # Both functions were called
        checkpoint_fn.assert_called_once()
        # Transaction was opened
        mock_conn.transaction.assert_called_once()
        # Result is an AuditEntry
        assert result.user_id == "user-logistics-01"
        # Transaction committed (no exception)
        assert mock_conn._txn_ctx.committed is True

    @pytest.mark.asyncio
    async def test_audit_write_fails_rolls_back_both(self, mock_conn):
        """If audit write fails, the transaction rolls back (checkpoint also undone)."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        # Audit write will fail
        mock_conn.fetchrow = AsyncMock(side_effect=RuntimeError("DB write failed"))

        checkpoint_fn = AsyncMock()

        with pytest.raises(RuntimeError, match="DB write failed"):
            await atomic_audit_write(
                conn=mock_conn,
                checkpoint_fn=checkpoint_fn,
                audit_entry=entry_create,
            )

        # Transaction rolled back
        assert mock_conn._txn_ctx.rolled_back is True
        assert mock_conn._txn_ctx.committed is False

    @pytest.mark.asyncio
    async def test_checkpoint_fails_rolls_back_both(self, mock_conn):
        """If checkpoint fails, audit entry also rolls back."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        # Checkpoint will fail
        checkpoint_fn = AsyncMock(side_effect=RuntimeError("Checkpoint failed"))

        with pytest.raises(RuntimeError, match="Checkpoint failed"):
            await atomic_audit_write(
                conn=mock_conn,
                checkpoint_fn=checkpoint_fn,
                audit_entry=entry_create,
            )

        # Transaction rolled back
        assert mock_conn._txn_ctx.rolled_back is True
        assert mock_conn._txn_ctx.committed is False

    @pytest.mark.asyncio
    async def test_checkpoint_called_before_audit_write(self, mock_conn):
        """Checkpoint runs first, then audit write. Order matters for rollback logic."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        call_order = []
        async def checkpoint_fn(conn):
            call_order.append("checkpoint")

        original_fetchrow = mock_conn.fetchrow
        async def tracked_fetchrow(*args, **kwargs):
            call_order.append("audit_write")
            return await original_fetchrow(*args, **kwargs)
        mock_conn.fetchrow = tracked_fetchrow

        await atomic_audit_write(
            conn=mock_conn,
            checkpoint_fn=checkpoint_fn,
            audit_entry=entry_create,
        )

        assert call_order[0] == "checkpoint"
        assert "audit_write" in call_order

    @pytest.mark.asyncio
    async def test_connection_passed_to_checkpoint_fn(self, mock_conn):
        """The same connection is passed to the checkpoint function."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)

        received_conn = None
        async def checkpoint_fn(conn):
            nonlocal received_conn
            received_conn = conn

        await atomic_audit_write(
            conn=mock_conn,
            checkpoint_fn=checkpoint_fn,
            audit_entry=entry_create,
        )

        assert received_conn is mock_conn

    @pytest.mark.asyncio
    async def test_returns_audit_entry_on_success(self, mock_conn):
        """On success, returns the AuditEntry from the write."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            atomic_audit_write,
        )

        entry_id = uuid4()
        entry_create = _make_entry_create()
        row = _make_db_row(id=entry_id)
        mock_conn.fetchrow = AsyncMock(return_value=row)
        checkpoint_fn = AsyncMock()

        result = await atomic_audit_write(
            conn=mock_conn,
            checkpoint_fn=checkpoint_fn,
            audit_entry=entry_create,
        )

        assert result.id == entry_id

    @pytest.mark.asyncio
    async def test_audit_logger_instance_used_internally(self, mock_conn):
        """atomic_audit_write uses AuditLogger internally (not raw SQL)."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            AuditLogger,
            atomic_audit_write,
        )

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchrow = AsyncMock(return_value=row)
        checkpoint_fn = AsyncMock()

        with patch.object(AuditLogger, "write", new_callable=AsyncMock) as mock_write:
            mock_write.return_value = MagicMock()
            await atomic_audit_write(
                conn=mock_conn,
                checkpoint_fn=checkpoint_fn,
                audit_entry=entry_create,
            )
            mock_write.assert_called_once_with(mock_conn, entry_create)
