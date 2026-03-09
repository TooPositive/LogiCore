"""Unit tests for the telemetry simulator.

Tests: event generation, anomaly injection, GPS interpolation,
temperature drift simulation, and event ordering.
"""

from datetime import UTC, datetime


class TestTelemetrySimulator:
    """Tests for the in-memory telemetry simulator."""

    def test_load_from_routes_file(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        assert len(sim.routes) >= 5
        assert len(sim.cold_storage) >= 3

    def test_generates_events_for_all_trucks(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=10)

        truck_ids = {e["truck_id"] for e in events}
        assert len(truck_ids) >= 4  # at least 4 trucks have events

    def test_events_sorted_by_timestamp(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=10)

        timestamps = [e["timestamp"] for e in events]
        assert timestamps == sorted(timestamps)

    def test_gps_events_have_required_fields(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=5)

        gps_events = [e for e in events if e["event_type"] == "gps_ping"]
        assert len(gps_events) > 0

        for event in gps_events[:5]:
            assert "truck_id" in event
            assert "latitude" in event
            assert "longitude" in event
            assert "speed_kmh" in event
            assert "heading" in event
            assert "timestamp" in event
            assert event["topic"] == "fleet.gps-pings"

    def test_temperature_events_have_required_fields(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=5)

        temp_events = [e for e in events if e["event_type"] == "temperature_reading"]
        assert len(temp_events) > 0

        for event in temp_events[:5]:
            assert "truck_id" in event
            assert "sensor_id" in event
            assert "temp_celsius" in event
            assert "setpoint_celsius" in event
            assert "timestamp" in event
            assert event["topic"] == "fleet.temperature"

    def test_non_refrigerated_trucks_have_no_temperature_events(self):
        """Trucks without temp_setpoint should not generate temp events."""
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=10)

        # truck-1234 is electronics (no temp monitoring)
        truck_1234_temp = [
            e for e in events
            if e["truck_id"] == "truck-1234" and e["event_type"] == "temperature_reading"
        ]
        assert len(truck_1234_temp) == 0

    def test_gps_positions_progress_along_route(self):
        """GPS coordinates should change over time (truck is moving)."""
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=30)

        truck_gps = [
            e for e in events
            if e["truck_id"] == "truck-4721" and e["event_type"] == "gps_ping"
        ]
        assert len(truck_gps) > 5

        first = truck_gps[0]
        last = truck_gps[-1]

        # Positions should differ (truck moved)
        assert (
            abs(first["latitude"] - last["latitude"]) > 0.01
            or abs(first["longitude"] - last["longitude"]) > 0.01
        )

    def test_event_volume_scales_with_duration(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )

        events_10 = sim.generate_events(duration_minutes=10)
        events_30 = sim.generate_events(duration_minutes=30)

        # 3x duration should produce roughly 3x events
        ratio = len(events_30) / len(events_10)
        assert 2.5 < ratio < 3.5

    def test_custom_intervals(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator(
            routes=[{
                "truck_id": "truck-test",
                "cargo": "general",
                "cargo_value_eur": 1000,
                "temp_setpoint_celsius": None,
                "route": {
                    "origin": {"city": "A", "lat": 50.0, "lng": 10.0},
                    "destination": {"city": "B", "lat": 51.0, "lng": 11.0},
                    "waypoints": [],
                },
                "anomalies": [],
            }],
            gps_interval_seconds=5,
        )

        events = sim.generate_events(duration_minutes=1)
        gps_events = [e for e in events if e["event_type"] == "gps_ping"]
        # 60 seconds / 5 second interval = 12 events
        assert len(gps_events) == 12

    def test_start_time_is_configurable(self):
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )

        custom_start = datetime(2026, 3, 9, 3, 0, 0, tzinfo=UTC)
        events = sim.generate_events(
            duration_minutes=5, start_time=custom_start
        )

        first_ts = events[0]["timestamp"]
        assert first_ts.startswith("2026-03-09T03:00:00")
