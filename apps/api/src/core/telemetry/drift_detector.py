"""Drift detector: automated regression testing and alerting.

Phase 5, Pillar 2: Drift Detection.

Domain-agnostic: works with any metric names. Alert handler is extensible
(implement AlertHandler protocol for Slack, email, PagerDuty, etc.).

Key design decisions:
- Thresholds: green (<2% drift), yellow (2-5%), red (>5%)
- Only regressions (negative deltas) trigger yellow/red
- Improvements are always green
- Missing metrics (in current but not baseline, or vice versa) are ignored
- Alert handler is a protocol — plug in any notification backend
"""

import abc
import logging
from datetime import UTC, datetime

from apps.api.src.core.domain.telemetry import DriftAlert, DriftSeverity
from apps.api.src.core.telemetry.model_registry import ModelVersionRegistry

logger = logging.getLogger(__name__)


def classify_drift_severity(
    delta: float,
    yellow_threshold: float = 0.02,
    red_threshold: float = 0.05,
) -> DriftSeverity:
    """Classify a metric delta into green/yellow/red severity.

    Only regressions (negative deltas) can be yellow or red.
    Improvements (positive deltas) are always green.

    Args:
        delta: The change in metric value (current - baseline). Negative = regression.
        yellow_threshold: Absolute regression threshold for yellow (default 2%).
        red_threshold: Absolute regression threshold for red (default 5%).

    Returns:
        DriftSeverity classification.
    """
    if delta >= 0:
        return DriftSeverity.GREEN

    abs_delta = abs(delta)
    if abs_delta >= red_threshold:
        return DriftSeverity.RED
    if abs_delta >= yellow_threshold:
        return DriftSeverity.YELLOW
    return DriftSeverity.GREEN


class AlertHandler(abc.ABC):
    """Abstract alert handler — extensible interface for drift notifications.

    Implement this for Slack, email, PagerDuty, or any notification backend.
    """

    @abc.abstractmethod
    def handle(self, alert: DriftAlert) -> None:
        """Handle a drift alert.

        Args:
            alert: The drift alert to process.
        """
        ...


class LogAlertHandler(AlertHandler):
    """Default alert handler that logs alerts to Python logging.

    Production deployments should replace this with Slack/email/PagerDuty handlers.
    """

    def handle(self, alert: DriftAlert) -> None:
        """Log the drift alert at appropriate severity level."""
        msg = (
            f"Drift alert [{alert.severity}]: {alert.metric} "
            f"baseline={alert.baseline_value:.4f} "
            f"current={alert.current_value:.4f} "
            f"delta={alert.delta:+.4f}"
        )
        if alert.model_name:
            msg += f" model={alert.model_name}"
        if alert.model_version:
            msg += f" version={alert.model_version}"

        if alert.severity == DriftSeverity.RED:
            logger.error(msg)
        elif alert.severity == DriftSeverity.YELLOW:
            logger.warning(msg)
        else:
            logger.info(msg)


class DriftDetector:
    """Automated drift detection against model version baselines.

    Compares current quality scores against registered baselines.
    Generates alerts when regressions exceed thresholds.
    Detects model version changes via the registry.
    """

    def __init__(
        self,
        registry: ModelVersionRegistry,
        alert_handler: AlertHandler,
        yellow_threshold: float = 0.02,
        red_threshold: float = 0.05,
    ) -> None:
        self._registry = registry
        self._alert_handler = alert_handler
        self._yellow_threshold = yellow_threshold
        self._red_threshold = red_threshold

    def check_regression(
        self,
        model_name: str,
        current_scores: dict[str, float],
    ) -> list[DriftAlert]:
        """Compare current scores against baseline and generate alerts.

        Only metrics present in BOTH baseline and current are compared.
        Green deltas (improvements or <2% regression) do not generate alerts.

        Args:
            model_name: The model to check.
            current_scores: Current quality metric scores.

        Returns:
            List of DriftAlert objects for metrics that exceed thresholds.
        """
        baseline = self._registry.get_baseline_scores(model_name)
        if not baseline:
            return []

        current_version = self._registry.get_current_version(model_name)
        version_str = current_version.version if current_version else None

        alerts: list[DriftAlert] = []

        for metric, baseline_value in baseline.items():
            if metric not in current_scores:
                continue

            current_value = current_scores[metric]
            delta = current_value - baseline_value
            severity = classify_drift_severity(
                delta,
                yellow_threshold=self._yellow_threshold,
                red_threshold=self._red_threshold,
            )

            if severity == DriftSeverity.GREEN:
                continue

            alert = DriftAlert(
                metric=metric,
                baseline_value=baseline_value,
                current_value=current_value,
                delta=delta,
                severity=severity,
                model_name=model_name,
                model_version=version_str,
            )
            alerts.append(alert)
            self._alert_handler.handle(alert)

        return alerts

    def detect_version_change(
        self, model_name: str, current_version: str
    ) -> bool:
        """Check if a model's version has changed.

        Delegates to the model registry's version change detection.

        Args:
            model_name: The model to check.
            current_version: The version currently being served.

        Returns:
            True if version has changed, False otherwise.
        """
        return self._registry.detect_version_change(model_name, current_version)

    def on_version_change(
        self,
        model_name: str,
        old_version: str,
        new_version: str,
    ) -> None:
        """Handle a detected model version change.

        Fires a version change alert via the alert handler.

        Args:
            model_name: The model whose version changed.
            old_version: The previous version.
            new_version: The new version.
        """
        alert = DriftAlert(
            metric=f"model_version_change: {old_version} -> {new_version}",
            baseline_value=0.0,
            current_value=0.0,
            delta=0.0,
            severity=DriftSeverity.YELLOW,
            model_name=model_name,
            model_version=new_version,
            detected_at=datetime.now(UTC),
        )
        self._alert_handler.handle(alert)
