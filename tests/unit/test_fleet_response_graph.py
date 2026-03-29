"""Unit tests for the LangGraph Fleet Response graph.

Tests the full workflow: memory_lookup -> route_by_memory ->
  investigate (normal) OR escalate_maintenance (recurring pattern) ->
  write_memory -> notify.

All external dependencies (LLM, RAG, Redis, PostgreSQL) are mocked.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from apps.api.src.domains.logicore.models.fleet import (
    AlertSeverity,
    AlertType,
    FleetMemoryEntry,
)


def _make_alert(**overrides) -> dict:
    """Create a FleetAlert dict for testing."""
    defaults = {
        "alert_id": "alert-test-001",
        "truck_id": "truck-4721",
        "alert_type": AlertType.TEMPERATURE_SPIKE.value,
        "severity": AlertSeverity.CRITICAL.value,
        "details": "Temperature 9.0C exceeds threshold 8.0C",
        "timestamp": datetime.now(UTC).isoformat(),
        "resolved": False,
        "cargo_value_eur": None,
    }
    defaults.update(overrides)
    return defaults


# ── State Schema ─────────────────────────────────────────────────────────────


class TestFleetResponseState:
    """Validate the state schema for the fleet response graph."""

    def test_state_has_required_fields(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            FleetResponseState,
        )

        # Should be a TypedDict with these fields
        annotations = FleetResponseState.__annotations__
        required = {
            "alert",
            "cargo_manifest",
            "financial_risk",
            "nearest_facility",
            "action_plan",
            "notifications",
            "truck_history",
            "known_patterns",
            "pattern_detected",
        }
        assert required <= set(annotations.keys()), (
            f"Missing fields: {required - set(annotations.keys())}"
        )


# ── Memory Lookup Node ──────────────────────────────────────────────────────


class TestMemoryLookupNode:
    """First node: check what we already know about this truck."""

    async def test_memory_lookup_populates_history_and_patterns(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            memory_lookup_node,
        )

        mock_memory = AsyncMock()
        mock_memory.lookup = AsyncMock(
            return_value={
                "truck_history": [
                    {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
                    {"alert_type": "temperature_spike", "timestamp": "2026-03-05"},
                ],
                "known_patterns": [
                    FleetMemoryEntry(
                        truck_id="truck-4721",
                        pattern="recurring_refrigeration_failure",
                        alert_type="temperature_spike",
                        action_taken="Diverted twice",
                        outcome="pending",
                        learned_at=datetime.now(UTC),
                        occurrence_count=2,
                    )
                ],
            }
        )

        state = {
            "alert": _make_alert(),
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": None,
            "known_patterns": None,
            "pattern_detected": None,
        }

        result = await memory_lookup_node(state, memory_store=mock_memory)

        assert len(result["truck_history"]) == 2
        assert len(result["known_patterns"]) == 1

    async def test_memory_lookup_with_no_history(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            memory_lookup_node,
        )

        mock_memory = AsyncMock()
        mock_memory.lookup = AsyncMock(
            return_value={"truck_history": [], "known_patterns": []}
        )

        state = {
            "alert": _make_alert(truck_id="truck-new"),
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": None,
            "known_patterns": None,
            "pattern_detected": None,
        }

        result = await memory_lookup_node(state, memory_store=mock_memory)

        assert result["truck_history"] == []
        assert result["known_patterns"] == []


# ── Route By Memory (Conditional Edge) ───────────────────────────────────────


class TestRouteByMemory:
    """Conditional routing: skip investigation if pattern is known."""

    def test_route_to_investigate_for_new_truck(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            route_by_memory,
        )

        state = {
            "alert": _make_alert(),
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = route_by_memory(state)
        assert result == "investigate"

    def test_route_to_investigate_with_few_similar_alerts(self):
        """Only 1 previous similar alert -- not enough for escalation."""
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            route_by_memory,
        )

        state = {
            "alert": _make_alert(),
            "truck_history": [
                {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
            ],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = route_by_memory(state)
        assert result == "investigate"

    def test_route_to_escalate_with_recurring_pattern(self):
        """3+ similar alerts in history -> skip to maintenance escalation."""
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            route_by_memory,
        )

        state = {
            "alert": _make_alert(),
            "truck_history": [
                {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-05"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-09"},
            ],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = route_by_memory(state)
        assert result == "escalate_maintenance"

    def test_route_ignores_different_alert_types(self):
        """3 alerts but different types -- not a recurring pattern."""
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            route_by_memory,
        )

        state = {
            "alert": _make_alert(alert_type=AlertType.TEMPERATURE_SPIKE.value),
            "truck_history": [
                {"alert_type": "speed_anomaly", "timestamp": "2026-03-01"},
                {"alert_type": "gps_deviation", "timestamp": "2026-03-05"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-09"},
            ],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = route_by_memory(state)
        assert result == "investigate"


# ── Investigation Node ───────────────────────────────────────────────────────


class TestInvestigationNode:
    """Normal investigation flow: RAG lookup + risk assessment + action plan."""

    async def test_investigate_produces_action_plan(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            investigate_node,
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content="URGENT: Divert truck-4721 to Zurich cold storage CS-CH-ZH-04."
            )
        )

        state = {
            "alert": _make_alert(),
            "cargo_manifest": {"cargo": "pharmaceutical", "value_eur": 180000},
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await investigate_node(state, llm=mock_llm)

        assert result["action_plan"] is not None
        assert len(result["action_plan"]) > 0

    async def test_investigate_calculates_financial_risk(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            investigate_node,
        )

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="Divert to cold storage.")
        )

        state = {
            "alert": _make_alert(cargo_value_eur="180000"),
            "cargo_manifest": {"cargo": "pharmaceutical", "value_eur": 180000},
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await investigate_node(state, llm=mock_llm)

        assert result["financial_risk"] is not None
        assert result["financial_risk"] > 0


# ── Escalation Node ─────────────────────────────────────────────────────────


class TestEscalationNode:
    """Memory-aware escalation: recurring pattern -> maintenance recommendation."""

    async def test_escalate_sets_pattern_detected(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            escalate_maintenance_node,
        )

        state = {
            "alert": _make_alert(truck_id="truck-4521"),
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": [
                {"alert_type": "temperature_spike", "timestamp": "2026-03-01"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-05"},
                {"alert_type": "temperature_spike", "timestamp": "2026-03-09"},
            ],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await escalate_maintenance_node(state)

        assert result["pattern_detected"] is not None
        assert "recurring" in result["pattern_detected"].lower()
        assert result["action_plan"] is not None
        assert "maintenance" in result["action_plan"].lower()

    async def test_escalate_includes_occurrence_count(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            escalate_maintenance_node,
        )

        state = {
            "alert": _make_alert(truck_id="truck-4521"),
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "action_plan": None,
            "notifications": [],
            "truck_history": [
                {"alert_type": "temperature_spike"} for _ in range(5)
            ],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await escalate_maintenance_node(state)

        # Should mention the count in the action plan
        assert "5" in result["action_plan"] or "five" in result["action_plan"].lower()


# ── Write Memory Node ────────────────────────────────────────────────────────


class TestWriteMemoryNode:
    """Post-resolution: write back what the agent learned."""

    async def test_write_memory_calls_store(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            write_memory_node,
        )

        mock_memory = AsyncMock()

        state = {
            "alert": _make_alert(),
            "action_plan": "Diverted to Zurich cold storage",
            "pattern_detected": None,
            "truck_history": [],
            "known_patterns": [],
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "notifications": [],
        }

        await write_memory_node(state, memory_store=mock_memory)

        mock_memory.write_back.assert_called_once()

    async def test_write_memory_with_pattern_includes_pattern(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            write_memory_node,
        )

        mock_memory = AsyncMock()

        state = {
            "alert": _make_alert(truck_id="truck-4521"),
            "action_plan": "Maintenance alert: pull from service",
            "pattern_detected": "recurring_refrigeration_failure",
            "truck_history": [{"alert_type": "temperature_spike"}] * 3,
            "known_patterns": [],
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "notifications": [],
        }

        await write_memory_node(state, memory_store=mock_memory)

        call_kwargs = mock_memory.write_back.call_args[1]
        assert call_kwargs["pattern_detected"] == "recurring_refrigeration_failure"


# ── Notify Node ──────────────────────────────────────────────────────────────


class TestNotifyNode:
    """Generate notifications for driver and dispatch."""

    async def test_notify_creates_notifications(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            notify_node,
        )

        state = {
            "alert": _make_alert(),
            "action_plan": "Divert to Zurich cold storage",
            "notifications": [],
            "cargo_manifest": None,
            "financial_risk": 27000.0,
            "nearest_facility": {"name": "CS-CH-ZH-04", "city": "Zurich"},
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await notify_node(state)

        assert len(result["notifications"]) >= 1
        assert any("driver" in n.get("target", "").lower() for n in result["notifications"])

    async def test_notify_includes_action_plan(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            notify_node,
        )

        state = {
            "alert": _make_alert(),
            "action_plan": "Divert to Munich cold storage immediately",
            "notifications": [],
            "cargo_manifest": None,
            "financial_risk": None,
            "nearest_facility": None,
            "truck_history": [],
            "known_patterns": [],
            "pattern_detected": None,
        }

        result = await notify_node(state)

        # At least one notification should reference the action plan
        all_messages = " ".join(n.get("message", "") for n in result["notifications"])
        assert "divert" in all_messages.lower() or "munich" in all_messages.lower()


# ── Full Graph Build ─────────────────────────────────────────────────────────


class TestGraphBuild:
    """Test that the graph can be constructed and compiled."""

    def test_graph_compiles(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            build_fleet_response_graph,
        )

        mock_memory = AsyncMock()
        mock_llm = AsyncMock()

        graph = build_fleet_response_graph(
            memory_store=mock_memory,
            llm=mock_llm,
        )

        compiled = graph.compile()
        assert compiled is not None

    def test_graph_has_expected_nodes(self):
        from apps.api.src.domains.logicore.graphs.fleet_response_graph import (
            build_fleet_response_graph,
        )

        mock_memory = AsyncMock()
        mock_llm = AsyncMock()

        graph = build_fleet_response_graph(
            memory_store=mock_memory,
            llm=mock_llm,
        )

        node_names = set(graph.nodes.keys())
        expected = {
            "memory_lookup",
            "investigate",
            "escalate_maintenance",
            "write_memory",
            "notify",
        }
        assert expected <= node_names, f"Missing nodes: {expected - node_names}"
