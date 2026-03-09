"""Two-tier anomaly detector for fleet telemetry.

Tier 1: Rule-based detection (threshold, rate-of-change, speed). Zero LLM cost.
Tier 2: Statistical detection (z-score on rolling window). Zero LLM cost.

Only confirmed anomalies trigger the LangGraph Fleet Response agent (Tier 3, LLM cost).

Key design decisions:
- Rate-of-change detection catches slow drift BEFORE threshold breach (EUR 207,000 gap).
- Per-truck temperature history enables gradient and z-score calculations.
- Alert deduplication prevents alert fatigue (same truck + type within configurable window).
- Staleness tagging warns when sensor data is too old for reliable facility recommendation.
"""

import logging
import math
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from apps.api.src.domains.logicore.models.fleet import (
    AlertSeverity,
    AlertType,
    FleetAlert,
    GPSPing,
    TemperatureReading,
)

logger = logging.getLogger(__name__)

# Minimum readings needed for z-score to be meaningful
_MIN_ZSCORE_READINGS = 5

# Maximum history entries per truck (sliding window)
_MAX_HISTORY_SIZE = 120


class AnomalyDetector:
    """Stateful anomaly detector with threshold, gradient, z-score, and dedup.

    Args:
        threshold_margin: Degrees above/below setpoint to trigger spike alert.
        drift_rate_threshold: Max acceptable temp change (C) per 30 minutes.
        zscore_threshold: Z-score above which a reading is flagged.
        max_speed_kmh: Maximum allowed truck speed before alert.
        dedup_window_seconds: Suppress duplicate alerts within this window.
        staleness_threshold_seconds: Flag alerts on data older than this.
    """

    def __init__(
        self,
        threshold_margin: float = 5.0,
        drift_rate_threshold: float = 0.5,
        zscore_threshold: float = 3.0,
        max_speed_kmh: float = 120.0,
        dedup_window_seconds: int = 300,
        staleness_threshold_seconds: int = 30,
    ) -> None:
        self.threshold_margin = threshold_margin
        self.drift_rate_threshold = drift_rate_threshold
        self.zscore_threshold = zscore_threshold
        self.max_speed_kmh = max_speed_kmh
        self.dedup_window_seconds = dedup_window_seconds
        self.staleness_threshold_seconds = staleness_threshold_seconds

        # Per-truck temperature history: truck_id -> [(timestamp, temp_celsius)]
        self._temp_history: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

        # Dedup tracking: (truck_id, alert_type) -> last alert timestamp
        self._last_alert: dict[tuple[str, str], datetime] = {}

    def check_temperature(self, reading: TemperatureReading) -> list[FleetAlert]:
        """Run all temperature checks on a reading.

        Returns list of alerts (may be empty for normal readings).
        """
        alerts: list[FleetAlert] = []
        is_stale = self._is_stale(reading.timestamp)

        # Record history for this truck
        self._record_temp(reading.truck_id, reading.timestamp, reading.temp_celsius)

        # Tier 1a: Absolute threshold check
        if self._check_threshold(reading):
            alert = self._make_temp_alert(
                truck_id=reading.truck_id,
                alert_type=AlertType.TEMPERATURE_SPIKE,
                severity=AlertSeverity.CRITICAL,
                details=self._threshold_details(reading, is_stale),
                timestamp=reading.timestamp,
            )
            if alert:
                alerts.append(alert)

        # Tier 1b: Rate-of-change (gradient) check
        drift_alert = self._check_drift(reading)
        if drift_alert:
            alerts.append(drift_alert)

        # Tier 2: Z-score statistical check
        zscore_alert = self._check_zscore(reading, is_stale)
        if zscore_alert:
            alerts.append(zscore_alert)

        return alerts

    def check_gps(self, ping: GPSPing) -> list[FleetAlert]:
        """Run GPS-related checks on a ping.

        Returns list of alerts (may be empty for normal pings).
        """
        alerts: list[FleetAlert] = []

        # Speed over limit
        if ping.speed_kmh > self.max_speed_kmh:
            alert = self._make_alert(
                truck_id=ping.truck_id,
                alert_type=AlertType.SPEED_ANOMALY,
                severity=AlertSeverity.HIGH,
                details=(
                    f"Speed {ping.speed_kmh} km/h exceeds limit "
                    f"{self.max_speed_kmh} km/h"
                ),
                timestamp=ping.timestamp,
            )
            if alert:
                alerts.append(alert)

        # Stopped with engine running
        if ping.speed_kmh == 0.0 and ping.engine_on:
            alert = self._make_alert(
                truck_id=ping.truck_id,
                alert_type=AlertType.SPEED_ANOMALY,
                severity=AlertSeverity.MEDIUM,
                details="Truck stationary with engine running",
                timestamp=ping.timestamp,
            )
            if alert:
                alerts.append(alert)

        return alerts

    # ── Private: threshold ───────────────────────────────────────────────

    def _check_threshold(self, reading: TemperatureReading) -> bool:
        """Check if temperature exceeds setpoint +/- margin."""
        upper = reading.setpoint_celsius + self.threshold_margin
        lower = reading.setpoint_celsius - self.threshold_margin
        return reading.temp_celsius > upper or reading.temp_celsius < lower

    def _threshold_details(self, reading: TemperatureReading, stale: bool) -> str:
        upper = reading.setpoint_celsius + self.threshold_margin
        base = (
            f"Temperature {reading.temp_celsius}C exceeds threshold "
            f"{upper}C (setpoint {reading.setpoint_celsius}C + margin {self.threshold_margin}C)"
        )
        if stale:
            base += " [STALE DATA WARNING: sensor reading is older than expected]"
        return base

    # ── Private: drift (rate-of-change) ──────────────────────────────────

    def _check_drift(self, reading: TemperatureReading) -> FleetAlert | None:
        """Detect gradual temperature increase over time.

        Compares current reading to the oldest reading within a 30-minute window.
        If the rate of change exceeds drift_rate_threshold, fires a drift alert.
        """
        history = self._temp_history[reading.truck_id]
        if len(history) < 2:
            return None

        # Find readings within the last 30 minutes
        cutoff = reading.timestamp - __import__("datetime").timedelta(minutes=30)
        window = [(ts, temp) for ts, temp in history if ts >= cutoff]

        if len(window) < 2:
            return None

        oldest_ts, oldest_temp = window[0]
        newest_ts, newest_temp = window[-1]

        elapsed_minutes = (newest_ts - oldest_ts).total_seconds() / 60.0
        if elapsed_minutes < 1.0:
            return None

        # Normalize to rate per 30 minutes
        rate_per_30min = abs(newest_temp - oldest_temp) * (30.0 / elapsed_minutes)

        if rate_per_30min > self.drift_rate_threshold:
            direction = "rising" if newest_temp > oldest_temp else "falling"
            return self._make_temp_alert(
                truck_id=reading.truck_id,
                alert_type=AlertType.TEMPERATURE_DRIFT,
                severity=AlertSeverity.HIGH,
                details=(
                    f"Temperature {direction}: {oldest_temp}C -> {newest_temp}C "
                    f"over {elapsed_minutes:.0f} min "
                    f"(rate: {rate_per_30min:.1f}C/30min, "
                    f"threshold: {self.drift_rate_threshold}C/30min)"
                ),
                timestamp=reading.timestamp,
            )

        return None

    # ── Private: z-score ─────────────────────────────────────────────────

    def _check_zscore(
        self, reading: TemperatureReading, stale: bool
    ) -> FleetAlert | None:
        """Statistical outlier detection using z-score on rolling window."""
        history = self._temp_history[reading.truck_id]
        if len(history) < _MIN_ZSCORE_READINGS:
            return None

        # Use all but the current reading for baseline
        temps = [temp for _, temp in history[:-1]]
        mean = sum(temps) / len(temps)
        variance = sum((t - mean) ** 2 for t in temps) / len(temps)
        std = math.sqrt(variance) if variance > 0 else 0.0

        if std == 0:
            return None

        zscore = abs(reading.temp_celsius - mean) / std

        if zscore > self.zscore_threshold:
            details = (
                f"Statistical anomaly: temp {reading.temp_celsius}C, "
                f"z-score {zscore:.1f} (mean {mean:.1f}C, std {std:.2f}C)"
            )
            if stale:
                details += " [STALE DATA WARNING]"
            return self._make_temp_alert(
                truck_id=reading.truck_id,
                alert_type=AlertType.TEMPERATURE_SPIKE,
                severity=AlertSeverity.HIGH,
                details=details,
                timestamp=reading.timestamp,
            )

        return None

    # ── Private: history management ──────────────────────────────────────

    def _record_temp(
        self, truck_id: str, timestamp: datetime, temp_celsius: float
    ) -> None:
        """Append reading to per-truck history, with size cap."""
        history = self._temp_history[truck_id]
        history.append((timestamp, temp_celsius))
        if len(history) > _MAX_HISTORY_SIZE:
            self._temp_history[truck_id] = history[-_MAX_HISTORY_SIZE:]

    # ── Private: staleness ───────────────────────────────────────────────

    def _is_stale(self, timestamp: datetime) -> bool:
        """Check if a reading timestamp is too old."""
        age = (datetime.now(UTC) - timestamp).total_seconds()
        return age > self.staleness_threshold_seconds

    # ── Private: alert creation + dedup ──────────────────────────────────

    def _make_temp_alert(
        self,
        truck_id: str,
        alert_type: AlertType,
        severity: AlertSeverity,
        details: str,
        timestamp: datetime,
    ) -> FleetAlert | None:
        """Create a temperature alert with deduplication."""
        return self._make_alert(truck_id, alert_type, severity, details, timestamp)

    def _make_alert(
        self,
        truck_id: str,
        alert_type: AlertType,
        severity: AlertSeverity,
        details: str,
        timestamp: datetime,
    ) -> FleetAlert | None:
        """Create an alert, suppressing duplicates within the dedup window."""
        dedup_key = (truck_id, alert_type.value)

        if self.dedup_window_seconds > 0 and dedup_key in self._last_alert:
            elapsed = (timestamp - self._last_alert[dedup_key]).total_seconds()
            if elapsed < self.dedup_window_seconds:
                logger.debug(
                    "Suppressed duplicate alert: %s %s (%.0fs since last)",
                    truck_id,
                    alert_type.value,
                    elapsed,
                )
                return None

        self._last_alert[dedup_key] = timestamp

        return FleetAlert(
            alert_id=f"alert-{uuid.uuid4().hex[:12]}",
            truck_id=truck_id,
            alert_type=alert_type,
            severity=severity,
            details=details,
            timestamp=timestamp,
        )
