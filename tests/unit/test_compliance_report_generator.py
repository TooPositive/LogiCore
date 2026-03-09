"""Unit tests for Phase 8 compliance report generator.

Tests cover:
- generate(): full compliance report for a date range
- Report completeness: no silent exclusion of entries
- Aggregation by model version
- Degraded decisions flagged
- Hash chain verification included in report
- entry_count_hash correctness and verifiability
- Empty period returns report with zero counts
- get_degraded_decisions(): filters correctly
- generate_summary_stats(): returns correct quick stats

All tests use mocked asyncpg connections (no Docker dependencies).
"""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    ComplianceReport,
)


def _make_db_row(**overrides) -> dict:
    """Factory for audit_log database row."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime(2026, 2, 15, 10, 0, 0, tzinfo=UTC),
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
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_cost_eur": Decimal("0.005"),
        "response_hash": None,
        "is_degraded": False,
        "provider_name": None,
        "quality_drift_alert": False,
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def mock_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    return conn


@pytest.fixture
def period():
    """Standard test period: Jan 1 to Mar 31, 2026."""
    return (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 3, 31, tzinfo=UTC),
    )


class TestGenerateReport:
    """generate(conn, period_start, period_end) -> ComplianceReport."""

    @pytest.mark.asyncio
    async def test_generate_report_for_date_range(self, mock_conn, period):
        """Generates a ComplianceReport for the given date range."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [
            _make_db_row(user_id="user-01", model_version="gpt-5.2"),
            _make_db_row(user_id="user-02", model_version="gpt-5.2"),
            _make_db_row(user_id="user-01", model_version="gpt-4o"),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert isinstance(report, ComplianceReport)
        assert report.period_start == period[0]
        assert report.period_end == period[1]
        assert report.total_entries == 3
        assert report.unique_users == 2

    @pytest.mark.asyncio
    async def test_report_includes_all_entries_no_silent_exclusion(
        self, mock_conn, period
    ):
        """Report must include ALL entries in the range -- no filtering."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [_make_db_row() for _ in range(7)]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert report.total_entries == 7

    @pytest.mark.asyncio
    async def test_report_aggregates_by_model_version(self, mock_conn, period):
        """models_used lists all distinct model versions."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [
            _make_db_row(model_version="gpt-5.2"),
            _make_db_row(model_version="gpt-5.2"),
            _make_db_row(model_version="gpt-4o"),
            _make_db_row(model_version="ollama-qwen3"),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert set(report.models_used) == {"gpt-5.2", "gpt-4o", "ollama-qwen3"}

    @pytest.mark.asyncio
    async def test_report_flags_degraded_decisions(self, mock_conn, period):
        """Report metadata includes degraded_count for regulator visibility."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [
            _make_db_row(is_degraded=False),
            _make_db_row(is_degraded=True, provider_name="ollama"),
            _make_db_row(is_degraded=True, provider_name="ollama"),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert report.metadata["degraded_count"] == 2

    @pytest.mark.asyncio
    async def test_report_includes_hash_chain_verification(
        self, mock_conn, period
    ):
        """Report metadata includes hash chain integrity check result."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [_make_db_row()]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert report.metadata["hash_chain_valid"] is True
        assert report.metadata["hash_chain_broken_at"] is None

    @pytest.mark.asyncio
    async def test_entry_count_hash_is_correct_and_verifiable(
        self, mock_conn, period
    ):
        """entry_count_hash = SHA-256(f'{count}:{start}:{end}')."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [_make_db_row() for _ in range(5)]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        expected_content = (
            f"5:{period[0].isoformat()}:{period[1].isoformat()}"
        )
        expected_hash = hashlib.sha256(
            expected_content.encode()
        ).hexdigest()
        assert (
            report.metadata["entry_count_hash"]
            == f"sha256:{expected_hash}"
        )

    @pytest.mark.asyncio
    async def test_empty_period_returns_report_with_zero_counts(
        self, mock_conn, period
    ):
        """Empty period returns a valid report with zero counts."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        mock_conn.fetch = AsyncMock(return_value=[])

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert report.total_entries == 0
        assert report.unique_users == 0
        assert report.models_used == []
        assert report.total_cost_eur == Decimal("0")
        assert report.hitl_approval_count == 0

    @pytest.mark.asyncio
    async def test_report_entries_by_level(self, mock_conn, period):
        """Report aggregates entries by log_level."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        rows = [
            _make_db_row(log_level="full_trace"),
            _make_db_row(log_level="full_trace"),
            _make_db_row(log_level="summary"),
            _make_db_row(log_level="metadata_only"),
        ]
        mock_conn.fetch = AsyncMock(return_value=rows)

        gen = ComplianceReportGenerator()

        with patch(
            "apps.api.src.domains.logicore.compliance.report_generator"
            ".AuditLogger.verify_hash_chain",
            new_callable=AsyncMock,
            return_value=(True, None),
        ):
            report = await gen.generate(mock_conn, period[0], period[1])

        assert report.entries_by_level["full_trace"] == 2
        assert report.entries_by_level["summary"] == 1
        assert report.entries_by_level["metadata_only"] == 1


class TestGetDegradedDecisions:
    """get_degraded_decisions(conn, period_start, period_end)."""

    @pytest.mark.asyncio
    async def test_get_degraded_decisions_filters_correctly(
        self, mock_conn, period
    ):
        """Returns only degraded entries."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        degraded_rows = [
            _make_db_row(is_degraded=True, provider_name="ollama"),
            _make_db_row(is_degraded=True, provider_name="ollama"),
        ]
        mock_conn.fetch = AsyncMock(return_value=degraded_rows)

        gen = ComplianceReportGenerator()
        results = await gen.get_degraded_decisions(
            mock_conn, period[0], period[1]
        )

        assert len(results) == 2
        assert all(isinstance(r, AuditEntry) for r in results)
        assert all(r.is_degraded for r in results)

    @pytest.mark.asyncio
    async def test_get_degraded_decisions_uses_parameterized_sql(
        self, mock_conn, period
    ):
        """SQL uses $1, $2 params, not string interpolation."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        mock_conn.fetch = AsyncMock(return_value=[])

        gen = ComplianceReportGenerator()
        await gen.get_degraded_decisions(mock_conn, period[0], period[1])

        sql_arg = mock_conn.fetch.call_args[0][0]
        assert "$1" in sql_arg
        assert "$2" in sql_arg
        assert "is_degraded" in sql_arg


class TestGenerateSummaryStats:
    """generate_summary_stats(conn, period_start, period_end) -> dict."""

    @pytest.mark.asyncio
    async def test_generate_summary_stats_returns_correct_stats(
        self, mock_conn, period
    ):
        """Quick stats without full entries."""
        from apps.api.src.domains.logicore.compliance.report_generator import (
            ComplianceReportGenerator,
        )

        # Mock: count=10, degraded=2, distinct_models=3, distinct_users=5
        mock_conn.fetchval = AsyncMock(side_effect=[10, 2, 3, 5])

        gen = ComplianceReportGenerator()
        stats = await gen.generate_summary_stats(
            mock_conn, period[0], period[1]
        )

        assert stats["total_entries"] == 10
        assert stats["degraded_count"] == 2
        assert stats["distinct_models"] == 3
        assert stats["distinct_users"] == 5
