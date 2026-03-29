"""Fleet Guardian agent -- orchestrates detection, memory, and response.

The main entry point for processing telemetry events. Routes:
  Kafka message -> anomaly detector (rule-based, zero LLM cost)
    -> if anomaly: trigger LangGraph fleet response graph (LLM cost)
    -> if normal: filter (EUR 0.00)

This is the two-tier processing core that makes real-time AI economically
viable: 99.95% cost reduction vs LLM-for-everything.
"""

import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
    AnomalyDetector,
)
from apps.api.src.domains.logicore.models.fleet import (
    FleetAlert,
    GPSPing,
    TemperatureReading,
)

logger = logging.getLogger(__name__)


class FleetGuardianAgent:
    """Orchestrates anomaly detection -> fleet response graph.

    Args:
        graph: Compiled LangGraph fleet response graph.
        memory_store: MemoryStore for 3-tier memory.
        detector: AnomalyDetector instance (optional, creates default).
        on_alert: Optional async callback for each generated alert.
    """

    def __init__(
        self,
        graph: Any,
        memory_store: Any,
        detector: AnomalyDetector | None = None,
        on_alert: Callable[[FleetAlert], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._graph = graph
        self._memory = memory_store
        self._detector = detector or AnomalyDetector()
        self._on_alert = on_alert

        self.metrics: dict[str, int] = {
            "events_processed": 0,
            "events_filtered": 0,
            "anomalies_detected": 0,
            "graph_invocations": 0,
            "graph_errors": 0,
        }

    async def process_temperature(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Process a temperature reading from Kafka or direct ingestion.

        Returns dict with alerts list and any graph results.
        """
        self.metrics["events_processed"] += 1

        reading = TemperatureReading(
            truck_id=msg["truck_id"],
            sensor_id=msg["sensor_id"],
            temp_celsius=msg["temp_celsius"],
            setpoint_celsius=msg["setpoint_celsius"],
            timestamp=(
                datetime.fromisoformat(msg["timestamp"])
                if isinstance(msg["timestamp"], str)
                else msg["timestamp"]
            ),
        )

        alerts = self._detector.check_temperature(reading)

        if not alerts:
            self.metrics["events_filtered"] += 1
            return {"alerts": [], "graph_result": None}

        self.metrics["anomalies_detected"] += len(alerts)
        return await self._handle_alerts(alerts)

    async def process_gps(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Process a GPS ping from Kafka or direct ingestion."""
        self.metrics["events_processed"] += 1

        ping = GPSPing(
            truck_id=msg["truck_id"],
            latitude=msg["latitude"],
            longitude=msg["longitude"],
            speed_kmh=msg["speed_kmh"],
            heading=msg["heading"],
            timestamp=(
                datetime.fromisoformat(msg["timestamp"])
                if isinstance(msg["timestamp"], str)
                else msg["timestamp"]
            ),
            engine_on=msg.get("engine_on", True),
        )

        alerts = self._detector.check_gps(ping)

        if not alerts:
            self.metrics["events_filtered"] += 1
            return {"alerts": [], "graph_result": None}

        self.metrics["anomalies_detected"] += len(alerts)
        return await self._handle_alerts(alerts)

    async def dispatch(
        self, topic: str, message: dict[str, Any]
    ) -> dict[str, Any]:
        """Route a message by topic to the appropriate processor."""
        if topic == "fleet.temperature":
            return await self.process_temperature(message)
        elif topic == "fleet.gps-pings":
            return await self.process_gps(message)
        else:
            logger.warning("Unknown topic: %s", topic)
            return {"alerts": [], "graph_result": None}

    async def _handle_alerts(
        self, alerts: list[FleetAlert]
    ) -> dict[str, Any]:
        """Handle confirmed anomalies: invoke callbacks and graph."""
        # Invoke alert callback for each alert
        if self._on_alert:
            for alert in alerts:
                try:
                    await self._on_alert(alert)
                except Exception:
                    logger.exception("Alert callback error for %s", alert.alert_id)

        # Invoke the fleet response graph for the first (highest-severity) alert
        alert = alerts[0]
        graph_result = None

        try:
            self.metrics["graph_invocations"] += 1
            graph_result = await self._graph.ainvoke({
                "alert": alert.model_dump(mode="json"),
                "cargo_manifest": None,
                "financial_risk": None,
                "nearest_facility": None,
                "action_plan": None,
                "notifications": [],
                "truck_history": None,
                "known_patterns": None,
                "pattern_detected": None,
            })
        except Exception:
            self.metrics["graph_errors"] += 1
            logger.exception(
                "Graph invocation failed for alert %s on truck %s",
                alert.alert_id,
                alert.truck_id,
            )

        return {
            "alerts": [a.model_dump(mode="json") for a in alerts],
            "graph_result": graph_result,
        }
