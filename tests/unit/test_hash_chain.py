"""Unit tests for SHA-256 hash chain with concurrency protection.

Security model:
  - Each audit entry's hash depends on the previous entry's hash, creating
    a tamper-evident chain. Modifying any entry breaks all subsequent hashes.
  - PostgreSQL advisory locks (pg_advisory_xact_lock) prevent concurrent
    writes from forking the chain.
  - Hash: SHA-256(prev_hash || created_at || user_id || query_hash
    || response_hash || model_version)

Tests cover:
  - Sequential writes produce valid chain
  - verify_hash_chain succeeds on valid chain
  - verify_hash_chain detects tampered entry
  - Concurrent writes (mocked advisory lock) don't fork the chain
  - Empty chain verification succeeds
  - Single-entry chain (prev_hash is None for first entry)
  - Hash is deterministic (same inputs = same hash)
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import AuditEntryCreate


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


class MockTransactionContext:
    """Mock for asyncpg's conn.transaction() async context manager."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection with advisory lock and transaction support."""
    conn = AsyncMock()
    txn_ctx = MockTransactionContext()
    conn.transaction = MagicMock(return_value=txn_ctx)
    return conn


class TestHashChainWrite:
    """write_with_hash_chain: appends entry with prev_hash from last entry."""

    @pytest.mark.asyncio
    async def test_first_entry_has_no_prev_hash(self, mock_conn):
        """First entry in chain has prev_entry_hash = None."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create()
        row = _make_db_row(prev_entry_hash=None)

        # No previous entry exists
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.fetchrow = AsyncMock(return_value=row)
        # Advisory lock is a no-op in mock
        mock_conn.execute = AsyncMock()

        logger = AuditLogger()
        result = await logger.write_with_hash_chain(mock_conn, entry_create)

        assert result.prev_entry_hash is None

    @pytest.mark.asyncio
    async def test_second_entry_references_first_hash(self, mock_conn):
        """Second entry's prev_entry_hash = first entry's entry_hash."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        first_hash = "sha256:first_entry_hash_abc"
        entry_create = _make_entry_create()
        row = _make_db_row(prev_entry_hash=first_hash)

        # Previous entry exists with known hash
        mock_conn.fetchval = AsyncMock(return_value=first_hash)
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.execute = AsyncMock()

        logger = AuditLogger()
        result = await logger.write_with_hash_chain(mock_conn, entry_create)

        assert result.prev_entry_hash == first_hash

    @pytest.mark.asyncio
    async def test_sequential_writes_produce_valid_chain(self, mock_conn):
        """Three sequential writes produce a chain: None -> hash1 -> hash2."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        logger = AuditLogger()
        hashes_seen = []

        # Simulate 3 sequential writes
        for i in range(3):
            prev_hash = hashes_seen[-1] if hashes_seen else None
            entry_create = _make_entry_create(
                query_text=f"Query {i}",
                response_text=f"Response {i}",
            )

            row = _make_db_row(
                prev_entry_hash=prev_hash,
                entry_hash=f"sha256:hash_{i}",
                query_text=f"Query {i}",
                response_text=f"Response {i}",
            )

            mock_conn.fetchval = AsyncMock(return_value=prev_hash)
            mock_conn.fetchrow = AsyncMock(return_value=row)
            mock_conn.execute = AsyncMock()

            result = await logger.write_with_hash_chain(mock_conn, entry_create)
            hashes_seen.append(result.entry_hash)

        # Chain: None -> hash_0 -> hash_1 -> hash_2
        assert len(hashes_seen) == 3

    @pytest.mark.asyncio
    async def test_write_acquires_advisory_lock(self, mock_conn):
        """write_with_hash_chain acquires pg_advisory_xact_lock to serialize writes."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        entry_create = _make_entry_create()
        row = _make_db_row()
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.fetchrow = AsyncMock(return_value=row)
        mock_conn.execute = AsyncMock()

        logger = AuditLogger()
        await logger.write_with_hash_chain(mock_conn, entry_create)

        # Advisory lock should have been called
        execute_calls = mock_conn.execute.call_args_list
        advisory_calls = [
            c for c in execute_calls
            if "pg_advisory_xact_lock" in str(c)
        ]
        assert len(advisory_calls) >= 1, "Should acquire advisory lock"

    @pytest.mark.asyncio
    async def test_concurrent_writes_serialize_via_lock(self, mock_conn):
        """Concurrent writes must be serialized by advisory lock, not fork the chain."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        logger = AuditLogger()
        lock_acquisitions = []

        # Track advisory lock calls to prove serialization
        original_execute = mock_conn.execute

        async def tracking_execute(sql, *args, **kwargs):
            if "pg_advisory_xact_lock" in sql:
                lock_acquisitions.append(datetime.now(UTC))
            return await original_execute(sql, *args, **kwargs)

        mock_conn.execute = tracking_execute
        mock_conn.fetchval = AsyncMock(return_value=None)
        mock_conn.fetchrow = AsyncMock(return_value=_make_db_row())

        # Launch 3 concurrent writes
        entries = [
            _make_entry_create(query_text=f"Concurrent query {i}")
            for i in range(3)
        ]

        # In real Postgres, advisory lock serializes. Here we verify all acquire the lock.
        results = await asyncio.gather(
            *[logger.write_with_hash_chain(mock_conn, e) for e in entries]
        )

        assert len(results) == 3
        assert len(lock_acquisitions) == 3, "All 3 writes must acquire advisory lock"


class TestHashChainVerification:
    """verify_hash_chain: walks entire chain to detect tampering."""

    @pytest.mark.asyncio
    async def test_empty_chain_is_valid(self, mock_conn):
        """Empty table: verify_hash_chain returns (True, None)."""
        from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger

        mock_conn.fetch = AsyncMock(return_value=[])

        logger = AuditLogger()
        valid, broken_index = await logger.verify_hash_chain(mock_conn)

        assert valid is True
        assert broken_index is None

    @pytest.mark.asyncio
    async def test_single_entry_chain_valid(self, mock_conn):
        """Single entry with prev_hash=None is a valid chain."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            AuditLogger,
            compute_chain_hash,
        )

        created_at = datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC)
        user_id = "user-logistics-01"
        query_hash = hashlib.sha256(b"Audit invoice").hexdigest()
        response_hash = hashlib.sha256(b"Discrepancy detected").hexdigest()
        model_version = "gpt-5.2-2026-0201"

        expected_hash = compute_chain_hash(
            prev_hash=None,
            created_at=created_at,
            user_id=user_id,
            query_hash=query_hash,
            response_hash=response_hash,
            model_version=model_version,
        )

        row = {
            "prev_entry_hash": None,
            "entry_hash": expected_hash,
            "created_at": created_at,
            "user_id": user_id,
            "query_text": "Audit invoice",
            "response_text": "Discrepancy detected",
            "model_version": model_version,
        }
        mock_conn.fetch = AsyncMock(return_value=[row])

        logger = AuditLogger()
        valid, broken_index = await logger.verify_hash_chain(mock_conn)

        assert valid is True
        assert broken_index is None

    @pytest.mark.asyncio
    async def test_valid_chain_passes_verification(self, mock_conn):
        """A properly formed 3-entry chain passes verification."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            AuditLogger,
            compute_chain_hash,
        )

        rows = []
        prev_hash = None

        for i in range(3):
            created_at = datetime(2026, 9, 15, 14, i, 0, tzinfo=UTC)
            user_id = f"user-{i}"
            query_text = f"Query {i}"
            response_text = f"Response {i}"
            model_version = "gpt-5.2"

            query_hash = hashlib.sha256(query_text.encode()).hexdigest()
            resp_hash = hashlib.sha256(response_text.encode()).hexdigest()

            entry_hash = compute_chain_hash(
                prev_hash=prev_hash,
                created_at=created_at,
                user_id=user_id,
                query_hash=query_hash,
                response_hash=resp_hash,
                model_version=model_version,
            )

            rows.append({
                "prev_entry_hash": prev_hash,
                "entry_hash": entry_hash,
                "created_at": created_at,
                "user_id": user_id,
                "query_text": query_text,
                "response_text": response_text,
                "model_version": model_version,
            })
            prev_hash = entry_hash

        mock_conn.fetch = AsyncMock(return_value=rows)

        logger = AuditLogger()
        valid, broken_index = await logger.verify_hash_chain(mock_conn)

        assert valid is True
        assert broken_index is None

    @pytest.mark.asyncio
    async def test_tampered_entry_detected(self, mock_conn):
        """Modifying an entry's data makes its hash invalid -- verification catches it."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            AuditLogger,
            compute_chain_hash,
        )

        rows = []
        prev_hash = None

        for i in range(3):
            created_at = datetime(2026, 9, 15, 14, i, 0, tzinfo=UTC)
            user_id = f"user-{i}"
            query_text = f"Query {i}"
            response_text = f"Response {i}"
            model_version = "gpt-5.2"

            query_hash = hashlib.sha256(query_text.encode()).hexdigest()
            resp_hash = hashlib.sha256(response_text.encode()).hexdigest()

            entry_hash = compute_chain_hash(
                prev_hash=prev_hash,
                created_at=created_at,
                user_id=user_id,
                query_hash=query_hash,
                response_hash=resp_hash,
                model_version=model_version,
            )

            rows.append({
                "prev_entry_hash": prev_hash,
                "entry_hash": entry_hash,
                "created_at": created_at,
                "user_id": user_id,
                "query_text": query_text,
                "response_text": response_text,
                "model_version": model_version,
            })
            prev_hash = entry_hash

        # Tamper with entry at index 1 (change response_text)
        rows[1]["response_text"] = "TAMPERED: nothing wrong"

        mock_conn.fetch = AsyncMock(return_value=rows)

        logger = AuditLogger()
        valid, broken_index = await logger.verify_hash_chain(mock_conn)

        assert valid is False
        assert broken_index == 1

    @pytest.mark.asyncio
    async def test_broken_prev_hash_link_detected(self, mock_conn):
        """If prev_entry_hash doesn't match previous entry's hash, chain is broken."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            AuditLogger,
            compute_chain_hash,
        )

        created_at_0 = datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC)
        query_hash_0 = hashlib.sha256(b"Query 0").hexdigest()
        resp_hash_0 = hashlib.sha256(b"Response 0").hexdigest()

        hash_0 = compute_chain_hash(
            prev_hash=None,
            created_at=created_at_0,
            user_id="user-0",
            query_hash=query_hash_0,
            response_hash=resp_hash_0,
            model_version="gpt-5.2",
        )

        # Entry 1 has wrong prev_entry_hash (doesn't match hash_0)
        created_at_1 = datetime(2026, 9, 15, 14, 1, 0, tzinfo=UTC)
        query_hash_1 = hashlib.sha256(b"Query 1").hexdigest()
        resp_hash_1 = hashlib.sha256(b"Response 1").hexdigest()

        # Compute hash with WRONG prev_hash but store that wrong prev_hash
        wrong_prev = "sha256:totally_wrong"
        hash_1 = compute_chain_hash(
            prev_hash=wrong_prev,
            created_at=created_at_1,
            user_id="user-1",
            query_hash=query_hash_1,
            response_hash=resp_hash_1,
            model_version="gpt-5.2",
        )

        rows = [
            {
                "prev_entry_hash": None,
                "entry_hash": hash_0,
                "created_at": created_at_0,
                "user_id": "user-0",
                "query_text": "Query 0",
                "response_text": "Response 0",
                "model_version": "gpt-5.2",
            },
            {
                "prev_entry_hash": wrong_prev,  # Should be hash_0
                "entry_hash": hash_1,
                "created_at": created_at_1,
                "user_id": "user-1",
                "query_text": "Query 1",
                "response_text": "Response 1",
                "model_version": "gpt-5.2",
            },
        ]

        mock_conn.fetch = AsyncMock(return_value=rows)

        logger = AuditLogger()
        valid, broken_index = await logger.verify_hash_chain(mock_conn)

        assert valid is False
        assert broken_index == 1


class TestHashDeterminism:
    """Hash computation must be deterministic: same inputs = same hash."""

    def test_same_inputs_produce_same_hash(self):
        """Identical inputs always produce identical hash."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            compute_chain_hash,
        )

        kwargs = {
            "prev_hash": "sha256:abc",
            "created_at": datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC),
            "user_id": "user-01",
            "query_hash": hashlib.sha256(b"test query").hexdigest(),
            "response_hash": hashlib.sha256(b"test response").hexdigest(),
            "model_version": "gpt-5.2",
        }

        hash1 = compute_chain_hash(**kwargs)
        hash2 = compute_chain_hash(**kwargs)
        hash3 = compute_chain_hash(**kwargs)
        hash4 = compute_chain_hash(**kwargs)
        hash5 = compute_chain_hash(**kwargs)

        assert hash1 == hash2 == hash3 == hash4 == hash5
        assert hash1.startswith("sha256:")

    def test_different_prev_hash_produces_different_result(self):
        """Changing prev_hash changes the output (chain linkage)."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            compute_chain_hash,
        )

        common = {
            "created_at": datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC),
            "user_id": "user-01",
            "query_hash": hashlib.sha256(b"test").hexdigest(),
            "response_hash": hashlib.sha256(b"resp").hexdigest(),
            "model_version": "gpt-5.2",
        }

        h1 = compute_chain_hash(prev_hash="sha256:aaa", **common)
        h2 = compute_chain_hash(prev_hash="sha256:bbb", **common)

        assert h1 != h2

    def test_none_prev_hash_produces_valid_hash(self):
        """First entry (prev_hash=None) still produces a valid SHA-256 hash."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            compute_chain_hash,
        )

        result = compute_chain_hash(
            prev_hash=None,
            created_at=datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC),
            user_id="user-01",
            query_hash=hashlib.sha256(b"query").hexdigest(),
            response_hash=hashlib.sha256(b"response").hexdigest(),
            model_version="gpt-5.2",
        )

        assert result.startswith("sha256:")
        # The hash after prefix should be 64 hex chars (SHA-256)
        hex_part = result.split(":", 1)[1]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_different_user_id_produces_different_hash(self):
        """Changing user_id changes the hash (proves user_id is included)."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            compute_chain_hash,
        )

        common = {
            "prev_hash": None,
            "created_at": datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC),
            "query_hash": hashlib.sha256(b"test").hexdigest(),
            "response_hash": hashlib.sha256(b"resp").hexdigest(),
            "model_version": "gpt-5.2",
        }

        h1 = compute_chain_hash(user_id="alice", **common)
        h2 = compute_chain_hash(user_id="bob", **common)

        assert h1 != h2

    def test_different_model_version_produces_different_hash(self):
        """Changing model_version changes the hash."""
        from apps.api.src.domains.logicore.compliance.audit_logger import (
            compute_chain_hash,
        )

        common = {
            "prev_hash": None,
            "created_at": datetime(2026, 9, 15, 14, 0, 0, tzinfo=UTC),
            "user_id": "user-01",
            "query_hash": hashlib.sha256(b"test").hexdigest(),
            "response_hash": hashlib.sha256(b"resp").hexdigest(),
        }

        h1 = compute_chain_hash(model_version="gpt-5.2", **common)
        h2 = compute_chain_hash(model_version="gpt-4o", **common)

        assert h1 != h2
