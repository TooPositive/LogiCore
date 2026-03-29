"""EU AI Act Article 12 compliance report generator.

Generates compliance reports for a date range by querying the audit_log
table. Reports include:
  - Total entries and entries by log level
  - Distinct models used and unique users
  - HITL approval count and total cost
  - Degraded decision count (Phase 7 integration)
  - Hash chain integrity verification
  - Entry count hash for completeness verification

Security model:
  1. Parameterized queries only ($1, $2, ...) -- no string interpolation
  2. Entry count hash proves no entries were silently excluded
  3. Hash chain verification proves no entries were tampered with
"""

import hashlib
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from apps.api.src.domains.logicore.compliance.audit_logger import (
    AuditLogger,
    _row_to_audit_entry,
)
from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    ComplianceReport,
)

# --- SQL (parameterized) ---

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

_SELECT_DEGRADED_SQL = """
SELECT
    id, created_at,
    user_id, query_text, retrieved_chunk_ids,
    model_version, model_deployment, response_text,
    hitl_approver_id, langfuse_trace_id, metadata, log_level,
    prev_entry_hash, entry_hash,
    prompt_tokens, completion_tokens, total_cost_eur, response_hash,
    is_degraded, provider_name, quality_drift_alert
FROM audit_log
WHERE created_at >= $1 AND created_at <= $2 AND is_degraded = TRUE
ORDER BY created_at ASC
"""

_COUNT_BY_RANGE_SQL = """
SELECT COUNT(*) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
"""

_COUNT_DEGRADED_SQL = """
SELECT COUNT(*) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2 AND is_degraded = TRUE
"""

_COUNT_DISTINCT_MODELS_SQL = """
SELECT COUNT(DISTINCT model_version) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
"""

_COUNT_DISTINCT_USERS_SQL = """
SELECT COUNT(DISTINCT user_id) FROM audit_log
WHERE created_at >= $1 AND created_at <= $2
"""


class ComplianceReportGenerator:
    """Generate EU AI Act Article 12 compliance reports.

    All methods accept an asyncpg connection (not pool) for
    transaction sharing with other compliance operations.
    """

    async def generate(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
        include_pii: bool = False,
    ) -> ComplianceReport:
        """Generate a full compliance report for a date range.

        Queries audit_log, aggregates statistics, verifies hash chain,
        and produces a ComplianceReport with entry_count_hash for
        completeness verification.

        Args:
            conn: asyncpg connection
            period_start: start of reporting period (inclusive)
            period_end: end of reporting period (inclusive)
            include_pii: whether to include PII data (default False)

        Returns:
            ComplianceReport with all aggregated data and verification hashes.
        """
        # Fetch all entries in the period
        rows = await conn.fetch(_SELECT_BY_DATE_RANGE_SQL, period_start, period_end)

        # Aggregate statistics
        total_entries = len(rows)
        user_ids: set[str] = set()
        model_versions: set[str] = set()
        level_counts: Counter[str] = Counter()
        hitl_count = 0
        total_cost = Decimal("0")
        degraded_count = 0

        for row in rows:
            user_ids.add(row["user_id"])
            model_versions.add(row["model_version"])
            level_counts[row["log_level"]] += 1
            if row["hitl_approver_id"] is not None:
                hitl_count += 1
            if row["total_cost_eur"] is not None:
                total_cost += Decimal(str(row["total_cost_eur"]))
            if row["is_degraded"]:
                degraded_count += 1

        # Hash chain verification
        audit_logger = AuditLogger()
        chain_valid, chain_broken_at = await audit_logger.verify_hash_chain(conn)

        # Entry count hash for completeness verification
        count_content = (
            f"{total_entries}:{period_start.isoformat()}:{period_end.isoformat()}"
        )
        entry_count_hash = (
            f"sha256:{hashlib.sha256(count_content.encode()).hexdigest()}"
        )

        return ComplianceReport(
            report_id=uuid4(),
            generated_at=datetime.now(UTC),
            period_start=period_start,
            period_end=period_end,
            total_entries=total_entries,
            entries_by_level=dict(level_counts),
            models_used=sorted(model_versions),
            unique_users=len(user_ids),
            hitl_approval_count=hitl_count,
            total_cost_eur=total_cost,
            generated_by="compliance-report-generator",
            metadata={
                "degraded_count": degraded_count,
                "hash_chain_valid": chain_valid,
                "hash_chain_broken_at": chain_broken_at,
                "entry_count_hash": entry_count_hash,
            },
        )

    async def generate_summary_stats(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        """Generate quick summary stats without fetching full entries.

        Uses aggregate SQL queries for performance on large audit logs.

        Args:
            conn: asyncpg connection
            period_start: start of reporting period
            period_end: end of reporting period

        Returns:
            Dict with total_entries, degraded_count, distinct_models, distinct_users.
        """
        total = await conn.fetchval(_COUNT_BY_RANGE_SQL, period_start, period_end)
        degraded = await conn.fetchval(_COUNT_DEGRADED_SQL, period_start, period_end)
        models = await conn.fetchval(
            _COUNT_DISTINCT_MODELS_SQL, period_start, period_end
        )
        users = await conn.fetchval(
            _COUNT_DISTINCT_USERS_SQL, period_start, period_end
        )

        return {
            "total_entries": total,
            "degraded_count": degraded,
            "distinct_models": models,
            "distinct_users": users,
        }

    async def get_degraded_decisions(
        self,
        conn,
        period_start: datetime,
        period_end: datetime,
    ) -> list[AuditEntry]:
        """Get all degraded-mode decisions in a period.

        Specifically for regulator focus: which decisions were made
        using fallback/degraded inference (Phase 7 integration).

        Args:
            conn: asyncpg connection
            period_start: start of period
            period_end: end of period

        Returns:
            List of AuditEntry where is_degraded=True.
        """
        rows = await conn.fetch(_SELECT_DEGRADED_SQL, period_start, period_end)
        return [_row_to_audit_entry(row) for row in rows]
