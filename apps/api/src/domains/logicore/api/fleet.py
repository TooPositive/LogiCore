"""Fleet API endpoints for Phase 9: Fleet Guardian.

GET  /api/v1/fleet/status           -- fleet summary (trucks, active alerts, consumer health)
GET  /api/v1/fleet/alerts           -- list alerts with optional truck_id/severity filters
POST /api/v1/fleet/alerts/{id}/resolve -- mark alert as resolved
POST /api/v1/fleet/ingest/temperature  -- direct ingestion (Kafka fallback)
POST /api/v1/fleet/ingest/gps         -- direct GPS ingestion (Kafka fallback)
GET  /api/v1/fleet/consumer/health     -- Kafka consumer health status
WS   /api/v1/fleet/ws                 -- real-time alert stream via WebSocket
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
    AnomalyDetector,
)
from apps.api.src.domains.logicore.models.fleet import (
    FleetAlert,
    GPSPing,
    TemperatureReading,
)

# In-memory alert store (production: PostgreSQL + Kafka consumer populates this)
_alert_store: dict[str, FleetAlert] = {}

# Shared anomaly detector instance
_detector = AnomalyDetector()

# WebSocket connections for real-time updates
_ws_connections: list[WebSocket] = []

# Consumer health state (set by the Kafka consumer worker)
_consumer_state: dict[str, Any] = {
    "running": False,
    "messages_processed": 0,
    "errors": 0,
    "last_message_at": None,
}


# ── Response Models ──────────────────────────────────────────────────────────


class FleetStatusResponse(BaseModel):
    total_trucks: int
    active_alerts: int
    consumer_health: dict[str, Any]


class AlertsResponse(BaseModel):
    alerts: list[dict[str, Any]]
    total: int


class ResolveResponse(BaseModel):
    alert_id: str
    resolved: bool


class IngestResponse(BaseModel):
    processed: bool
    alerts: list[dict[str, Any]]


class ConsumerHealthResponse(BaseModel):
    running: bool
    messages_processed: int
    errors: int
    last_message_at: str | None


# ── Router Factory ───────────────────────────────────────────────────────────


def create_fleet_router() -> APIRouter:
    """Create the fleet API router.

    Uses a factory function so tests can create isolated routers.
    """
    router = APIRouter(prefix="/api/v1/fleet", tags=["fleet"])

    @router.get("/status", response_model=FleetStatusResponse)
    async def fleet_status() -> FleetStatusResponse:
        """Fleet summary: total trucks tracked, active alerts, consumer health."""
        # Auto-resolve alerts older than 10 minutes
        now = datetime.now(UTC)
        for alert in _alert_store.values():
            if not alert.resolved:
                age = (now - alert.timestamp).total_seconds()
                if age > 600:
                    alert.resolved = True

        active_alerts = sum(1 for a in _alert_store.values() if not a.resolved)
        truck_ids = {a.truck_id for a in _alert_store.values() if not a.resolved}

        return FleetStatusResponse(
            total_trucks=len(truck_ids),
            active_alerts=active_alerts,
            consumer_health=_consumer_state,
        )

    @router.get("/alerts", response_model=AlertsResponse)
    async def list_alerts(
        truck_id: str | None = None,
        severity: str | None = None,
    ) -> AlertsResponse:
        """List alerts with optional filters."""
        alerts = list(_alert_store.values())

        if truck_id:
            alerts = [a for a in alerts if a.truck_id == truck_id]
        if severity:
            alerts = [a for a in alerts if a.severity.value == severity]

        alert_dicts = [a.model_dump(mode="json") for a in alerts]

        return AlertsResponse(alerts=alert_dicts, total=len(alert_dicts))

    @router.post("/alerts/{alert_id}/resolve", response_model=ResolveResponse)
    async def resolve_alert(alert_id: str) -> ResolveResponse:
        """Mark an alert as resolved."""
        if alert_id not in _alert_store:
            raise HTTPException(
                status_code=404,
                detail=f"Alert {alert_id} not found",
            )

        _alert_store[alert_id].resolved = True

        return ResolveResponse(alert_id=alert_id, resolved=True)

    @router.post("/ingest/temperature", response_model=IngestResponse)
    async def ingest_temperature(reading: TemperatureReading) -> IngestResponse:
        """Direct temperature ingestion (fallback when Kafka is unavailable).

        Runs the anomaly detector and returns any generated alerts.
        """
        alerts = _detector.check_temperature(reading)

        for alert in alerts:
            _alert_store[alert.alert_id] = alert
            await _broadcast_alert(alert)

        _consumer_state["running"] = True
        _consumer_state["messages_processed"] += 1
        _consumer_state["last_message_at"] = datetime.now(UTC)

        return IngestResponse(
            processed=True,
            alerts=[a.model_dump(mode="json") for a in alerts],
        )

    @router.post("/ingest/gps", response_model=IngestResponse)
    async def ingest_gps(ping: GPSPing) -> IngestResponse:
        """Direct GPS ingestion (fallback when Kafka is unavailable)."""
        alerts = _detector.check_gps(ping)

        for alert in alerts:
            _alert_store[alert.alert_id] = alert
            await _broadcast_alert(alert)

        _consumer_state["running"] = True
        _consumer_state["messages_processed"] += 1
        _consumer_state["last_message_at"] = datetime.now(UTC)

        return IngestResponse(
            processed=True,
            alerts=[a.model_dump(mode="json") for a in alerts],
        )

    @router.get("/consumer/health", response_model=ConsumerHealthResponse)
    async def consumer_health() -> ConsumerHealthResponse:
        """Kafka consumer health status."""
        last_msg = _consumer_state.get("last_message_at")
        return ConsumerHealthResponse(
            running=_consumer_state.get("running", False),
            messages_processed=_consumer_state.get("messages_processed", 0),
            errors=_consumer_state.get("errors", 0),
            last_message_at=last_msg.isoformat() if last_msg else None,
        )

    @router.websocket("/ws")
    async def fleet_websocket(websocket: WebSocket) -> None:
        """WebSocket for real-time fleet alert streaming."""
        await websocket.accept()
        _ws_connections.append(websocket)
        try:
            while True:
                # Keep connection alive, client can send pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            _ws_connections.remove(websocket)

    return router


async def _broadcast_alert(alert: FleetAlert) -> None:
    """Broadcast an alert to all connected WebSocket clients."""
    import json

    message = json.dumps(alert.model_dump(mode="json"), default=str)
    disconnected = []
    for ws in _ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_connections.remove(ws)


def register_consumer_health(
    running: bool,
    messages_processed: int,
    errors: int,
    last_message_at: datetime | None,
) -> None:
    """Update consumer health state from the Kafka consumer worker."""
    _consumer_state["running"] = running
    _consumer_state["messages_processed"] = messages_processed
    _consumer_state["errors"] = errors
    _consumer_state["last_message_at"] = last_message_at
