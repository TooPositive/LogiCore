"""Immutable audit log writer for EU AI Act Article 12 compliance.

Security model:
  1. Parameterized queries only ($1, $2, ...) -- no string interpolation
  2. Database-level immutability: REVOKE UPDATE/DELETE on audit_log
  3. Hash chain: each entry stores prev_entry_hash + entry_hash
  4. All writes return the full AuditEntry for immediate verification

The audit logger accepts an asyncpg connection (not a pool) so that
callers can share a transaction with the LangGraph checkpointer.
This is the atomic audit write pattern from the phase spec:

    async with pool.acquire() as conn:
        async with conn.transaction():
            await checkpointer.save(state, conn=conn)
            await audit_logger.write(conn, entry)
            # Both succeed or both roll back
"""

import hashlib
import json
from datetime import datetime
from uuid import UUID

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    AuditEntryCreate,
)


def _compute_entry_hash(entry: AuditEntryCreate) -> str:
    """Compute SHA-256 hash of the entry content for tamper evidence.

    Hash covers all content fields -- identity fields (id, created_at)
    are excluded since they're server-generated.
    """
    content = (
        f"{entry.user_id}|{entry.query_text}|"
        f"{json.dumps(entry.retrieved_chunk_ids, sort_keys=True)}|"
        f"{entry.model_version}|{entry.model_deployment}|"
        f"{entry.response_text}|{entry.log_level.value}"
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _row_to_audit_entry(row: dict) -> AuditEntry:
    """Convert an asyncpg Record (or dict) to an AuditEntry model.

    Handles type coercion for JSONB fields (asyncpg returns Python objects).
    """
    return AuditEntry(
        id=row["id"],
        created_at=row["created_at"],
        user_id=row["user_id"],
        query_text=row["query_text"],
        retrieved_chunk_ids=row["retrieved_chunk_ids"],
        model_version=row["model_version"],
        model_deployment=row["model_deployment"],
        response_text=row["response_text"],
        hitl_approver_id=row["hitl_approver_id"],
        langfuse_trace_id=row["langfuse_trace_id"],
        metadata=row["metadata"],
        log_level=row["log_level"],
        prev_entry_hash=row["prev_entry_hash"],
        entry_hash=row["entry_hash"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        total_cost_eur=row["total_cost_eur"],
        response_hash=row["response_hash"],
        is_degraded=row["is_degraded"],
        provider_name=row["provider_name"],
        quality_drift_alert=row["quality_drift_alert"],
    )


_INSERT_SQL = """
INSERT INTO audit_log (
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
) VALUES (
    $1, $2, $3::jsonb,
    $4, $5, $6,
    $7, $8, $9::jsonb, $10,
    $11, $12,
    $13, $14, $15, $16,
    $17, $18, $19
) RETURNING
    id, created_at,
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
"""

_SELECT_BY_ID_SQL = """
SELECT
    id, created_at,
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
FROM audit_log
WHERE id = $1
"""

_SELECT_BY_DATE_RANGE_SQL = """
SELECT
    id, created_at,
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
ORDER BY created_at ASC
"""

_SELECT_BY_DATE_RANGE_AND_USER_SQL = """
SELECT
    id, created_at,
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2 AND user_id = $3
ORDER BY created_at ASC
"""

_COUNT_SQL = "SELECT COUNT(*) FROM audit_log"


class AuditLogger:
    """Immutable audit log writer for EU AI Act Article 12 compliance.

    All methods accept an asyncpg connection (not pool) so callers
    can wrap writes in the same transaction as LangGraph checkpoints.
    """

    async def write(self, conn, entry: AuditEntryCreate) -> AuditEntry:
        """Write an audit entry. Returns the full entry with server-side fields.

        Computes entry_hash for tamper evidence. All fields are passed
        as parameterized query arguments -- no string interpolation.
        """
        entry_hash = _compute_entry_hash(entry)
        metadata_json = json.dumps(entry.metadata)
        chunk_ids_json = json.dumps(entry.retrieved_chunk_ids)

        row = await conn.fetchrow(
            _INSERT_SQL,
            entry.user_id,                    # $1
            entry.query_text,                 # $2
            chunk_ids_json,                   # $3
            entry.model_version,              # $4
            entry.model_deployment,           # $5
            entry.response_text,              # $6
            entry.hitl_approver_id,           # $7
            entry.langfuse_trace_id,          # $8
            metadata_json,                    # $9
            entry.log_level.value,            # $10
            entry.prev_entry_hash,            # $11
            entry_hash,                       # $12
            entry.prompt_tokens,              # $13
            entry.completion_tokens,          # $14
            entry.total_cost_eur,             # $15
            entry.response_hash,              # $16
            entry.is_degraded,                # $17
            entry.provider_name,              # $18
            entry.quality_drift_alert,        # $19
        )

        return _row_to_audit_entry(row)

    async def get(self, conn, entry_id: UUID) -> AuditEntry | None:
        """Fetch a single audit entry by ID. Returns None if not found."""
        row = await conn.fetchrow(_SELECT_BY_ID_SQL, entry_id)
        if row is None:
            return None
        return _row_to_audit_entry(row)

    async def get_by_date_range(
        self,
        conn,
        start: datetime,
        end: datetime,
        user_id: str | None = None,
    ) -> list[AuditEntry]:
        """Fetch audit entries within a date range, optionally filtered by user."""
        if user_id is not None:
            rows = await conn.fetch(
                _SELECT_BY_DATE_RANGE_AND_USER_SQL, start, end, user_id
            )
        else:
            rows = await conn.fetch(_SELECT_BY_DATE_RANGE_SQL, start, end)
        return [_row_to_audit_entry(row) for row in rows]

    async def count(self, conn) -> int:
        """Count total audit log entries."""
        return await conn.fetchval(_COUNT_SQL)
