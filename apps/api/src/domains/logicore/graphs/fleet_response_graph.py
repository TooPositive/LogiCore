"""LangGraph fleet response graph -- anomaly investigation workflow.

Nodes:
  memory_lookup -> route_by_memory (conditional) ->
    investigate (normal path) OR escalate_maintenance (recurring pattern) ->
    write_memory -> notify

Memory-aware routing: if the truck has 2+ similar alerts in recent history,
skip full investigation and escalate directly to maintenance recommendation.
This saves EUR 0.017/alert (GPT-5.2 vs GPT-5-mini) and gets to the right
answer faster.

Dependencies (memory_store, llm) are injected via build_fleet_response_graph()
and captured in closures -- the graph nodes themselves are pure functions of state.
"""

from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

# Recurring pattern threshold: 2+ previous similar alerts = skip investigation
_RECURRING_THRESHOLD = 2


class FleetResponseState(TypedDict):
    """State for the fleet response workflow graph."""

    alert: dict[str, Any]
    cargo_manifest: dict[str, Any] | None
    financial_risk: float | None
    nearest_facility: dict[str, Any] | None
    action_plan: str | None
    notifications: list[dict[str, Any]]
    # Memory context
    truck_history: list[dict[str, Any]] | None
    known_patterns: list[Any] | None
    pattern_detected: str | None


# ── Node functions (testable independently) ──────────────────────────────────


async def memory_lookup_node(
    state: FleetResponseState,
    memory_store: Any,
) -> dict[str, Any]:
    """First node: retrieve memory context for this truck."""
    truck_id = state["alert"]["truck_id"]
    memory = await memory_store.lookup(truck_id)

    return {
        "truck_history": memory["truck_history"],
        "known_patterns": memory["known_patterns"],
    }


def route_by_memory(state: FleetResponseState) -> str:
    """Conditional edge: route based on memory context.

    If 2+ similar alerts exist in history, skip to escalation.
    Otherwise, do full investigation.
    """
    history = state.get("truck_history") or []
    alert_type = state["alert"].get("alert_type", "")

    similar = [h for h in history if h.get("alert_type") == alert_type]

    if len(similar) >= _RECURRING_THRESHOLD:
        return "escalate_maintenance"

    return "investigate"


async def investigate_node(
    state: FleetResponseState,
    llm: Any = None,
) -> dict[str, Any]:
    """Normal investigation: RAG lookup + risk assessment + LLM action plan."""
    alert = state["alert"]
    cargo = state.get("cargo_manifest") or {}

    # Calculate financial risk
    cargo_value = None
    if alert.get("cargo_value_eur"):
        try:
            cargo_value = float(alert["cargo_value_eur"])
        except (ValueError, TypeError):
            pass
    if cargo_value is None and cargo.get("value_eur"):
        try:
            cargo_value = float(cargo["value_eur"])
        except (ValueError, TypeError):
            pass

    financial_risk = cargo_value * 0.15 if cargo_value else None

    # Generate action plan via LLM
    action_plan = None
    if llm:
        prompt = (
            f"Fleet alert for truck {alert['truck_id']}: {alert.get('details', '')}. "
            f"Cargo: {cargo.get('cargo', 'unknown')}. "
            f"Value: EUR {cargo_value or 'unknown'}. "
            f"Generate a concise action plan including nearest cold-storage facility."
        )
        response = await llm.ainvoke(prompt)
        action_plan = response.content
    else:
        action_plan = (
            f"Alert on {alert['truck_id']}: {alert.get('details', '')}. "
            f"Recommend immediate investigation."
        )

    return {
        "financial_risk": financial_risk,
        "action_plan": action_plan,
    }


async def escalate_maintenance_node(
    state: FleetResponseState,
) -> dict[str, Any]:
    """Memory-aware escalation: recurring pattern -> maintenance recommendation.

    Skips full investigation because the pattern is already known.
    Uses GPT-5-mini (EUR 0.003) instead of GPT-5.2 (EUR 0.02).
    """
    alert = state["alert"]
    history = state.get("truck_history") or []
    alert_type = alert.get("alert_type", "unknown")

    similar_count = len([h for h in history if h.get("alert_type") == alert_type])
    total_count = similar_count + 1  # including current alert

    pattern_name = f"recurring_{alert_type}"

    action_plan = (
        f"MAINTENANCE ALERT: {alert['truck_id']} has {total_count} "
        f"{alert_type} anomalies in recent history. "
        f"Recommend: pull from service for inspection. "
        f"Estimated repair: EUR 2,500. "
        f"Estimated loss if ignored: EUR 180,000 per incident."
    )

    return {
        "pattern_detected": pattern_name,
        "action_plan": action_plan,
    }


async def write_memory_node(
    state: FleetResponseState,
    memory_store: Any,
) -> dict[str, Any]:
    """Post-resolution: write back what the agent learned."""
    alert = state["alert"]
    history = state.get("truck_history") or []
    alert_type = alert.get("alert_type", "unknown")

    similar_count = len([h for h in history if h.get("alert_type") == alert_type])

    await memory_store.write_back(
        truck_id=alert["truck_id"],
        alert_type=alert_type,
        severity=alert.get("severity", "medium"),
        action_taken=state.get("action_plan", "No action plan generated"),
        pattern_detected=state.get("pattern_detected"),
        occurrence_count=similar_count + 1,
    )

    return {}


async def notify_node(state: FleetResponseState) -> dict[str, Any]:
    """Generate notifications for driver and dispatch."""
    alert = state["alert"]
    action_plan = state.get("action_plan", "No action plan available")

    notifications = [
        {
            "target": "driver",
            "truck_id": alert["truck_id"],
            "message": f"Alert: {alert.get('details', 'Anomaly detected')}. Action: {action_plan}",
            "severity": alert.get("severity", "medium"),
            "timestamp": datetime.now(UTC).isoformat(),
        },
        {
            "target": "dispatch",
            "truck_id": alert["truck_id"],
            "message": (
                f"Fleet alert on {alert['truck_id']}: {alert.get('details', '')}. "
                f"Financial risk: EUR {state.get('financial_risk', 'N/A')}. "
                f"Action plan: {action_plan}"
            ),
            "severity": alert.get("severity", "medium"),
            "timestamp": datetime.now(UTC).isoformat(),
        },
    ]

    return {"notifications": notifications}


# ── Graph Builder ────────────────────────────────────────────────────────────


def build_fleet_response_graph(
    memory_store: Any = None,
    llm: Any = None,
) -> StateGraph:
    """Build the fleet response LangGraph state machine.

    Args:
        memory_store: MemoryStore instance for 3-tier memory.
        llm: LLM for investigation action plans.

    Returns:
        StateGraph (not compiled -- caller compiles with optional checkpointer).
    """

    async def _memory_lookup(state: FleetResponseState) -> dict[str, Any]:
        return await memory_lookup_node(state, memory_store=memory_store)

    async def _investigate(state: FleetResponseState) -> dict[str, Any]:
        return await investigate_node(state, llm=llm)

    async def _escalate(state: FleetResponseState) -> dict[str, Any]:
        return await escalate_maintenance_node(state)

    async def _write_memory(state: FleetResponseState) -> dict[str, Any]:
        return await write_memory_node(state, memory_store=memory_store)

    async def _notify(state: FleetResponseState) -> dict[str, Any]:
        return await notify_node(state)

    graph = StateGraph(FleetResponseState)

    graph.add_node("memory_lookup", _memory_lookup)
    graph.add_node("investigate", _investigate)
    graph.add_node("escalate_maintenance", _escalate)
    graph.add_node("write_memory", _write_memory)
    graph.add_node("notify", _notify)

    graph.add_edge(START, "memory_lookup")
    graph.add_conditional_edges(
        "memory_lookup",
        route_by_memory,
        {
            "investigate": "investigate",
            "escalate_maintenance": "escalate_maintenance",
        },
    )
    graph.add_edge("investigate", "write_memory")
    graph.add_edge("escalate_maintenance", "write_memory")
    graph.add_edge("write_memory", "notify")
    graph.add_edge("notify", END)

    return graph
