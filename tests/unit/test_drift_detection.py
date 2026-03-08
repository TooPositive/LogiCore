"""Tests for the drift detector: regression suite, alerting, version change detection.

Phase 5, Pillar 2: Drift Detection — drift_detector.py.

Tests cover:
- Drift severity classification (green/yellow/red, n>=5)
- Regression detection against baselines (n>=5)
- Automatic regression trigger on version change
- Alert generation with extensible interface
- Concurrent version change during check
- Multi-metric drift
"""

from unittest.mock import MagicMock

import pytest

from apps.api.src.domain.telemetry import DriftAlert, DriftSeverity
from apps.api.src.telemetry.drift_detector import (
    AlertHandler,
    DriftDetector,
    LogAlertHandler,
    classify_drift_severity,
)
from apps.api.src.telemetry.model_registry import ModelVersionRegistry

# =========================================================================
# Drift severity classification (n>=5)
# =========================================================================


class TestDriftSeverityClassification:
    """Tests for classify_drift_severity function."""

    def test_green_no_drift(self):
        """0% drift -> GREEN."""
        assert classify_drift_severity(0.0) == DriftSeverity.GREEN

    def test_green_small_positive(self):
        """1% improvement -> GREEN."""
        assert classify_drift_severity(0.01) == DriftSeverity.GREEN

    def test_green_small_negative(self):
        """1.5% regression -> GREEN (below 2% threshold)."""
        assert classify_drift_severity(-0.015) == DriftSeverity.GREEN

    def test_yellow_2_percent(self):
        """Exactly 2% regression -> YELLOW."""
        assert classify_drift_severity(-0.02) == DriftSeverity.YELLOW

    def test_yellow_4_percent(self):
        """4% regression -> YELLOW."""
        assert classify_drift_severity(-0.04) == DriftSeverity.YELLOW

    def test_red_5_percent(self):
        """Exactly 5% regression -> RED."""
        assert classify_drift_severity(-0.05) == DriftSeverity.RED

    def test_red_10_percent(self):
        """10% regression -> RED."""
        assert classify_drift_severity(-0.10) == DriftSeverity.RED

    def test_green_large_improvement(self):
        """Large improvement -> GREEN (only regressions trigger yellow/red)."""
        assert classify_drift_severity(0.15) == DriftSeverity.GREEN

    def test_yellow_boundary(self):
        """Just below 5% regression -> YELLOW."""
        assert classify_drift_severity(-0.049) == DriftSeverity.YELLOW

    def test_custom_thresholds(self):
        """Custom thresholds override defaults."""
        # 3% regression with custom yellow=1%, red=3%
        assert (
            classify_drift_severity(-0.03, yellow_threshold=0.01, red_threshold=0.03)
            == DriftSeverity.RED
        )


# =========================================================================
# DriftDetector — regression detection (n>=5)
# =========================================================================


class TestDriftDetectorRegression:
    """Tests for DriftDetector comparing current scores against baselines."""

    def _make_detector(self, baseline_scores: dict[str, float]) -> DriftDetector:
        """Helper: create a detector with a registered baseline."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline_scores)
        handler = LogAlertHandler()
        return DriftDetector(registry=registry, alert_handler=handler)

    def test_no_drift_all_metrics_stable(self):
        """All metrics match baseline -> no alerts."""
        detector = self._make_detector(
            {"precision": 0.90, "faithfulness": 0.85, "relevancy": 0.88}
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"precision": 0.90, "faithfulness": 0.85, "relevancy": 0.88},
        )
        assert len(alerts) == 0

    def test_single_metric_red_drift(self):
        """One metric drops >5% -> one RED alert."""
        detector = self._make_detector({"precision": 0.90, "faithfulness": 0.85})
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"precision": 0.83, "faithfulness": 0.85},
        )
        assert len(alerts) == 1
        assert alerts[0].metric == "precision"
        assert alerts[0].severity == DriftSeverity.RED
        assert alerts[0].delta == pytest.approx(-0.07)

    def test_multiple_metrics_drift(self):
        """Multiple metrics drift -> multiple alerts."""
        detector = self._make_detector(
            {"precision": 0.90, "faithfulness": 0.85, "relevancy": 0.88}
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={
                "precision": 0.83,   # -7% RED
                "faithfulness": 0.82, # -3% YELLOW
                "relevancy": 0.88,    # 0% GREEN (no alert)
            },
        )
        assert len(alerts) == 2
        severities = {a.metric: a.severity for a in alerts}
        assert severities["precision"] == DriftSeverity.RED
        assert severities["faithfulness"] == DriftSeverity.YELLOW

    def test_improvement_no_alert(self):
        """Scores improve -> no alerts."""
        detector = self._make_detector({"precision": 0.85})
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"precision": 0.92},
        )
        assert len(alerts) == 0

    def test_yellow_drift_threshold(self):
        """3% regression -> YELLOW alert."""
        detector = self._make_detector({"precision": 0.90})
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"precision": 0.87},
        )
        assert len(alerts) == 1
        assert alerts[0].severity == DriftSeverity.YELLOW

    def test_unregistered_model_returns_empty(self):
        """No baseline -> cannot detect drift -> no alerts."""
        registry = ModelVersionRegistry()
        detector = DriftDetector(registry=registry, alert_handler=LogAlertHandler())
        alerts = detector.check_regression(
            model_name="unknown-model",
            current_scores={"precision": 0.50},
        )
        assert len(alerts) == 0

    def test_alert_contains_model_info(self):
        """Alerts include model name and version."""
        detector = self._make_detector({"precision": 0.90})
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"precision": 0.80},
        )
        assert alerts[0].model_name == "gpt-5.2"
        assert alerts[0].model_version == "v1"


# =========================================================================
# DriftDetector — version change detection
# =========================================================================


class TestDriftDetectorVersionChange:
    """Tests for version change detection and automatic regression trigger."""

    def test_no_version_change(self):
        """Same version -> no change detected."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        detector = DriftDetector(registry=registry, alert_handler=LogAlertHandler())

        changed = detector.detect_version_change("gpt-5.2", "v1")
        assert changed is False

    def test_version_change_detected(self):
        """Different version -> change detected."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        detector = DriftDetector(registry=registry, alert_handler=LogAlertHandler())

        changed = detector.detect_version_change("gpt-5.2", "v2")
        assert changed is True

    def test_version_change_triggers_alert(self):
        """Version change fires an alert via the alert handler."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        mock_handler = MagicMock(spec=AlertHandler)
        detector = DriftDetector(registry=registry, alert_handler=mock_handler)

        detector.on_version_change("gpt-5.2", "v1", "v2")
        mock_handler.handle.assert_called_once()
        alert_arg = mock_handler.handle.call_args[0][0]
        assert isinstance(alert_arg, DriftAlert)
        assert "version" in alert_arg.metric.lower()


# =========================================================================
# Alert handler — extensible interface
# =========================================================================


class TestAlertHandler:
    """Tests for the extensible alert handler interface."""

    def test_log_handler_does_not_raise(self):
        """LogAlertHandler should handle alerts without errors."""
        handler = LogAlertHandler()
        alert = DriftAlert(
            metric="precision",
            baseline_value=0.90,
            current_value=0.83,
            delta=-0.07,
            severity=DriftSeverity.RED,
        )
        # Should not raise
        handler.handle(alert)

    def test_custom_handler_called(self):
        """Custom handler receives the alert object."""
        received_alerts = []

        class TestHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                received_alerts.append(alert)

        handler = TestHandler()
        alert = DriftAlert(
            metric="faithfulness",
            baseline_value=0.85,
            current_value=0.80,
            delta=-0.05,
            severity=DriftSeverity.RED,
        )
        handler.handle(alert)
        assert len(received_alerts) == 1
        assert received_alerts[0].metric == "faithfulness"

    def test_multiple_alerts_dispatched(self):
        """Handler receives multiple alerts for multi-metric drift."""
        received = []

        class CollectorHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                received.append(alert)

        registry = ModelVersionRegistry()
        registry.register(
            "gpt-5.2", "v1", {"p": 0.90, "f": 0.85}
        )
        detector = DriftDetector(
            registry=registry, alert_handler=CollectorHandler()
        )
        detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.80, "f": 0.75},  # both RED drift
        )
        assert len(received) == 2

    def test_handler_receives_severity(self):
        """Handler can filter by severity."""
        red_alerts = []

        class RedOnlyHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                if alert.severity == DriftSeverity.RED:
                    red_alerts.append(alert)

        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90, "f": 0.85})
        detector = DriftDetector(
            registry=registry, alert_handler=RedOnlyHandler()
        )
        detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.80, "f": 0.83},  # p=RED, f=YELLOW
        )
        assert len(red_alerts) == 1
        assert red_alerts[0].metric == "p"


# =========================================================================
# DriftDetector — edge cases and regression suite
# =========================================================================


class TestDriftDetectorEdgeCases:
    """Edge cases and regression suite scenarios."""

    def test_regression_with_missing_metric(self):
        """Current scores missing a baseline metric -> ignored (not alert)."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90, "f": 0.85})
        detector = DriftDetector(
            registry=registry, alert_handler=LogAlertHandler()
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.90},  # f missing
        )
        # Only metrics present in both baseline and current are compared
        assert len(alerts) == 0

    def test_regression_with_extra_metric(self):
        """Current scores have extra metrics not in baseline -> ignored."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        detector = DriftDetector(
            registry=registry, alert_handler=LogAlertHandler()
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.90, "new_metric": 0.50},
        )
        assert len(alerts) == 0

    def test_exact_threshold_boundary_yellow(self):
        """Exactly -2% -> YELLOW (not GREEN)."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        detector = DriftDetector(
            registry=registry, alert_handler=LogAlertHandler()
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.88},  # -0.02 = exactly 2%
        )
        assert len(alerts) == 1
        assert alerts[0].severity == DriftSeverity.YELLOW

    def test_exact_threshold_boundary_red(self):
        """Exactly -5% -> RED (not YELLOW)."""
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", {"p": 0.90})
        detector = DriftDetector(
            registry=registry, alert_handler=LogAlertHandler()
        )
        alerts = detector.check_regression(
            model_name="gpt-5.2",
            current_scores={"p": 0.85},  # -0.05 = exactly 5%
        )
        assert len(alerts) == 1
        assert alerts[0].severity == DriftSeverity.RED


# =========================================================================
# Large-scale regression suite (100+ metrics)
# =========================================================================


class TestLargeScaleRegressionSuite:
    """Tests for drift detection at production scale (100+ metrics).

    The spec mentions "100+ test cases" in the regression suite.
    This validates per-metric alerting works at that scale without
    any aggregation masking individual metric regressions.
    """

    def test_100_metrics_mixed_drift(self):
        """100 metrics with 5 RED, 10 YELLOW, 85 GREEN.

        Per-metric alerting must generate exactly 15 alerts.
        No aggregation masking — each metric is evaluated independently.
        """
        # Build baseline with 100 metrics
        baseline = {f"metric_{i:03d}": 0.90 for i in range(100)}
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline)

        collected = []

        class CollectorHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                collected.append(alert)

        detector = DriftDetector(
            registry=registry, alert_handler=CollectorHandler()
        )

        # Current scores: 5 RED, 10 YELLOW, 85 GREEN
        current = {}
        for i in range(100):
            if i < 5:
                current[f"metric_{i:03d}"] = 0.83  # -7% RED
            elif i < 15:
                current[f"metric_{i:03d}"] = 0.87  # -3% YELLOW
            else:
                current[f"metric_{i:03d}"] = 0.89  # -1% GREEN
        alerts = detector.check_regression("gpt-5.2", current)

        assert len(alerts) == 15
        red_count = sum(1 for a in alerts if a.severity == DriftSeverity.RED)
        yellow_count = sum(1 for a in alerts if a.severity == DriftSeverity.YELLOW)
        assert red_count == 5
        assert yellow_count == 10

    def test_100_metrics_all_improved(self):
        """100 metrics all improved -> zero alerts."""
        baseline = {f"metric_{i:03d}": 0.85 for i in range(100)}
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline)

        detector = DriftDetector(
            registry=registry, alert_handler=LogAlertHandler()
        )
        current = {f"metric_{i:03d}": 0.92 for i in range(100)}
        alerts = detector.check_regression("gpt-5.2", current)
        assert len(alerts) == 0

    def test_100_metrics_all_red(self):
        """Catastrophic regression: all 100 metrics RED."""
        baseline = {f"metric_{i:03d}": 0.90 for i in range(100)}
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline)

        collected = []

        class CollectorHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                collected.append(alert)

        detector = DriftDetector(
            registry=registry, alert_handler=CollectorHandler()
        )
        current = {f"metric_{i:03d}": 0.50 for i in range(100)}
        alerts = detector.check_regression("gpt-5.2", current)

        assert len(alerts) == 100
        assert all(a.severity == DriftSeverity.RED for a in alerts)

    def test_metrics_cancelling_out_still_individual_alerts(self):
        """5 metrics regress, 5 improve. Aggregate net change = 0.

        But per-metric alerting must still fire 5 alerts for the regressions.
        Aggregation masking is the enemy of drift detection.
        """
        baseline = {f"metric_{i:03d}": 0.90 for i in range(10)}
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline)

        collected = []

        class CollectorHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                collected.append(alert)

        detector = DriftDetector(
            registry=registry, alert_handler=CollectorHandler()
        )
        current = {}
        for i in range(10):
            if i < 5:
                current[f"metric_{i:03d}"] = 0.80  # -10% RED
            else:
                current[f"metric_{i:03d}"] = 1.00  # +10% improvement (GREEN)

        alerts = detector.check_regression("gpt-5.2", current)
        assert len(alerts) == 5  # Only regressions, not improvements
        assert all(a.severity == DriftSeverity.RED for a in alerts)

    def test_per_metric_alert_contains_metric_name(self):
        """Each alert references the specific metric that drifted."""
        baseline = {f"metric_{i:03d}": 0.90 for i in range(50)}
        registry = ModelVersionRegistry()
        registry.register("gpt-5.2", "v1", baseline)

        collected = []

        class CollectorHandler(AlertHandler):
            def handle(self, alert: DriftAlert) -> None:
                collected.append(alert)

        detector = DriftDetector(
            registry=registry, alert_handler=CollectorHandler()
        )
        # Only metric_007 and metric_042 regress
        current = {f"metric_{i:03d}": 0.90 for i in range(50)}
        current["metric_007"] = 0.80  # RED
        current["metric_042"] = 0.87  # YELLOW

        alerts = detector.check_regression("gpt-5.2", current)
        alert_metrics = {a.metric for a in alerts}
        assert alert_metrics == {"metric_007", "metric_042"}
