"""Telemetry simulator for fleet guardian testing.

Generates mock GPS pings and temperature readings for trucks,
with configurable anomaly injection. Can publish to Kafka or
run in-memory for testing.

Usage:
    # In-memory (for unit tests):
    sim = TelemetrySimulator.from_routes_file("data/mock-telemetry/routes.json")
    events = sim.generate_events(duration_minutes=60)

    # Kafka (for integration tests):
    python scripts/telemetry_simulator.py --bootstrap-servers localhost:9092
"""

import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class TelemetrySimulator:
    """Generates mock telemetry events for fleet testing.

    Args:
        routes: List of route definitions with truck IDs and anomaly configs.
        gps_interval_seconds: How often to generate GPS pings.
        temp_interval_seconds: How often to generate temperature readings.
    """

    def __init__(
        self,
        routes: list[dict[str, Any]],
        cold_storage: list[dict[str, Any]] | None = None,
        gps_interval_seconds: int = 15,
        temp_interval_seconds: int = 60,
    ) -> None:
        self.routes = routes
        self.cold_storage = cold_storage or []
        self.gps_interval = gps_interval_seconds
        self.temp_interval = temp_interval_seconds

    @classmethod
    def from_routes_file(cls, path: str) -> "TelemetrySimulator":
        """Create simulator from a routes JSON file."""
        data = json.loads(Path(path).read_text())
        return cls(
            routes=data["routes"],
            cold_storage=data.get("cold_storage_facilities", []),
        )

    def generate_events(
        self,
        duration_minutes: int = 60,
        start_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Generate telemetry events for all trucks over a time period.

        Returns list of events sorted by timestamp, each tagged with
        'event_type' (gps_ping or temperature_reading) and 'topic'.
        """
        start = start_time or datetime.now(UTC)
        events: list[dict[str, Any]] = []

        for route in self.routes:
            events.extend(
                self._generate_truck_events(route, start, duration_minutes)
            )

        events.sort(key=lambda e: e["timestamp"])
        return events

    def _generate_truck_events(
        self,
        route: dict[str, Any],
        start: datetime,
        duration_minutes: int,
    ) -> list[dict[str, Any]]:
        """Generate events for a single truck."""
        events: list[dict[str, Any]] = []
        truck_id = route["truck_id"]
        waypoints = self._get_all_points(route)
        anomalies = route.get("anomalies", [])

        total_seconds = duration_minutes * 60

        # GPS pings
        for sec in range(0, total_seconds, self.gps_interval):
            ts = start + timedelta(seconds=sec)
            progress = sec / total_seconds
            pos = self._interpolate_position(waypoints, progress)

            speed = 75.0 + random.uniform(-10, 10)

            # Check for speed anomalies
            for anomaly in anomalies:
                if anomaly.get("type") == "speed_anomaly":
                    wp_idx = anomaly.get("waypoint_index", 0)
                    if self._near_waypoint(progress, wp_idx, len(waypoints)):
                        speed = anomaly["speed_kmh"]

            events.append({
                "event_type": "gps_ping",
                "topic": "fleet.gps-pings",
                "truck_id": truck_id,
                "latitude": pos[0],
                "longitude": pos[1],
                "speed_kmh": round(speed, 1),
                "heading": random.uniform(0, 360),
                "engine_on": True,
                "timestamp": ts.isoformat(),
            })

        # Temperature readings (only for refrigerated trucks)
        setpoint = route.get("temp_setpoint_celsius")
        if setpoint is not None:
            for sec in range(0, total_seconds, self.temp_interval):
                ts = start + timedelta(seconds=sec)
                progress = sec / total_seconds

                temp = setpoint + random.uniform(-0.3, 0.3)

                # Apply temperature anomalies
                for anomaly in anomalies:
                    if anomaly.get("type") == "temperature_drift":
                        wp_idx = anomaly.get("waypoint_index", 0)
                        if self._near_waypoint(progress, wp_idx, len(waypoints)):
                            drift_progress = self._anomaly_progress(
                                progress, wp_idx, len(waypoints)
                            )
                            rate = anomaly.get("temp_rise_rate_per_30min", 0.8)
                            temp += rate * drift_progress * 2

                    elif anomaly.get("type") == "temperature_spike":
                        wp_idx = anomaly.get("waypoint_index", 0)
                        if self._near_waypoint(progress, wp_idx, len(waypoints)):
                            temp = anomaly["temp_spike_celsius"]

                events.append({
                    "event_type": "temperature_reading",
                    "topic": "fleet.temperature",
                    "truck_id": truck_id,
                    "sensor_id": f"sensor-{truck_id[-4:]}",
                    "temp_celsius": round(temp, 1),
                    "setpoint_celsius": setpoint,
                    "timestamp": ts.isoformat(),
                })

        return events

    def _get_all_points(
        self, route: dict[str, Any]
    ) -> list[tuple[float, float]]:
        """Get all route points (origin + waypoints + destination)."""
        points = []
        r = route.get("route", {})
        if "origin" in r:
            points.append((r["origin"]["lat"], r["origin"]["lng"]))
        for wp in r.get("waypoints", []):
            points.append((wp["lat"], wp["lng"]))
        if "destination" in r:
            points.append((r["destination"]["lat"], r["destination"]["lng"]))
        return points if points else [(0.0, 0.0)]

    def _interpolate_position(
        self,
        waypoints: list[tuple[float, float]],
        progress: float,
    ) -> tuple[float, float]:
        """Linearly interpolate position along waypoints."""
        if len(waypoints) < 2:
            return waypoints[0] if waypoints else (0.0, 0.0)

        segment_count = len(waypoints) - 1
        segment = min(int(progress * segment_count), segment_count - 1)
        local_progress = (progress * segment_count) - segment

        p1 = waypoints[segment]
        p2 = waypoints[segment + 1]

        lat = p1[0] + (p2[0] - p1[0]) * local_progress
        lng = p1[1] + (p2[1] - p1[1]) * local_progress

        # Add small GPS noise
        lat += random.uniform(-0.001, 0.001)
        lng += random.uniform(-0.001, 0.001)

        return (round(lat, 6), round(lng, 6))

    def _near_waypoint(
        self, progress: float, waypoint_index: int, total_points: int
    ) -> bool:
        """Check if current progress is near a specific waypoint."""
        if total_points < 2:
            return False
        wp_progress = (waypoint_index + 1) / total_points
        return abs(progress - wp_progress) < 0.15

    def _anomaly_progress(
        self, progress: float, waypoint_index: int, total_points: int
    ) -> float:
        """How far into the anomaly zone we are (0-1)."""
        wp_progress = (waypoint_index + 1) / total_points
        distance = progress - (wp_progress - 0.15)
        return max(0.0, min(1.0, distance / 0.3))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fleet telemetry simulator")
    parser.add_argument(
        "--routes",
        default="data/mock-telemetry/routes.json",
        help="Routes JSON file path",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Simulation duration in minutes",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=None,
        help="Kafka bootstrap servers (if not set, prints events)",
    )
    args = parser.parse_args()

    sim = TelemetrySimulator.from_routes_file(args.routes)
    events = sim.generate_events(duration_minutes=args.duration)

    if args.bootstrap_servers:
        import asyncio

        from aiokafka import AIOKafkaProducer

        async def publish():
            producer = AIOKafkaProducer(
                bootstrap_servers=args.bootstrap_servers,
            )
            await producer.start()
            try:
                for event in events:
                    topic = event.pop("topic")
                    event.pop("event_type")
                    value = json.dumps(event).encode("utf-8")
                    key = event["truck_id"].encode("utf-8")
                    await producer.send_and_wait(topic=topic, value=value, key=key)
                print(f"Published {len(events)} events to Kafka")
            finally:
                await producer.stop()

        asyncio.run(publish())
    else:
        print(f"Generated {len(events)} events")
        for event in events[:10]:
            print(json.dumps(event, indent=2))
        if len(events) > 10:
            print(f"... and {len(events) - 10} more")
