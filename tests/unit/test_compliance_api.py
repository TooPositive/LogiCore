"""Unit tests for Phase 8 compliance API endpoints.

Tests cover:
- GET /api/v1/compliance/audit-log: returns entries, date filtering, RBAC
- GET /api/v1/compliance/report: requires compliance_officer role
- GET /api/v1/compliance/lineage/{document_id}: returns full lineage
- GET /api/v1/compliance/hash-chain/verify: returns integrity status
- POST /api/v1/compliance/bias-report: requires compliance_officer role
- Input validation (invalid dates return 422)
- Rate limit awareness (endpoint accepts X-RateLimit headers)

All tests use FastAPI TestClient with dependency overrides (no Docker).
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    ComplianceReport,
    LogLevel,
)


def _make_audit_entry(**overrides) -> AuditEntry:
    """Factory for AuditEntry model instances."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime(2026, 2, 15, 10, 0, 0, tzinfo=UTC),
        "entry_hash": "sha256:abc123",
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
        "hitl_approver_id": None,
        "langfuse_trace_id": None,
        "metadata": {},
        "log_level": LogLevel.FULL_TRACE,
        "prev_entry_hash": None,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_cost_eur": Decimal("0.005"),
        "response_hash": None,
        "is_degraded": False,
        "provider_name": None,
        "quality_drift_alert": False,
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    return conn


@pytest.fixture
def app_with_mocks():
    """Create FastAPI app with compliance router and mocked dependencies."""
    from fastapi import FastAPI

    from apps.api.src.domains.logicore.api.compliance import (
        create_compliance_router,
    )

    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()

    # Context manager for pool.acquire()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm

    app = FastAPI()
    router = create_compliance_router(db_pool=mock_pool)
    app.include_router(router)

    return app, mock_conn, mock_pool


class TestGetAuditLog:
    """GET /api/v1/compliance/audit-log."""

    @pytest.mark.asyncio
    async def test_get_audit_log_returns_entries(self, app_with_mocks):
        """Returns paginated audit entries."""
        app, mock_conn, _ = app_with_mocks
        entries = [_make_audit_entry(), _make_audit_entry()]

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditLogger.get_by_date_range",
            new_callable=AsyncMock,
            return_value=entries,
        ), patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditRBAC.filter_entries_for_user",
            return_value=entries,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/audit-log",
                    params={
                        "from_date": "2026-01-01T00:00:00Z",
                        "to_date": "2026-03-31T00:00:00Z",
                        "user_id": "user-logistics-01",
                        "viewer_role": "compliance_officer",
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2

    @pytest.mark.asyncio
    async def test_audit_log_filtered_by_date_range(self, app_with_mocks):
        """Date params passed to audit logger."""
        app, mock_conn, _ = app_with_mocks

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditLogger.get_by_date_range",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_get, patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditRBAC.filter_entries_for_user",
            return_value=[],
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                await ac.get(
                    "/api/v1/compliance/audit-log",
                    params={
                        "from_date": "2026-01-01T00:00:00Z",
                        "to_date": "2026-03-31T00:00:00Z",
                        "viewer_role": "user",
                    },
                )

        mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_log_rbac_regular_user_sees_own_entries(
        self, app_with_mocks
    ):
        """Regular user only sees their own entries via RBAC filter."""
        app, mock_conn, _ = app_with_mocks

        all_entries = [
            _make_audit_entry(user_id="user-01"),
            _make_audit_entry(user_id="user-02"),
        ]
        # RBAC filter returns only user-01's entries
        filtered = [all_entries[0]]

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditLogger.get_by_date_range",
            new_callable=AsyncMock,
            return_value=all_entries,
        ), patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditRBAC.filter_entries_for_user",
            return_value=filtered,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/audit-log",
                    params={
                        "from_date": "2026-01-01T00:00:00Z",
                        "to_date": "2026-03-31T00:00:00Z",
                        "user_id": "user-01",
                        "viewer_role": "user",
                    },
                )

        assert response.status_code == 200
        assert response.json()["total"] == 1


class TestGetReport:
    """GET /api/v1/compliance/report."""

    @pytest.mark.asyncio
    async def test_get_report_requires_compliance_officer(
        self, app_with_mocks
    ):
        """Returns 403 for non-compliance roles."""
        app, mock_conn, _ = app_with_mocks

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            response = await ac.get(
                "/api/v1/compliance/report",
                params={
                    "period_start": "2026-01-01T00:00:00Z",
                    "period_end": "2026-03-31T00:00:00Z",
                    "viewer_role": "user",
                },
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_report_success_for_compliance_officer(
        self, app_with_mocks
    ):
        """Compliance officer can generate report."""
        app, mock_conn, _ = app_with_mocks

        report = ComplianceReport(
            report_id=uuid4(),
            generated_at=datetime.now(UTC),
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 31, tzinfo=UTC),
            total_entries=100,
            entries_by_level={"full_trace": 80, "summary": 20},
            models_used=["gpt-5.2"],
            unique_users=10,
            hitl_approval_count=5,
            total_cost_eur=Decimal("12.50"),
            generated_by="compliance-report-generator",
        )

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".ComplianceReportGenerator.generate",
            new_callable=AsyncMock,
            return_value=report,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/report",
                    params={
                        "period_start": "2026-01-01T00:00:00Z",
                        "period_end": "2026-03-31T00:00:00Z",
                        "viewer_role": "compliance_officer",
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 100


class TestGetLineage:
    """GET /api/v1/compliance/lineage/{document_id}."""

    @pytest.mark.asyncio
    async def test_get_lineage_returns_full_chain(self, app_with_mocks):
        """Returns full lineage for a document."""
        app, mock_conn, _ = app_with_mocks

        from apps.api.src.domains.logicore.models.compliance import (
            ChunkVersion,
            DocumentVersion,
            LineageRecord,
        )

        doc_id = uuid4()
        lineage = LineageRecord(
            document_id="CTR-2024-001",
            versions=[
                DocumentVersion(
                    id=doc_id,
                    document_id="CTR-2024-001",
                    version=1,
                    ingested_at=datetime.now(UTC),
                    source_hash="a" * 64,
                    chunk_count=2,
                ),
            ],
            chunks=[
                ChunkVersion(
                    id=uuid4(),
                    document_version_id=doc_id,
                    chunk_index=0,
                    content_hash="b" * 64,
                    qdrant_point_id="q-1",
                    embedding_model="text-embedding-3-small",
                ),
            ],
        )

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".DataLineageTracker.get_full_lineage",
            new_callable=AsyncMock,
            return_value=lineage,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/lineage/CTR-2024-001",
                )

        assert response.status_code == 200
        data = response.json()
        assert data["document_id"] == "CTR-2024-001"
        assert len(data["versions"]) == 1
        assert len(data["chunks"]) == 1


class TestHashChainVerify:
    """GET /api/v1/compliance/hash-chain/verify."""

    @pytest.mark.asyncio
    async def test_hash_chain_verify_returns_integrity_status(
        self, app_with_mocks
    ):
        """Returns hash chain verification result."""
        app, mock_conn, _ = app_with_mocks

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/hash-chain/verify",
                )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["broken_at"] is None


class TestBiasReport:
    """POST /api/v1/compliance/bias-report."""

    @pytest.mark.asyncio
    async def test_bias_report_requires_compliance_officer(
        self, app_with_mocks
    ):
        """Returns 403 for non-compliance roles."""
        app, mock_conn, _ = app_with_mocks

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            response = await ac.post(
                "/api/v1/compliance/bias-report",
                params={
                    "period_start": "2026-01-01T00:00:00Z",
                    "period_end": "2026-03-31T00:00:00Z",
                    "viewer_role": "user",
                },
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_bias_report_success_for_compliance_officer(
        self, app_with_mocks
    ):
        """Compliance officer can generate bias report."""
        app, mock_conn, _ = app_with_mocks

        fairness_report = {
            "routing_bias": {"bias_detected": False, "flagged_departments": []},
            "model_preference_bias": {"bias_detected": False, "flagged_models": []},
            "degraded_correlation": {"bias_detected": False, "flagged_departments": []},
        }

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".BiasDetector.generate_fairness_report",
            new_callable=AsyncMock,
            return_value=fairness_report,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.post(
                    "/api/v1/compliance/bias-report",
                    params={
                        "period_start": "2026-01-01T00:00:00Z",
                        "period_end": "2026-03-31T00:00:00Z",
                        "viewer_role": "compliance_officer",
                    },
                )

        assert response.status_code == 200
        data = response.json()
        assert "routing_bias" in data
        assert "model_preference_bias" in data


class TestInputValidation:
    """Input validation for compliance endpoints."""

    @pytest.mark.asyncio
    async def test_invalid_dates_return_422(self, app_with_mocks):
        """Invalid date format returns 422 Unprocessable Entity."""
        app, _, _ = app_with_mocks

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            response = await ac.get(
                "/api/v1/compliance/audit-log",
                params={
                    "from_date": "not-a-date",
                    "to_date": "2026-03-31T00:00:00Z",
                    "viewer_role": "user",
                },
            )

        assert response.status_code == 422


class TestRateLimitAwareness:
    """Endpoints accept rate limit headers."""

    @pytest.mark.asyncio
    async def test_endpoint_accepts_rate_limit_headers(self, app_with_mocks):
        """Endpoints respond even with X-RateLimit headers present."""
        app, _, _ = app_with_mocks

        with patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditLogger.get_by_date_range",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "apps.api.src.domains.logicore.api.compliance"
            ".AuditRBAC.filter_entries_for_user",
            return_value=[],
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                response = await ac.get(
                    "/api/v1/compliance/audit-log",
                    params={
                        "from_date": "2026-01-01T00:00:00Z",
                        "to_date": "2026-03-31T00:00:00Z",
                        "viewer_role": "user",
                    },
                    headers={
                        "X-RateLimit-Limit": "100",
                        "X-RateLimit-Remaining": "99",
                    },
                )

        assert response.status_code == 200
