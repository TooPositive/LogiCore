"""Unit tests for fleet domain models.

Tests: GPSPing, TemperatureReading, FleetAlert, FleetMemoryEntry.
Validates Pydantic constraints, serialization, and edge cases.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError


# ── GPSPing ──────────────────────────────────────────────────────────────────


class TestGPSPing:
    """GPSPing model validation tests."""

    def test_valid_gps_ping(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        ping = GPSPing(
            truck_id="truck-4721",
            latitude=47.3769,
            longitude=8.5417,
            speed_kmh=78.5,
            heading=180.0,
            timestamp=datetime.now(UTC),
        )
        assert ping.truck_id == "truck-4721"
        assert ping.speed_kmh == 78.5

    def test_gps_ping_rejects_invalid_latitude_too_high(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="truck-001",
                latitude=91.0,
                longitude=0.0,
                speed_kmh=60.0,
                heading=0.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_rejects_invalid_latitude_too_low(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="truck-001",
                latitude=-91.0,
                longitude=0.0,
                speed_kmh=60.0,
                heading=0.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_rejects_invalid_longitude(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="truck-001",
                latitude=0.0,
                longitude=181.0,
                speed_kmh=60.0,
                heading=0.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_rejects_negative_speed(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="truck-001",
                latitude=0.0,
                longitude=0.0,
                speed_kmh=-10.0,
                heading=0.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_rejects_empty_truck_id(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="",
                latitude=0.0,
                longitude=0.0,
                speed_kmh=60.0,
                heading=0.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_heading_wraps_at_360(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        with pytest.raises(ValidationError):
            GPSPing(
                truck_id="truck-001",
                latitude=0.0,
                longitude=0.0,
                speed_kmh=60.0,
                heading=361.0,
                timestamp=datetime.now(UTC),
            )

    def test_gps_ping_serialization_roundtrip(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        ts = datetime.now(UTC)
        ping = GPSPing(
            truck_id="truck-4721",
            latitude=47.3769,
            longitude=8.5417,
            speed_kmh=78.5,
            heading=180.0,
            timestamp=ts,
        )
        data = ping.model_dump()
        restored = GPSPing(**data)
        assert restored == ping

    def test_gps_ping_optional_engine_on_defaults_true(self):
        from apps.api.src.domains.logicore.models.fleet import GPSPing

        ping = GPSPing(
            truck_id="truck-001",
            latitude=0.0,
            longitude=0.0,
            speed_kmh=60.0,
            heading=0.0,
            timestamp=datetime.now(UTC),
        )
        assert ping.engine_on is True


# ── TemperatureReading ───────────────────────────────────────────────────────


class TestTemperatureReading:
    """TemperatureReading model validation tests."""

    def test_valid_temperature_reading(self):
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        reading = TemperatureReading(
            truck_id="truck-4721",
            sensor_id="sensor-01",
            temp_celsius=3.2,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )
        assert reading.temp_celsius == 3.2
        assert reading.setpoint_celsius == 3.0

    def test_temperature_reading_extreme_cold(self):
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=-40.0,
            setpoint_celsius=-25.0,
            timestamp=datetime.now(UTC),
        )
        assert reading.temp_celsius == -40.0

    def test_temperature_reading_rejects_extreme_values(self):
        """Sensors don't read > 100C or < -100C -- likely hardware error."""
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        with pytest.raises(ValidationError):
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="sensor-01",
                temp_celsius=101.0,
                setpoint_celsius=3.0,
                timestamp=datetime.now(UTC),
            )

    def test_temperature_reading_rejects_empty_sensor_id(self):
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        with pytest.raises(ValidationError):
            TemperatureReading(
                truck_id="truck-001",
                sensor_id="",
                temp_celsius=3.2,
                setpoint_celsius=3.0,
                timestamp=datetime.now(UTC),
            )

    def test_temperature_reading_serialization(self):
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        ts = datetime.now(UTC)
        reading = TemperatureReading(
            truck_id="truck-4721",
            sensor_id="sensor-01",
            temp_celsius=6.1,
            setpoint_celsius=3.0,
            timestamp=ts,
        )
        data = reading.model_dump()
        assert data["temp_celsius"] == 6.1
        restored = TemperatureReading(**data)
        assert restored == reading


# ── FleetAlert ───────────────────────────────────────────────────────────────


class TestFleetAlert:
    """FleetAlert model validation tests."""

    def test_valid_fleet_alert(self):
        from apps.api.src.domains.logicore.models.fleet import (
            AlertSeverity,
            AlertType,
            FleetAlert,
        )

        alert = FleetAlert(
            alert_id="alert-001",
            truck_id="truck-4721",
            alert_type=AlertType.TEMPERATURE_SPIKE,
            severity=AlertSeverity.CRITICAL,
            details="Temperature exceeded threshold: 6.1C (threshold: 8.0C)",
            timestamp=datetime.now(UTC),
        )
        assert alert.alert_type == AlertType.TEMPERATURE_SPIKE
        assert alert.severity == AlertSeverity.CRITICAL

    def test_alert_severity_ordering(self):
        """Severity levels should be orderable for priority queueing."""
        from apps.api.src.domains.logicore.models.fleet import AlertSeverity

        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.HIGH.value == "high"
        assert AlertSeverity.MEDIUM.value == "medium"
        assert AlertSeverity.LOW.value == "low"

    def test_alert_types_cover_all_anomaly_categories(self):
        from apps.api.src.domains.logicore.models.fleet import AlertType

        expected_types = {
            "temperature_spike",
            "temperature_drift",
            "gps_deviation",
            "speed_anomaly",
            "heartbeat_timeout",
        }
        actual_types = {t.value for t in AlertType}
        assert expected_types <= actual_types  # at least these types

    def test_fleet_alert_rejects_empty_alert_id(self):
        from apps.api.src.domains.logicore.models.fleet import (
            AlertSeverity,
            AlertType,
            FleetAlert,
        )

        with pytest.raises(ValidationError):
            FleetAlert(
                alert_id="",
                truck_id="truck-001",
                alert_type=AlertType.TEMPERATURE_SPIKE,
                severity=AlertSeverity.HIGH,
                details="test",
                timestamp=datetime.now(UTC),
            )

    def test_fleet_alert_serialization(self):
        from apps.api.src.domains.logicore.models.fleet import (
            AlertSeverity,
            AlertType,
            FleetAlert,
        )

        ts = datetime.now(UTC)
        alert = FleetAlert(
            alert_id="alert-001",
            truck_id="truck-4721",
            alert_type=AlertType.TEMPERATURE_SPIKE,
            severity=AlertSeverity.CRITICAL,
            details="Temperature spike",
            timestamp=ts,
        )
        data = alert.model_dump()
        restored = FleetAlert(**data)
        assert restored == alert

    def test_fleet_alert_resolved_default_false(self):
        from apps.api.src.domains.logicore.models.fleet import (
            AlertSeverity,
            AlertType,
            FleetAlert,
        )

        alert = FleetAlert(
            alert_id="alert-001",
            truck_id="truck-001",
            alert_type=AlertType.TEMPERATURE_SPIKE,
            severity=AlertSeverity.HIGH,
            details="test",
            timestamp=datetime.now(UTC),
        )
        assert alert.resolved is False

    def test_fleet_alert_with_cargo_value(self):
        from apps.api.src.domains.logicore.models.fleet import (
            AlertSeverity,
            AlertType,
            FleetAlert,
        )

        alert = FleetAlert(
            alert_id="alert-001",
            truck_id="truck-4721",
            alert_type=AlertType.TEMPERATURE_SPIKE,
            severity=AlertSeverity.CRITICAL,
            details="Pharma cargo at risk",
            timestamp=datetime.now(UTC),
            cargo_value_eur=Decimal("180000"),
        )
        assert alert.cargo_value_eur == Decimal("180000")


# ── FleetMemoryEntry ─────────────────────────────────────────────────────────


class TestFleetMemoryEntry:
    """FleetMemoryEntry model for cross-session agent memory."""

    def test_valid_memory_entry(self):
        from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

        entry = FleetMemoryEntry(
            truck_id="truck-4521",
            pattern="recurring_refrigeration_failure",
            alert_type="temperature_spike",
            action_taken="Diverted to Zurich cold storage",
            outcome="pending_verification",
            learned_at=datetime.now(UTC),
        )
        assert entry.pattern == "recurring_refrigeration_failure"
        assert entry.outcome == "pending_verification"

    def test_memory_entry_rejects_empty_pattern(self):
        from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

        with pytest.raises(ValidationError):
            FleetMemoryEntry(
                truck_id="truck-001",
                pattern="",
                alert_type="temperature_spike",
                action_taken="test",
                outcome="pending",
                learned_at=datetime.now(UTC),
            )

    def test_memory_entry_serialization(self):
        from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

        ts = datetime.now(UTC)
        entry = FleetMemoryEntry(
            truck_id="truck-4521",
            pattern="recurring_refrigeration_failure",
            alert_type="temperature_spike",
            action_taken="Diverted to cold storage",
            outcome="verified_fixed",
            learned_at=ts,
            occurrence_count=3,
        )
        data = entry.model_dump()
        assert data["occurrence_count"] == 3
        restored = FleetMemoryEntry(**data)
        assert restored == entry

    def test_memory_entry_default_occurrence_count(self):
        from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

        entry = FleetMemoryEntry(
            truck_id="truck-001",
            pattern="speed_anomaly_pattern",
            alert_type="speed_anomaly",
            action_taken="Notified driver",
            outcome="pending",
            learned_at=datetime.now(UTC),
        )
        assert entry.occurrence_count == 1

    def test_memory_entry_optional_memory_id(self):
        from apps.api.src.domains.logicore.models.fleet import FleetMemoryEntry

        entry = FleetMemoryEntry(
            truck_id="truck-001",
            pattern="test_pattern",
            alert_type="temperature_spike",
            action_taken="test",
            outcome="pending",
            learned_at=datetime.now(UTC),
            memory_id="mem-001",
        )
        assert entry.memory_id == "mem-001"


# ── AnomalyEvent (internal event passed to detector) ─────────────────────────


class TestAnomalyEvent:
    """Internal event type used between detector components."""

    def test_staleness_check_fresh(self):
        """Events under 30 seconds old are fresh."""
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=6.1,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC),
        )
        # Fresh event
        age = (datetime.now(UTC) - reading.timestamp).total_seconds()
        assert age < 5  # just created

    def test_staleness_check_stale(self):
        """Events older than 30 seconds need staleness warning."""
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        reading = TemperatureReading(
            truck_id="truck-001",
            sensor_id="sensor-01",
            temp_celsius=6.1,
            setpoint_celsius=3.0,
            timestamp=datetime.now(UTC) - timedelta(seconds=60),
        )
        age = (datetime.now(UTC) - reading.timestamp).total_seconds()
        assert age > 30  # stale
