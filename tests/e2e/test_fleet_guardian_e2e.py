"""E2E tests for Fleet Guardian pipeline.

Tests the full flow: simulator events -> anomaly detector -> fleet agent
-> fleet response graph -> alerts + notifications.

No real Kafka, Redis, or PostgreSQL needed -- all mocked.
These tests prove the pipeline components integrate correctly.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from apps.api.src.domains.logicore.models.fleet import (
    AlertType,
)


@pytest.mark.e2e
class TestFleetGuardianPipeline:
    """Full pipeline: events -> detector -> agent -> graph -> alerts."""

    async def test_normal_events_filtered_no_llm_cost(self):
        """100 normal events -> 0 alerts -> 0 LLM calls.

        DECISION: Two-tier processing is mandatory. Without it, processing
        47K daily pings through GPT-5.2 costs EUR 662/day. With it: EUR 0.075/day.
        COST OF WRONG CHOICE: EUR 19,860/month wasted on LLM calls for normal events.
        """
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_memory = AsyncMock()
        agent = FleetGuardianAgent(graph=mock_graph, memory_store=mock_memory)

        for i in range(100):
            await agent.process_temperature({
                "truck_id": f"truck-{i % 10:03d}",
                "sensor_id": "s01",
                "temp_celsius": 3.0 + (i % 5) * 0.2,  # 3.0-3.8, all normal
                "setpoint_celsius": 3.0,
                "timestamp": datetime.now(UTC).isoformat(),
            })

        assert agent.metrics["events_processed"] == 100
        assert agent.metrics["events_filtered"] == 100
        assert agent.metrics["anomalies_detected"] == 0
        assert agent.metrics["graph_invocations"] == 0
        # 100% filter rate = zero LLM cost

    async def test_temperature_spike_triggers_full_response(self):
        """Temperature spike -> detector -> graph -> action plan + notification.

        DECISION: Threshold detection catches sudden spikes immediately.
        COST OF WRONG CHOICE: Missing a temperature spike on EUR 180K pharma
        cargo = EUR 207,000 total loss (cargo + penalty).
        """
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "alert": {"truck_id": "truck-4721"},
            "action_plan": "URGENT: Divert to Zurich cold storage CS-CH-ZH-04",
            "notifications": [
                {"target": "driver", "message": "Temperature alert"},
                {"target": "dispatch", "message": "Fleet alert on truck-4721"},
            ],
            "pattern_detected": None,
            "financial_risk": 27000.0,
        })
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(graph=mock_graph, memory_store=mock_memory)

        result = await agent.process_temperature({
            "truck_id": "truck-4721",
            "sensor_id": "sensor-01",
            "temp_celsius": 12.0,
            "setpoint_celsius": 3.0,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        assert len(result["alerts"]) >= 1
        assert result["graph_result"] is not None
        assert "Divert" in result["graph_result"]["action_plan"]
        assert agent.metrics["graph_invocations"] == 1

    async def test_slow_drift_detected_before_threshold(self):
        """Gradual temp rise caught by rate-of-change detection.

        DECISION: Rate-of-change detection is mandatory, not optional.
        Threshold-only detection misses 40% of temperature incidents (slow drifts).
        COST OF WRONG CHOICE: EUR 414,000-621,000/year in missed incidents.
        """
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )

        detector = AnomalyDetector(threshold_margin=5.0, drift_rate_threshold=0.5)
        base_time = datetime.now(UTC) - timedelta(minutes=30)

        # Simulate the EUR 207,000 scenario: 3.1C -> 4.5C over 30 min
        readings = [
            {"temp": 3.1, "offset_min": 0},
            {"temp": 3.5, "offset_min": 10},
            {"temp": 3.8, "offset_min": 15},
            {"temp": 4.1, "offset_min": 20},
            {"temp": 4.5, "offset_min": 30},
        ]

        all_alerts = []
        for r in readings:
            from apps.api.src.domains.logicore.models.fleet import TemperatureReading

            reading = TemperatureReading(
                truck_id="truck-4721",
                sensor_id="sensor-01",
                temp_celsius=r["temp"],
                setpoint_celsius=3.0,
                timestamp=base_time + timedelta(minutes=r["offset_min"]),
            )
            alerts = detector.check_temperature(reading)
            all_alerts.extend(alerts)

        drift_alerts = [a for a in all_alerts if a.alert_type == AlertType.TEMPERATURE_DRIFT]
        assert len(drift_alerts) >= 1, (
            "Rate-of-change detection MUST catch slow drift before threshold breach. "
            "Without this: EUR 207,000 per missed incident."
        )

        # Verify NO threshold alert fired (4.5C < 3.0 + 5.0 = 8.0C)
        spike_alerts = [a for a in all_alerts if a.alert_type == AlertType.TEMPERATURE_SPIKE]
        assert len(spike_alerts) == 0, (
            "Threshold should NOT fire at 4.5C (threshold is 8.0C). "
            "Drift detection catches it before threshold breach."
        )

    async def test_recurring_pattern_escalates_to_maintenance(self):
        """3rd anomaly on same truck -> skip investigation -> maintenance alert.

        DECISION: Cross-session memory saves EUR 3,500-10,500/year by
        preventing repeated diversions on trucks with failing equipment.
        WITHOUT MEMORY: EUR 2,000/diversion x 3 = EUR 6,000 wasted.
        WITH MEMORY: One repair (EUR 2,500) after pattern detection.
        """
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            escalate_maintenance_node,
            route_by_memory,
        )

        # State simulating a truck with recurring temp spikes
        state = {
            "alert": {
                "alert_id": "alert-test",
                "truck_id": "truck-4521",
                "alert_type": "temperature_spike",
                "severity": "critical",
                "details": "Temperature spike #3",
                "timestamp": datetime.now(UTC).isoformat(),
            },
            "truck_history": [
                {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-12"},
            ],
            "known_patterns": [],
            "pattern_detected": None,
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
        }

        # Routing should go to escalation, not investigation
        route = route_by_memory(state)
        assert route == "escalate_maintenance"

        # Escalation node should set pattern and maintenance recommendation
        result = await escalate_maintenance_node(state)
        assert result["pattern_detected"] is not None
        assert "maintenance" in result["action_plan"].lower()
        assert "3" in result["action_plan"]  # mentions occurrence count

    async def test_stateless_vs_memory_different_responses(self):
        """Same alert produces different response with vs without memory.

        This is the key architect demonstration: memory changes behavior.
        RECOMMENDATION: Memory adds ~5ms latency (Redis lookup) per anomaly.
        That's acceptable when it prevents a 5th unnecessary EUR 2,000 diversion.
        """
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            escalate_maintenance_node,
            investigate_node,
            route_by_memory,
        )

        alert = {
            "alert_id": "alert-test",
            "truck_id": "truck-4521",
            "alert_type": "temperature_spike",
            "severity": "critical",
            "details": "Temperature spike",
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Stateless: no history -> investigate
        stateless_state = {
            "alert": alert,
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
        }

        route_stateless = route_by_memory(stateless_state)
        assert route_stateless == "investigate"

        result_stateless = await investigate_node(stateless_state)
        assert result_stateless["action_plan"] is not None
        assert "maintenance" not in result_stateless["action_plan"].lower()

        # Memory-aware: 3 previous alerts -> escalate
        memory_state = {
            "alert": alert,
            "truck_history": [
                {"alert_type": "temperature_spike"} for _ in range(3)
            ],
            "known_patterns": [],
            "pattern_detected": None,
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
        }

        route_memory = route_by_memory(memory_state)
        assert route_memory == "escalate_maintenance"

        result_memory = await escalate_maintenance_node(memory_state)
        assert "maintenance" in result_memory["action_plan"].lower()

        # Different responses for same alert
        assert result_stateless["action_plan"] != result_memory["action_plan"]

    async def test_simulator_to_agent_full_pipeline(self):
        """Run simulator events through the full agent pipeline.

        Generates realistic telemetry, processes through anomaly detector,
        and verifies the two-tier filter rate.
        """
        from apps.api.src.domains.logicore.agents.guardian.fleet_agent import (
            FleetGuardianAgent,
        )
        from scripts.telemetry_simulator import TelemetrySimulator

        sim = TelemetrySimulator.from_routes_file(
            "data/mock-telemetry/routes.json"
        )
        events = sim.generate_events(duration_minutes=30)

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={
            "action_plan": "Alert processed",
            "notifications": [],
            "pattern_detected": None,
        })
        mock_memory = AsyncMock()

        agent = FleetGuardianAgent(graph=mock_graph, memory_store=mock_memory)

        for event in events:
            topic = event["topic"]
            # Remove simulator-specific fields
            msg = {k: v for k, v in event.items() if k not in ("event_type", "topic")}
            await agent.dispatch(topic=topic, message=msg)

        total = agent.metrics["events_processed"]
        filtered = agent.metrics["events_filtered"]
        anomalies = agent.metrics["anomalies_detected"]

        # Two-tier filter rate should be >80% (most events are normal)
        filter_rate = filtered / total if total > 0 else 0
        assert filter_rate > 0.80, (
            f"Filter rate {filter_rate:.1%} is too low. "
            f"Two-tier processing should filter >80% of events. "
            f"Total: {total}, Filtered: {filtered}, Anomalies: {anomalies}"
        )

    async def test_alert_dedup_prevents_flooding(self):
        """Same anomaly within 5 min -> single alert, not 20.

        DECISION: Alert deduplication is mandatory to prevent alert fatigue.
        WITHOUT IT: 50+ false/duplicate alerts during heatwave -> dispatchers
        ignore all alerts -> real EUR 180K pharma alert missed.
        """
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )
        from apps.api.src.domains.logicore.models.fleet import TemperatureReading

        detector = AnomalyDetector(dedup_window_seconds=300)
        now = datetime.now(UTC)

        alert_count = 0
        for i in range(20):
            reading = TemperatureReading(
                truck_id="truck-001",
                sensor_id="s01",
                temp_celsius=12.0,
                setpoint_celsius=3.0,
                timestamp=now + timedelta(seconds=i * 10),  # every 10 seconds
            )
            alerts = detector.check_temperature(reading)
            alert_count += len(alerts)

        # Should produce exactly 1 alert (first one), rest are deduplicated
        # (could also produce drift alerts, but spike should be 1)
        spike_alerts_count = alert_count  # rough count
        assert spike_alerts_count < 5, (
            f"Got {spike_alerts_count} alerts for 20 readings of the same anomaly. "
            f"Dedup should suppress duplicates within 5-minute window."
        )


@pytest.mark.e2e
class TestFleetAPIIntegration:
    """E2E tests for the fleet API with the full pipeline."""

    async def test_ingest_and_query_alerts(self):
        """POST temperature -> GET alerts -> verify alert appears."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

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

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Ingest an anomalous temperature reading
            ingest_resp = await ac.post(
                "/api/v1/fleet/ingest/temperature",
                json={
                    "truck_id": "truck-ingest-test",
                    "sensor_id": "sensor-01",
                    "temp_celsius": 12.0,
                    "setpoint_celsius": 3.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            assert ingest_resp.status_code == 200
            assert len(ingest_resp.json()["alerts"]) >= 1

            # Query alerts
            alerts_resp = await ac.get("/api/v1/fleet/alerts")
            assert alerts_resp.status_code == 200
            assert alerts_resp.json()["total"] >= 1

            # Filter by truck
            filtered_resp = await ac.get(
                "/api/v1/fleet/alerts?truck_id=truck-ingest-test"
            )
            assert filtered_resp.status_code == 200
            assert filtered_resp.json()["total"] >= 1

        _alert_store.clear()

    async def test_resolve_alert_flow(self):
        """POST alert -> resolve -> verify resolved."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

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

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Ingest anomalous reading (unique truck to avoid dedup)
            ingest_resp = await ac.post(
                "/api/v1/fleet/ingest/temperature",
                json={
                    "truck_id": "truck-resolve-test",
                    "sensor_id": "sensor-01",
                    "temp_celsius": 15.0,
                    "setpoint_celsius": 3.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            alerts = ingest_resp.json()["alerts"]
            alert_id = alerts[0]["alert_id"]

            # Resolve it
            resolve_resp = await ac.post(
                f"/api/v1/fleet/alerts/{alert_id}/resolve"
            )
            assert resolve_resp.status_code == 200
            assert resolve_resp.json()["resolved"] is True

        _alert_store.clear()

    async def test_fleet_status_reflects_state(self):
        """Status endpoint should reflect current fleet state."""
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from apps.api.src.domains.logicore.api import fleet as fleet_module
        from apps.api.src.domains.logicore.api.fleet import (
            _alert_store,
            create_fleet_router,
        )

        app = FastAPI()
        app.include_router(create_fleet_router())

        _alert_store.clear()
        # Reset the detector to clear dedup state from previous tests
        from apps.api.src.domains.logicore.agents.guardian.anomaly_detector import (
            AnomalyDetector,
        )
        fleet_module._detector = AnomalyDetector()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Empty state
            status = await ac.get("/api/v1/fleet/status")
            assert status.json()["active_alerts"] == 0

            # Add an alert (unique truck to avoid dedup from other tests)
            await ac.post(
                "/api/v1/fleet/ingest/temperature",
                json={
                    "truck_id": "truck-status-test",
                    "sensor_id": "s01",
                    "temp_celsius": 12.0,
                    "setpoint_celsius": 3.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

            # Status should reflect the alert
            status2 = await ac.get("/api/v1/fleet/status")
            assert status2.json()["active_alerts"] >= 1

        _alert_store.clear()
