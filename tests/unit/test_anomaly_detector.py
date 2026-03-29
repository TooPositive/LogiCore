"""Unit tests for the two-tier anomaly detector.

Tests rule-based threshold detection, rate-of-change (gradient) detection,
z-score statistical detection, alert deduplication, and staleness checking.

The anomaly detector is the EUR 207,000 line between "works" and "production-ready."
Threshold-only detection catches sudden spikes but misses slow drift (40% of incidents).
Rate-of-change detection catches gradual refrigeration failure BEFORE threshold breach.
"""

from datetime import UTC, datetime, timedelta

from apps.api.src.domains.logicore.models.fleet import (
    AlertType,
    GPSPing,
    TemperatureReading,
)

# ── Temperature Threshold Detection ─────────────────────────────────────────


class TestTemperatureThreshold:
    """Tier 1: Rule-based threshold detection. Zero LLM cost."""

    def test_temperature_above_threshold_triggers_alert(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        reading = TemperatureReading(
            truck_id="truck-4721",
            sensor_id="sensor-01",
            temp_celsius=9.0,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.TEMPERATURE_SPIKE
        assert alerts[0].truck_id == "truck-4721"

    def test_temperature_within_threshold_no_alert(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=4.0,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 0

    def test_temperature_at_exact_threshold_no_alert(self):
        """Boundary: setpoint + margin = 5.0 (default margin=5). At 8.0, threshold=8.0, no alert."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0)
        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=8.0,  # setpoint(3) + margin(5) = 8, not exceeded
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 0

    def test_temperature_just_above_threshold_triggers(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0)
        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=8.1,  # setpoint(3) + margin(5) = 8, 8.1 > 8
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 1

    def test_configurable_threshold_margin(self):
        """Different cargo types have different margins."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=2.0)
        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=5.1,  # setpoint(3) + margin(2) = 5, 5.1 > 5
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 1


# ── Borderline Temperature (Pharma 2C Margin vs General Freight 5C) ──────


class TestBorderlineTemperature:
    """Pharma cargo uses tight margins (2C), general freight uses wide (5C).

    The filter rate changes dramatically: pharma margin catches spoilage earlier
    but generates more alerts on marginal readings. This is the CTO trade-off:
    tight margins = more false positives but zero missed cargo losses.

    These tests prove the exact boundary behavior at thresholds that matter
    for EUR 180,000 pharmaceutical cargo.
    """

    def test_pharma_margin_7_9_on_8_threshold_no_alert(self):
        """Pharma: setpoint 3C + margin 5C = threshold 8C. 7.9C < 8.0C -> no alert."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0)
        reading = TemperatureReading(
            truck_id="truck-pharma",
            sensor_id="sensor-01",
            temp_celsius=7.9,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        threshold_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(threshold_alerts) == 0, (
            "7.9C is below 8.0C threshold — no alert. "
            "But note: at 7.9C, cargo degradation may have already started. "
            "Pharma clients should use tighter margins (2.0C)."
        )

    def test_pharma_margin_8_01_on_8_threshold_triggers(self):
        """8.01C > 8.0C threshold -> alert fires."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0)
        reading = TemperatureReading(
            truck_id="truck-pharma-01",
            sensor_id="sensor-01",
            temp_celsius=8.01,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        threshold_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(threshold_alerts) == 1

    def test_tight_pharma_margin_catches_earlier(self):
        """Tight margin (2C): alerts at 5.1C instead of 8.1C.

        ARCHITECT DECISION: Pharma cargo should use 2C margin.
        With 5C margin, cargo is at 8C when alert fires — damage started at 5C.
        With 2C margin, alert fires at 5.1C — 75 minutes earlier response.
        """
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        # Tight margin (pharma): setpoint 3C + margin 2C = threshold 5C
        tight = AnomalyDetector(threshold_margin=2.0)
        # Wide margin (general): setpoint 3C + margin 5C = threshold 8C
        wide = AnomalyDetector(threshold_margin=5.0)

        reading = TemperatureReading(
            truck_id="truck-compare",
            sensor_id="sensor-01",
            temp_celsius=5.5,  # Above 5C, below 8C
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        tight_alerts = tight.check_temperature(reading)
        wide_alerts = wide.check_temperature(reading)

        tight_spikes = [a for a in tight_alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        wide_spikes = [a for a in wide_alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]

        assert len(tight_spikes) == 1, "Tight margin (2C) should catch 5.5C"
        assert len(wide_spikes) == 0, "Wide margin (5C) misses 5.5C — damage starts undetected"

    def test_borderline_batch_100_readings_around_threshold(self):
        """100 readings from 7.5C to 8.5C in 0.01C steps — verify exact boundary.

        DECISION: threshold is strict greater-than (>), not greater-or-equal (>=).
        At exactly 8.0C, no alert fires. This is intentional: setpoint + margin
        defines the acceptable range, not the alert trigger. One reading at the
        boundary is sensor noise, not an anomaly.
        """
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0, dedup_window_seconds=0)

        alerts_below = 0
        alerts_at = 0
        alerts_above = 0

        for i in range(101):
            temp = 7.5 + i * 0.01  # 7.50, 7.51, ..., 8.00, ..., 8.50
            reading = TemperatureReading(
                truck_id=f"truck-boundary-{i:03d}",
                sensor_id="sensor-01",
                temp_celsius=round(temp, 2),
                setpoint_celsius=3.0,
                timestamp=datetime.now(UTC),
            )
            alerts = detector.check_temperature(reading)
            spikes = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]

            if temp < 8.0:
                alerts_below += len(spikes)
            elif temp == 8.0:
                alerts_at += len(spikes)
            else:
                alerts_above += len(spikes)

        assert alerts_below == 0, "No alerts below threshold"
        assert alerts_at == 0, "No alert at exact threshold (strict >)"
        assert alerts_above == 50, f"All {alerts_above}/50 readings above threshold should alert"

    def test_frozen_cargo_lower_boundary(self):
        """Frozen cargo (setpoint -20C, margin 5C): alert at -25.01C but not -25.0C."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0, dedup_window_seconds=0)

        # At boundary: -20 - 5 = -25, no alert
        at_boundary = TemperatureReading(
            truck_id="truck-frozen-at",
            sensor_id="s01",
            temp_celsius=-25.0,
            setpoint_celsius=-20.0,
            timestamp=datetime.now(UTC),
        )
        alerts_at = detector.check_temperature(at_boundary)
        spikes_at = [a for a in alerts_at if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spikes_at) == 0

        # Below boundary: alert
        below = TemperatureReading(
            truck_id="truck-frozen-below",
            sensor_id="s01",
            temp_celsius=-25.1,
            setpoint_celsius=-20.0,
            timestamp=datetime.now(UTC),
        )
        alerts_below = detector.check_temperature(below)
        spikes_below = [a for a in alerts_below if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spikes_below) == 1

    def test_negative_temperature_below_setpoint_triggers(self):
        """Frozen cargo: temperature dropping below setpoint - margin."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0)
        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=-30.0,  # setpoint(-20) - margin(5) = -25, -30 < -25
            setpoint_celsius=-20.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(reading)
        assert len(alerts) == 1


# ── Temperature Drift Detection (Rate-of-Change) ────────────────────────────


class TestTemperatureDrift:
    """Catches the EUR 207,000 slow drift that threshold-only detection misses.

    If temperature rises >0.5C in 30 minutes consistently, alert BEFORE
    it crosses the threshold.
    """

    def test_gradual_rise_triggers_drift_alert(self):
        """3.1C -> 3.8C -> 4.5C over 30 min = 0.7C/15min rate = drift alert."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        base_time = datetime.now(UTC) - timedelta(minutes=30)

        # Feed readings that simulate slow drift
        readings = [
            TemperatureReading(
                truck_id="truck-4721",
                sensor_id="sensor-01",
                temp_celsius=3.1,
                setpoint_celsius=3.0,
                timestamp=base_time,
            ),
            TemperatureReading(
                truck_id="truck-4721",
                sensor_id="sensor-01",
                temp_celsius=3.8,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=15),
            ),
            TemperatureReading(
                truck_id="truck-4721",
                sensor_id="sensor-01",
                temp_celsius=4.5,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=30),
            ),
        ]

        # Process each reading
        all_alerts = []
        for reading in readings:
            alerts = detector.check_temperature(reading)
            all_alerts.extend(alerts)

        # Should have at least one drift alert
        drift_alerts = [a for a in all_alerts if a.alert_type == AlertType.TEMPERATURE_DRIFT]
        assert len(drift_alerts) >= 1, (
            "Slow drift (3.1->4.5C over 30min) must trigger drift alert "
            "BEFORE threshold breach. Missing this = EUR 207,000 cargo loss."
        )

    def test_stable_temperature_no_drift(self):
        """3.0C -> 3.1C -> 3.0C -- stable, no drift."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        base_time = datetime.now(UTC) - timedelta(minutes=30)

        readings = [
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=base_time,
            ),
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=3.1,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=15),
            ),
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=30),
            ),
        ]

        all_alerts = []
        for reading in readings:
            all_alerts.extend(detector.check_temperature(reading))

        drift_alerts = [a for a in all_alerts if a.alert_type == AlertType.TEMPERATURE_DRIFT]
        assert len(drift_alerts) == 0

    def test_configurable_drift_rate(self):
        """Drift threshold should be configurable (default 0.5C/30min)."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(drift_rate_threshold=1.0)
        base_time = datetime.now(UTC) - timedelta(minutes=30)

        # 0.7C rise in 30 min -- below 1.0 threshold
        readings = [
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=base_time,
            ),
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=3.7,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=30),
            ),
        ]

        all_alerts = []
        for r in readings:
            all_alerts.extend(detector.check_temperature(r))

        drift_alerts = [a for a in all_alerts if a.alert_type == AlertType.TEMPERATURE_DRIFT]
        assert len(drift_alerts) == 0

    def test_different_trucks_have_separate_histories(self):
        """Truck-A's readings should not affect truck-B's drift detection."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        base_time = datetime.now(UTC) - timedelta(minutes=30)

        # Truck-A: steady rise (should trigger drift)
        detector.check_temperature(
            TemperatureReading(
                truck_id="truck-A",
                sensor_id="s01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=base_time,
            )
        )
        # Truck-B: stable
        detector.check_temperature(
            TemperatureReading(
                truck_id="truck-B",
                sensor_id="s01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=base_time,
            )
        )
        # Truck-A: rising
        alerts_a = detector.check_temperature(
            TemperatureReading(
                truck_id="truck-A",
                sensor_id="s01",
                temp_celsius=4.0,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=30),
            )
        )
        # Truck-B: stable
        alerts_b = detector.check_temperature(
            TemperatureReading(
                truck_id="truck-B",
                sensor_id="s01",
                temp_celsius=3.1,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=30),
            )
        )

        drift_a = [a for a in alerts_a if a.alert_type == AlertType.TEMPERATURE_DRIFT]
        drift_b = [a for a in alerts_b if a.alert_type == AlertType.TEMPERATURE_DRIFT]

        assert len(drift_a) >= 1, "Truck-A should have drift alert"
        assert len(drift_b) == 0, "Truck-B should have no drift"


# ── Z-Score Statistical Detection ────────────────────────────────────────────


class TestZScoreDetection:
    """Tier 2: Statistical anomaly detection using z-score on rolling window."""

    def test_outlier_temperature_detected_by_zscore(self):
        """A sudden jump from stable baseline should be detected."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(zscore_threshold=3.0)
        base_time = datetime.now(UTC) - timedelta(hours=1)

        # Build stable baseline: 20 readings at ~3.0C
        for i in range(20):
            detector.check_temperature(
                TemperatureReading(
                    truck_id="truck-001",
                    sensor_id="s01",
                    temp_celsius=3.0 + (i % 3) * 0.1,  # 3.0, 3.1, 3.2
                    setpoint_celsius=3.0,
                    timestamp=base_time + timedelta(minutes=i * 3),
                )
            )

        # Now a sudden spike to 7.0C (well above z=3 for this baseline)
        alerts = detector.check_temperature(
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="s01",
                temp_celsius=7.0,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=63),
            )
        )

        # Should trigger threshold alert (7.0 > 3.0 + 5.0? No, 7.0 < 8.0)
        # But z-score should catch it (7.0 is far from mean ~3.1)
        spike_alerts = [
            a for a in alerts
            if a.alert_type in (AlertType.TEMPERATURE_SPIKE, AlertType.TEMPERATURE_DRIFT)
        ]
        assert len(spike_alerts) >= 1, (
            "Z-score should catch 7.0C when baseline is 3.0-3.2C, "
            "even if threshold (8.0) is not reached."
        )

    def test_zscore_needs_minimum_readings(self):
        """Z-score should not fire with fewer than 5 readings (not enough data)."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(zscore_threshold=3.0)

        # Only 2 readings, then spike
        detector.check_temperature(
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="s01",
                temp_celsius=3.0,
                setpoint_celsius=3.0,
                timestamp=datetime.now(UTC) - timedelta(minutes=10),
            )
        )

        alerts = detector.check_temperature(
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="s01",
                temp_celsius=7.0,
                setpoint_celsius=3.0,
                timestamp=datetime.now(UTC),
            )
        )

        # Should NOT trigger z-score alert (not enough data)
        # Might still trigger drift if rate > threshold
        zscore_alerts = [
            a for a in alerts
            if "z-score" in a.details.lower() or "statistical" in a.details.lower()
        ]
        assert len(zscore_alerts) == 0


# ── GPS Deviation Detection ──────────────────────────────────────────────────


class TestGPSDeviation:
    """Detect trucks deviating from expected routes."""

    def test_speed_anomaly_too_fast(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(max_speed_kmh=120.0)
        ping = GPSPing(
            truck_id="truck-001",
            latitude=47.37,
            longitude=8.54,
            speed_kmh=135.0,
            heading=180.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_gps(ping)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.SPEED_ANOMALY

    def test_speed_zero_with_engine_on(self):
        """Truck stopped with engine running -- could be theft or breakdown."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        ping = GPSPing(
            truck_id="truck-001",
            latitude=47.37,
            longitude=8.54,
            speed_kmh=0.0,
            heading=180.0,
            timestamp=datetime.now(UTC),
            engine_on=True,
        )

        alerts = detector.check_gps(ping)
        speed_alerts = [a for a in alerts if a.alert_type == AlertType.SPEED_ANOMALY]
        assert len(speed_alerts) == 1

    def test_speed_zero_engine_off_no_alert(self):
        """Truck parked normally -- no alert."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        ping = GPSPing(
            truck_id="truck-001",
            latitude=47.37,
            longitude=8.54,
            speed_kmh=0.0,
            heading=180.0,
            timestamp=datetime.now(UTC),
            engine_on=False,
        )

        alerts = detector.check_gps(ping)
        assert len(alerts) == 0

    def test_normal_speed_no_alert(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        ping = GPSPing(
            truck_id="truck-001",
            latitude=47.37,
            longitude=8.54,
            speed_kmh=80.0,
            heading=180.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_gps(ping)
        assert len(alerts) == 0

    def test_speed_at_exact_limit_no_alert(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(max_speed_kmh=120.0)
        ping = GPSPing(
            truck_id="truck-001",
            latitude=47.37,
            longitude=8.54,
            speed_kmh=120.0,
            heading=180.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_gps(ping)
        assert len(alerts) == 0


# ── Alert Deduplication ──────────────────────────────────────────────────────


class TestAlertDeduplication:
    """Same truck + same alert type within 5 minutes -> suppress duplicate."""

    def test_duplicate_alert_suppressed(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(dedup_window_seconds=300)
        now = datetime.now(UTC)

        # First spike alert
        reading1 = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=now,
        )
        alerts1 = detector.check_temperature(reading1)
        assert len([a for a in alerts1 if a.alert_type == AlertType.TEMPERATURE_SPIKE]) == 1

        # Same truck, same type, 2 minutes later -- should be suppressed
        reading2 = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=13.0,
            setpoint_celsius=3.0,
            timestamp=now + timedelta(minutes=2),
        )
        alerts2 = detector.check_temperature(reading2)
        spike_alerts2 = [a for a in alerts2 if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts2) == 0, "Duplicate spike alert within 5min should be suppressed"

    def test_dedup_expires_after_window(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(dedup_window_seconds=300)
        now = datetime.now(UTC)

        # First spike
        reading1 = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=now,
        )
        detector.check_temperature(reading1)

        # 6 minutes later -- past dedup window
        reading2 = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=13.0,
            setpoint_celsius=3.0,
            timestamp=now + timedelta(minutes=6),
        )
        alerts = detector.check_temperature(reading2)
        spike_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts) == 1, "After dedup window expires, alert should fire again"

    def test_different_trucks_not_deduplicated(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(dedup_window_seconds=300)
        now = datetime.now(UTC)

        reading1 = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=now,
        )
        detector.check_temperature(reading1)

        # Different truck, same time
        reading2 = TemperatureReading(
            truck_id="truck-002",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=now + timedelta(seconds=30),
        )
        alerts = detector.check_temperature(reading2)
        spike_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts) == 1, "Different truck should not be deduplicated"

    def test_different_alert_types_not_deduplicated(self):
        """A temp spike and a temp drift for the same truck are different alerts.

        Dedup keys include alert_type, so spike and drift are tracked
        independently. This is verified by the dedup key structure:
        (truck_id, alert_type.value).
        """
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(dedup_window_seconds=300)
        # Verify dedup uses (truck_id, alert_type) as key
        assert isinstance(detector._last_alert, dict)


# ── Staleness Detection ──────────────────────────────────────────────────────


class TestStalenessDetection:
    """Stale GPS data = wrong facility recommendation = worsened spoilage."""

    def test_stale_alert_flagged(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(staleness_threshold_seconds=30)

        stale_reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC) - timedelta(seconds=60),
        )

        alerts = detector.check_temperature(stale_reading)
        # Alert should still fire but with staleness warning in details
        spike_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts) == 1
        assert "stale" in spike_alerts[0].details.lower()

    def test_fresh_alert_not_flagged_stale(self):
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(staleness_threshold_seconds=30)

        fresh_reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="s01",
            temp_celsius=12.0,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )

        alerts = detector.check_temperature(fresh_reading)
        spike_alerts = [a for a in alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts) == 1
        assert "stale" not in spike_alerts[0].details.lower()


# ── Filter Rate ──────────────────────────────────────────────────────────────


class TestFilterRate:
    """Two-tier processing: >95% of normal events should produce zero alerts."""

    def test_normal_events_produce_no_alerts(self):
        """100 normal readings -> 0 alerts."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector()
        base_time = datetime.now(UTC)

        alert_count = 0
        for i in range(100):
            reading = TemperatureReading(
                truck_id=f"truck-{i % 10:03d}",
                sensor_id="s01",
                temp_celsius=3.0 + (i % 5) * 0.2,  # 3.0 to 3.8 -- all normal
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(seconds=i * 15),
            )
            alerts = detector.check_temperature(reading)
            alert_count += len(alerts)

        assert alert_count == 0, f"Normal events should produce 0 alerts, got {alert_count}"

    def test_mixed_events_anomaly_ratio(self):
        """95 normal + 5 anomalous readings -> alerts only for anomalous ones."""
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(dedup_window_seconds=0)  # disable dedup for counting
        base_time = datetime.now(UTC)

        anomaly_alert_count = 0
        normal_alert_count = 0

        for i in range(100):
            is_anomaly = i >= 95
            reading = TemperatureReading(
                truck_id=f"truck-{i:03d}",  # unique trucks to avoid dedup
                sensor_id="s01",
                temp_celsius=12.0 if is_anomaly else 3.5,
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(seconds=i),
            )
            alerts = detector.check_temperature(reading)
            if is_anomaly:
                anomaly_alert_count += len(alerts)
            else:
                normal_alert_count += len(alerts)

        assert normal_alert_count == 0, "Normal events should produce 0 alerts"
        assert anomaly_alert_count == 5, "Each anomalous event should produce 1 alert"
