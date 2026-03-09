"""Unit tests for Phase 8 bias detection.

Tests cover:
- detect_routing_bias(): checks if decisions unfairly distributed across departments
- detect_model_preference_bias(): checks if queries consistently routed to specific models
- generate_fairness_report(): comprehensive fairness assessment
- No bias detected when decisions are evenly distributed
- Bias detected when one department has disproportionate decisions (>2x expected)
- Model preference bias detected when queries always go to same model
- Empty period returns clean report
- Degraded mode correlation with specific departments flagged

All tests use mocked asyncpg connections (no Docker dependencies).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest


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


class TestDetectRoutingBias:
    """detect_routing_bias(conn, period_start, period_end) -> dict."""

    @pytest.mark.asyncio
    async def test_no_bias_when_decisions_evenly_distributed(
        self, mock_conn, period
    ):
        """Even distribution across departments = no bias flagged."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # 3 departments, ~33% each -- within normal range
        dept_rows = [
            {"department": "logistics", "count": 33},
            {"department": "finance", "count": 34},
            {"department": "compliance", "count": 33},
        ]
        mock_conn.fetch = AsyncMock(return_value=dept_rows)
        mock_conn.fetchval = AsyncMock(return_value=100)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is False

    @pytest.mark.asyncio
    async def test_bias_detected_when_department_disproportionate(
        self, mock_conn, period
    ):
        """One department has >2x expected rate = bias flagged."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # 3 departments but logistics has 80% of decisions
        dept_rows = [
            {"department": "logistics", "count": 80},
            {"department": "finance", "count": 10},
            {"department": "compliance", "count": 10},
        ]
        mock_conn.fetch = AsyncMock(return_value=dept_rows)
        mock_conn.fetchval = AsyncMock(return_value=100)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is True
        assert "logistics" in result["flagged_departments"]

    @pytest.mark.asyncio
    async def test_routing_bias_empty_period_no_bias(
        self, mock_conn, period
    ):
        """Empty period returns no bias."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchval = AsyncMock(return_value=0)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is False
        assert result["flagged_departments"] == []


class TestMinimumSampleSize:
    """Bias detection must return insufficient_data when n < 30."""

    @pytest.mark.asyncio
    async def test_small_sample_returns_insufficient_data(
        self, mock_conn, period
    ):
        """n=10 is too small for meaningful bias detection."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # Even with extreme imbalance, n=10 is insufficient
        dept_rows = [
            {"department": "logistics", "count": 9},
            {"department": "finance", "count": 1},
        ]
        mock_conn.fetch = AsyncMock(return_value=dept_rows)
        mock_conn.fetchval = AsyncMock(return_value=10)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is False
        assert result["insufficient_data"] is True

    @pytest.mark.asyncio
    async def test_sufficient_sample_enables_detection(
        self, mock_conn, period
    ):
        """n=100 is sufficient — bias detection works normally."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # 3 depts: expected=33%. logistics=80% -> ratio=2.4x > 2x -> bias
        dept_rows = [
            {"department": "logistics", "count": 80},
            {"department": "finance", "count": 10},
            {"department": "compliance", "count": 10},
        ]
        mock_conn.fetch = AsyncMock(return_value=dept_rows)
        mock_conn.fetchval = AsyncMock(return_value=100)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is True
        assert result["insufficient_data"] is False

    @pytest.mark.asyncio
    async def test_boundary_at_30_enables_detection(
        self, mock_conn, period
    ):
        """n=30 is the minimum — bias detection should work."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        dept_rows = [
            {"department": "logistics", "count": 25},
            {"department": "finance", "count": 5},
        ]
        mock_conn.fetch = AsyncMock(return_value=dept_rows)
        mock_conn.fetchval = AsyncMock(return_value=30)

        detector = BiasDetector()
        result = await detector.detect_routing_bias(
            mock_conn, period[0], period[1]
        )

        # 25/30 = 83%, expected = 50%, ratio = 1.67x — NOT > 2x, so no bias
        assert result["insufficient_data"] is False

    @pytest.mark.asyncio
    async def test_model_preference_also_checks_sample_size(
        self, mock_conn, period
    ):
        """Model preference bias also respects minimum sample size."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        model_rows = [
            {"model_version": "gpt-5.2", "count": 8},
            {"model_version": "ollama", "count": 2},
        ]
        mock_conn.fetch = AsyncMock(return_value=model_rows)
        mock_conn.fetchval = AsyncMock(return_value=10)

        detector = BiasDetector()
        result = await detector.detect_model_preference_bias(
            mock_conn, period[0], period[1]
        )

        assert result["insufficient_data"] is True
        assert result["bias_detected"] is False


class TestDetectModelPreferenceBias:
    """detect_model_preference_bias(conn, period_start, period_end) -> dict."""

    @pytest.mark.asyncio
    async def test_model_preference_bias_detected(self, mock_conn, period):
        """One model handles >2x expected share = bias flagged."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # 3 models: gpt-5.2 has 80% (expected ~33%) -- 80/33 = 2.4x
        model_rows = [
            {"model_version": "gpt-5.2", "count": 80},
            {"model_version": "ollama-qwen3", "count": 10},
            {"model_version": "gpt-4o", "count": 10},
        ]
        mock_conn.fetch = AsyncMock(return_value=model_rows)
        mock_conn.fetchval = AsyncMock(return_value=100)

        detector = BiasDetector()
        result = await detector.detect_model_preference_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is True
        assert "gpt-5.2" in result["flagged_models"]

    @pytest.mark.asyncio
    async def test_no_model_preference_bias_when_balanced(
        self, mock_conn, period
    ):
        """Balanced model usage = no bias."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        model_rows = [
            {"model_version": "gpt-5.2", "count": 55},
            {"model_version": "ollama-qwen3", "count": 45},
        ]
        mock_conn.fetch = AsyncMock(return_value=model_rows)
        mock_conn.fetchval = AsyncMock(return_value=100)

        detector = BiasDetector()
        result = await detector.detect_model_preference_bias(
            mock_conn, period[0], period[1]
        )

        assert result["bias_detected"] is False


class TestGenerateFairnessReport:
    """generate_fairness_report(conn, period_start, period_end) -> dict."""

    @pytest.mark.asyncio
    async def test_fairness_report_includes_all_checks(
        self, mock_conn, period
    ):
        """Comprehensive report includes routing + model checks."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # Routing check: even distribution
        dept_rows = [
            {"department": "logistics", "count": 50},
            {"department": "finance", "count": 50},
        ]
        # Model check: even distribution
        model_rows = [
            {"model_version": "gpt-5.2", "count": 50},
            {"model_version": "ollama-qwen3", "count": 50},
        ]
        # Degraded by department: no correlation
        degraded_dept_rows = [
            {"department": "logistics", "count": 5},
            {"department": "finance", "count": 5},
        ]

        mock_conn.fetch = AsyncMock(
            side_effect=[dept_rows, model_rows, degraded_dept_rows]
        )
        mock_conn.fetchval = AsyncMock(
            side_effect=[100, 100, 10]
        )

        detector = BiasDetector()
        report = await detector.generate_fairness_report(
            mock_conn, period[0], period[1]
        )

        assert "routing_bias" in report
        assert "model_preference_bias" in report
        assert "degraded_correlation" in report
        assert report["routing_bias"]["bias_detected"] is False
        assert report["model_preference_bias"]["bias_detected"] is False

    @pytest.mark.asyncio
    async def test_empty_period_returns_clean_report(
        self, mock_conn, period
    ):
        """Empty period returns clean fairness report."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.fetchval = AsyncMock(return_value=0)

        detector = BiasDetector()
        report = await detector.generate_fairness_report(
            mock_conn, period[0], period[1]
        )

        assert report["routing_bias"]["bias_detected"] is False
        assert report["model_preference_bias"]["bias_detected"] is False
        assert report["degraded_correlation"]["bias_detected"] is False

    @pytest.mark.asyncio
    async def test_degraded_mode_correlation_with_department_flagged(
        self, mock_conn, period
    ):
        """Degraded decisions concentrated in one dept = flagged."""
        from apps.api.src.domains.logicore.compliance.bias_detector import (
            BiasDetector,
        )

        # Routing: even
        dept_rows = [
            {"department": "logistics", "count": 50},
            {"department": "finance", "count": 50},
        ]
        # Models: even
        model_rows = [
            {"model_version": "gpt-5.2", "count": 50},
            {"model_version": "ollama-qwen3", "count": 50},
        ]
        # Degraded: concentrated in logistics (3 depts, 75% in logistics)
        # Expected per dept = 33%. Actual logistics = 75%. 75/33 = 2.27x > 2x
        # Total must be >= 30 (minimum sample size for bias detection)
        degraded_dept_rows = [
            {"department": "logistics", "count": 24},
            {"department": "finance", "count": 4},
            {"department": "compliance", "count": 4},
        ]

        mock_conn.fetch = AsyncMock(
            side_effect=[dept_rows, model_rows, degraded_dept_rows]
        )
        mock_conn.fetchval = AsyncMock(
            side_effect=[100, 100, 32]
        )

        detector = BiasDetector()
        report = await detector.generate_fairness_report(
            mock_conn, period[0], period[1]
        )

        assert report["degraded_correlation"]["bias_detected"] is True
        assert "logistics" in report["degraded_correlation"][
            "flagged_departments"
        ]
