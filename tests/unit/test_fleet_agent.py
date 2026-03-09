"""Unit tests for the fleet guardian agent.

The fleet agent ties together: Kafka consumer -> anomaly detector ->
LangGraph fleet response graph. It processes raw telemetry events,
filters normal events (zero LLM cost), and triggers the agent only
on confirmed anomalies.

All external deps (Kafka, Redis, PostgreSQL, LLM) are mocked.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.domains.logicore.models.fleet import (
    AlertType,
    FleetAlert,
)


# ── FleetGuardianAgent ──────────────────────────────────────────────────────


class TestFleetGuardianAgent:
    """Tests for the main agent that orchestrates detection -> response."""

    async def test_process_normal_temperature_no_graph_invocation(self):
        """Normal readings should be filtered -- no LLM cost."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "sensor_id": "sensor-01",
            "temp_celsius": 3.5,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.process_temperature(msg)

        assert result["alerts"] == []
        mock_graph.ainvoke.assert_not_called()

    async def test_process_anomalous_temperature_triggers_graph(self):
        """Confirmed anomaly should trigger the fleet response graph."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "action_plan": "Divert to cold storage",
            "notifications": [{"target": "driver", "message": "Alert"}],
            "pattern_detected": None,
        })
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-4721",
            "sensor_id": "sensor-01",
            "temp_celsius": 12.0,  # Well above threshold
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.process_temperature(msg)

        assert len(result["alerts"]) >= 1
        mock_graph.ainvoke.assert_called_once()

    async def test_process_gps_normal_no_alerts(self):
        """Normal GPS ping should produce no alerts."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "latitude": 47.37,
            "longitude": 8.54,
            "speed_kmh": 80.0,
            "heading": 180.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.process_gps(msg)

        assert result["alerts"] == []

    async def test_process_gps_speed_anomaly_triggers_graph(self):
        """Speed anomaly should trigger the fleet response graph."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "action_plan": "Speed alert: notify driver",
            "notifications": [{"target": "driver", "message": "Slow down"}],
            "pattern_detected": None,
        })
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "latitude": 47.37,
            "longitude": 8.54,
            "speed_kmh": 140.0,  # Over limit
            "heading": 180.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.process_gps(msg)

        assert len(result["alerts"]) >= 1
        mock_graph.ainvoke.assert_called_once()

    async def test_metrics_tracking(self):
        """Agent should track processed/filtered/alerted counts."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "action_plan": "test",
            "notifications": [],
            "pattern_detected": None,
        })
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        # Process 3 normal + 1 anomalous
        for i in range(3):
            await agent.process_temperature({
                "truck_id": f"truck-{i:03d}",
                "sensor_id": "s01",
                "temp_celsius": 3.5,
                "setpoint_celsius": 3.0,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        await agent.process_temperature({
            "truck_id": "truck-099",
            "sensor_id": "s01",
            "temp_celsius": 12.0,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        assert agent.metrics["events_processed"] == 4
        assert agent.metrics["events_filtered"] == 3
        assert agent.metrics["anomalies_detected"] >= 1

    async def test_graph_error_does_not_crash_agent(self):
        """Graph invocation errors should be caught and logged."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM failed"))
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "sensor_id": "s01",
            "temp_celsius": 12.0,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Should not raise
        result = await agent.process_temperature(msg)

        # Alerts from detector should still be returned
        assert len(result["alerts"]) >= 1
        assert agent.metrics["graph_errors"] >= 1

    async def test_alert_callback_invoked(self):
        """Optional callback for publishing alerts (to Kafka, WebSocket, etc.)."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "action_plan": "test",
            "notifications": [],
            "pattern_detected": None,
        })
        mock_memory = AsyncMock()
        callback_calls = []

        async def on_alert(alert: FleetAlert):
            callback_calls.append(alert)

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
            on_alert=on_alert,
        )

        await agent.process_temperature({
            "truck_id": "truck-001",
            "sensor_id": "s01",
            "temp_celsius": 12.0,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        assert len(callback_calls) >= 1

    async def test_dispatch_routes_temperature_messages(self):
        """Generic dispatch method routes by topic."""
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "sensor_id": "s01",
            "temp_celsius": 3.5,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.dispatch(topic="fleet.temperature", message=msg)
        assert "alerts" in result

    async def test_dispatch_routes_gps_messages(self):
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(
            graph=mock_graph,
            memory_store=mock_memory,
        )

        msg = {
            "truck_id": "truck-001",
            "latitude": 47.37,
            "longitude": 8.54,
            "speed_kmh": 80.0,
            "heading": 180.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        result = await agent.dispatch(topic="fleet.gps-pings", message=msg)
        assert "alerts" in result
