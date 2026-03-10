"""Unit tests for fleet API endpoints.

Tests: GET /fleet/status, GET /fleet/alerts, POST /fleet/alerts/{alert_id}/resolve,
WebSocket /fleet/ws.
"""

from datetime import UTC, datetime

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


# ── WebSocket Broadcast (direct test) ────────────────────────────────────


class TestWebSocketBroadcast:
    """Proves connected WebSocket clients receive alerts when telemetry is ingested.

    CTO QUESTION: "How do I know the dashboard actually gets alerts in real-time?"
    These tests prove it: connect WS → ingest anomaly → assert WS message arrives.
    """

    async def test_ws_client_receives_alert_on_ingest(self):
        """Connect WS, ingest anomalous temp, verify alert arrives via WS."""
        import json

        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )
        from apps.api.src.domains.logicore.api import fleet as fleet_module
        from apps.api.src.domains.logicore.api.fleet import (
            _alert_store,
            create_fleet_router,
        )

        app = FastAPI()
        app.include_router(create_fleet_router())

        _alert_store.clear()
        fleet_module._detector = AnomalyDetector()
        fleet_module._ws_connections.clear()

        # Use Starlette TestClient for WebSocket support
        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/fleet/ws") as ws:
                # Ingest an anomalous reading via HTTP (separate client)
                response = client.post(
                    "/api/v1/fleet/ingest/temperature",
                    json={
                        "truck_id": "truck-ws-test",
                        "sensor_id": "sensor-01",
                        "temp_celsius": 12.0,
                        "setpoint_celsius": 3.0,
                        "timestamp": "2026-03-10T03:01:30+00:00",
                    },
                )
                assert response.status_code == 200
                assert len(response.json()["alerts"]) >= 1

                # WebSocket should have received the alert
                ws_message = ws.receive_text()
                alert_data = json.loads(ws_message)

                assert alert_data["truck_id"] == "truck-ws-test"
                assert alert_data["alert_type"] == "temperature_spike"
                assert alert_data["severity"] == "critical"

        _alert_store.clear()
        fleet_module._ws_connections.clear()

    async def test_multiple_ws_clients_all_receive_alert(self):
        """Multiple WS clients connected — all should receive the same alert."""
        import json

        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )
        from apps.api.src.domains.logicore.api import fleet as fleet_module
        from apps.api.src.domains.logicore.api.fleet import (
            _alert_store,
            create_fleet_router,
        )

        app = FastAPI()
        app.include_router(create_fleet_router())

        _alert_store.clear()
        fleet_module._detector = AnomalyDetector()
        fleet_module._ws_connections.clear()

        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/fleet/ws") as ws1:
                with client.websocket_connect("/api/v1/fleet/ws") as ws2:
                    # Ingest anomaly
                    response = client.post(
                        "/api/v1/fleet/ingest/temperature",
                        json={
                            "truck_id": "truck-multi-ws",
                            "sensor_id": "sensor-01",
                            "temp_celsius": 15.0,
                            "setpoint_celsius": 3.0,
                            "timestamp": "2026-03-10T03:02:00+00:00",
                        },
                    )
                    assert response.status_code == 200

                    # Both clients should receive the alert
                    msg1 = json.loads(ws1.receive_text())
                    msg2 = json.loads(ws2.receive_text())

                    assert msg1["truck_id"] == "truck-multi-ws"
                    assert msg2["truck_id"] == "truck-multi-ws"
                    assert msg1["alert_id"] == msg2["alert_id"]

        _alert_store.clear()
        fleet_module._ws_connections.clear()

    async def test_ws_ping_pong(self):
        """WebSocket keep-alive: send ping, receive pong."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from apps.api.src.domains.logicore.api.fleet import create_fleet_router

        app = FastAPI()
        app.include_router(create_fleet_router())

        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/fleet/ws") as ws:
                ws.send_text("ping")
                response = ws.receive_text()
                assert response == "pong"
