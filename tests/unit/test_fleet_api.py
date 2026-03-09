"""Unit tests for fleet API endpoints.

Tests: GET /fleet/status, GET /fleet/alerts, POST /fleet/alerts/{alert_id}/resolve,
WebSocket /fleet/ws.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.domains.logicore.models.fleet import (
    AlertSeverity,
    AlertType,
    FleetAlert,
)


@pytest.fixture
def fleet_app():
    """Create a FastAPI app with the fleet router."""
    from fastapi import FastAPI

    from apps.api.src.domains.logicore.api.fleet import create_fleet_router

    app = FastAPI()
    router = create_fleet_router()
    app.include_router(router)
    return app


@pytest.fixture
def sample_alerts():
    """Sample alerts for testing."""
    return [
        FleetAlert(
            alert_id="alert-001",
            truck_id="truck-4721",
            alert_type=AlertType.TEMPERATURE_SPIKE,
            severity=AlertSeverity.CRITICAL,
            details="Temperature 9.0C exceeds threshold",
            timestamp=datetime(2026, 3, 9, 3, 1, 30, tzinfo=UTC),
        ),
        FleetAlert(
            alert_id="alert-002",
            truck_id="truck-1234",
            alert_type=AlertType.SPEED_ANOMALY,
            severity=AlertSeverity.HIGH,
            details="Speed 135 km/h exceeds limit",
            timestamp=datetime(2026, 3, 9, 3, 5, 0, tzinfo=UTC),
        ),
    ]


# ── GET /fleet/status ────────────────────────────────────────────────────────


class TestFleetStatus:
    """Fleet status endpoint -- summary of all trucks."""

    async def test_fleet_status_returns_200(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/status")

        assert response.status_code == 200

    async def test_fleet_status_has_expected_fields(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/status")

        data = response.json()
        assert "total_trucks" in data
        assert "active_alerts" in data
        assert "consumer_health" in data


# ── GET /fleet/alerts ────────────────────────────────────────────────────────


class TestFleetAlerts:
    """Alerts endpoint -- list active and recent alerts."""

    async def test_alerts_returns_200(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/alerts")

        assert response.status_code == 200

    async def test_alerts_returns_list(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/alerts")

        data = response.json()
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

    async def test_alerts_filter_by_truck(self, fleet_app, sample_alerts):
        """Inject alerts and filter by truck_id."""
        from apps.api.src.domains.logicore.api import fleet as fleet_module

        fleet_module._alert_store.clear()
        for alert in sample_alerts:
            fleet_module._alert_store[alert.alert_id] = alert

        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/alerts?truck_id=truck-4721")

        data = response.json()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["truck_id"] == "truck-4721"

        fleet_module._alert_store.clear()

    async def test_alerts_filter_by_severity(self, fleet_app, sample_alerts):
        from apps.api.src.domains.logicore.api import fleet as fleet_module

        fleet_module._alert_store.clear()
        for alert in sample_alerts:
            fleet_module._alert_store[alert.alert_id] = alert

        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/alerts?severity=critical")

        data = response.json()
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["severity"] == "critical"

        fleet_module._alert_store.clear()


# ── POST /fleet/alerts/{alert_id}/resolve ────────────────────────────────────


class TestResolveAlert:
    """Resolve an alert -- marks it as handled."""

    async def test_resolve_existing_alert(self, fleet_app, sample_alerts):
        from apps.api.src.domains.logicore.api import fleet as fleet_module

        fleet_module._alert_store.clear()
        fleet_module._alert_store["alert-001"] = sample_alerts[0]

        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.post("/api/v1/fleet/alerts/alert-001/resolve")

        assert response.status_code == 200
        data = response.json()
        assert data["resolved"] is True

        fleet_module._alert_store.clear()

    async def test_resolve_nonexistent_alert_returns_404(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.post("/api/v1/fleet/alerts/alert-999/resolve")

        assert response.status_code == 404


# ── POST /fleet/ingest (telemetry ingestion for non-Kafka fallback) ──────────


class TestFleetIngest:
    """Direct telemetry ingestion endpoint (fallback when Kafka is down)."""

    async def test_ingest_temperature_reading(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/fleet/ingest/temperature",
                json={
                    "truck_id": "truck-001",
                    "sensor_id": "sensor-01",
                    "temp_celsius": 9.5,
                    "setpoint_celsius": 3.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data

    async def test_ingest_invalid_temperature_returns_422(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/fleet/ingest/temperature",
                json={
                    "truck_id": "truck-001",
                    "sensor_id": "sensor-01",
                    "temp_celsius": 200.0,  # > 100C hardware limit
                    "setpoint_celsius": 3.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        assert response.status_code == 422

    async def test_ingest_gps_ping(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/fleet/ingest/gps",
                json={
                    "truck_id": "truck-001",
                    "latitude": 47.37,
                    "longitude": 8.54,
                    "speed_kmh": 80.0,
                    "heading": 180.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data


# ── Consumer Health ──────────────────────────────────────────────────────────


class TestConsumerHealth:
    """Consumer health monitoring endpoint."""

    async def test_consumer_health_endpoint(self, fleet_app):
        async with AsyncClient(
            transport=ASGITransport(app=fleet_app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/fleet/consumer/health")

        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        assert "messages_processed" in data
