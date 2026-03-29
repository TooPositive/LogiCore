"""Compliance API endpoints for EU AI Act Article 12.

GET  /api/v1/compliance/audit-log         -- audit entries with RBAC filtering
GET  /api/v1/compliance/report            -- compliance report (officer+admin only)
GET  /api/v1/compliance/lineage/{doc_id}  -- full data lineage for a document
GET  /api/v1/compliance/hash-chain/verify -- hash chain integrity status
POST /api/v1/compliance/bias-report       -- fairness report (officer+admin only)

All endpoints:
  - Accept viewer_role for RBAC (production: extract from JWT)
  - Use parameterized SQL via the compliance module
  - Are rate-limit-ready (no enforcement here; reverse proxy handles it)
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from apps.api.src.domains.logicore.compliance.audit_logger import AuditLogger
from apps.api.src.domains.logicore.compliance.audit_rbac import AuditRBAC
from apps.api.src.domains.logicore.compliance.bias_detector import BiasDetector
from apps.api.src.domains.logicore.compliance.data_lineage import (
    DataLineageTracker,
)
from apps.api.src.domains.logicore.compliance.report_generator import (
    ComplianceReportGenerator,
)

# Roles allowed to access compliance reports and bias reports
_PRIVILEGED_ROLES = frozenset({"compliance_officer", "admin"})


def create_compliance_router(db_pool: Any) -> APIRouter:
    """Factory to create compliance router with injected DB pool.

    Args:
        db_pool: asyncpg connection pool (or mock for testing)

    Returns:
        FastAPI APIRouter with compliance endpoints.
    """
    router = APIRouter(
        prefix="/api/v1/compliance", tags=["compliance"]
    )

    @router.get("/audit-log")
    async def get_audit_log(
        from_date: datetime = Query(..., description="Start date (ISO 8601)"),
        to_date: datetime = Query(..., description="End date (ISO 8601)"),
        viewer_role: str = Query(
            default="user", description="Viewer's role for RBAC"
        ),
        user_id: str | None = Query(
            default=None, description="Filter by user ID"
        ),
        viewer_department: str | None = Query(
            default=None, description="Viewer's department (for manager role)"
        ),
    ) -> dict:
        """Get audit log entries with RBAC filtering.

        Regular users see only their own entries. Compliance officers
        and admins see all entries. Managers see their department's entries.
        """
        logger = AuditLogger()
        rbac = AuditRBAC()

        async with db_pool.acquire() as conn:
            entries = await logger.get_by_date_range(
                conn, from_date, to_date
            )

        # Apply RBAC filtering
        filtered = rbac.filter_entries_for_user(
            entries=entries,
            viewer_user_id=user_id or "",
            viewer_role=viewer_role,
            viewer_department=viewer_department,
        )

        return {
            "entries": [
                entry.model_dump(mode="json") for entry in filtered
            ],
            "total": len(filtered),
        }

    @router.get("/report")
    async def get_report(
        period_start: datetime = Query(
            ..., description="Report period start (ISO 8601)"
        ),
        period_end: datetime = Query(
            ..., description="Report period end (ISO 8601)"
        ),
        viewer_role: str = Query(
            default="user", description="Viewer's role for RBAC"
        ),
    ) -> dict:
        """Generate compliance report for a date range.

        Requires compliance_officer or admin role.
        """
        if viewer_role not in _PRIVILEGED_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Compliance reports require compliance_officer or admin role",
            )

        gen = ComplianceReportGenerator()

        async with db_pool.acquire() as conn:
            report = await gen.generate(conn, period_start, period_end)

        return report.model_dump(mode="json")

    @router.get("/lineage/{document_id}")
    async def get_lineage(document_id: str) -> dict:
        """Get full data lineage for a document.

        Returns all versions and all chunks with embedding info.
        """
        tracker = DataLineageTracker()

        async with db_pool.acquire() as conn:
            lineage = await tracker.get_full_lineage(conn, document_id)

        return lineage.model_dump(mode="json")

    @router.get("/hash-chain/verify")
    async def verify_hash_chain() -> dict:
        """Verify the integrity of the audit log hash chain.

        Returns whether the chain is valid and, if broken,
        the index of the first tampered entry.
        """
        logger = AuditLogger()

        async with db_pool.acquire() as conn:
            valid, broken_at = await logger.verify_hash_chain(conn)

        return {
            "valid": valid,
            "broken_at": broken_at,
        }

    @router.post("/bias-report")
    async def generate_bias_report(
        period_start: datetime = Query(
            ..., description="Report period start (ISO 8601)"
        ),
        period_end: datetime = Query(
            ..., description="Report period end (ISO 8601)"
        ),
        viewer_role: str = Query(
            default="user", description="Viewer's role for RBAC"
        ),
    ) -> dict:
        """Generate fairness/bias report for a date range.

        Requires compliance_officer or admin role.
        Checks routing bias, model preference bias, and
        degraded mode correlation.
        """
        if viewer_role not in _PRIVILEGED_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Bias reports require compliance_officer or admin role",
            )

        detector = BiasDetector()

        async with db_pool.acquire() as conn:
            report = await detector.generate_fairness_report(
                conn, period_start, period_end
            )

        return report

    return router
