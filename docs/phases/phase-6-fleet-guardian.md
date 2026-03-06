# Phase 6: "The Fleet Guardian" — Real-Time Streaming & Event-Driven AI

## Business Problem

A refrigerated truck carrying $200K in pharmaceuticals hits a temperature spike. The driver doesn't notice. The warehouse gets no alert. By the time anyone checks, the cargo is spoiled and the insurance claim is denied because there's no proof of when the anomaly started.

Batch processing checks temperature logs every 6 hours. By then, the damage is done.

**CTO pain**: "We have 10,000 trucks on the road. We need AI that reacts to anomalies in real-time — not after the fact. But we can't afford an LLM call for every GPS ping."

## Architecture

```
IoT Simulator → Kafka Topics
  ├── fleet.gps-pings (high volume: 10K msgs/sec)
  ├── fleet.temperature (medium volume: 1K msgs/sec)
  └── fleet.alerts (low volume: anomalies only)

Kafka Consumer (Python)
  → Anomaly Detector (rule-based + statistical)
    → IF anomaly detected:
        → Publish to fleet.alerts topic
        → Trigger LangGraph Agent:
            ├── RAG: cargo manifest lookup (what's on the truck?)
            ├── Risk Calculator: perishability + financial exposure
            ├── Action Planner: nearest cold-storage warehouse
            └── Alert Generator: driver notification + dispatch alert
    → IF normal:
        → Aggregate metrics (no LLM call — cost = $0)

Langfuse: cost per alert, false positive rate, response latency
Redis: cache repeated anomaly patterns
```

**Key design decisions**:
- Two-tier processing: rule-based filter first (cheap), LLM only on anomalies (expensive)
- Kafka for decoupling — simulator, detector, and agents are independent consumers
- Semantic caching prevents re-analyzing the same traffic jam GPS pattern
- Cost tracking per alert (not per message) — FinOps visibility

## Implementation Guide

### Prerequisites
- Phases 1-3 complete
- Kafka profile running: `make up-kafka`
- Mock telemetry data generator

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/infrastructure/kafka/__init__.py` | Package init |
| `apps/api/src/infrastructure/kafka/consumer.py` | Kafka consumer base class |
| `apps/api/src/infrastructure/kafka/producer.py` | Kafka producer helper |
| `apps/api/src/agents/guardian/anomaly_detector.py` | Rule-based + statistical anomaly detection |
| `apps/api/src/agents/guardian/fleet_agent.py` | LangGraph agent for anomaly response |
| `apps/api/src/graphs/fleet_response_graph.py` | LangGraph graph: RAG → risk calc → action plan |
| `apps/api/src/domain/telemetry.py` | GPSPing, TemperatureReading, FleetAlert models |
| `apps/api/src/api/v1/fleet.py` | GET /api/v1/fleet/status, /alerts endpoints |
| `scripts/telemetry_simulator.py` | Generates mock GPS + temperature Kafka events |
| `data/mock-telemetry/routes.json` | Predefined truck routes with anomaly injection points |
| `tests/integration/test_kafka_flow.py` | End-to-end Kafka → agent → alert test |
| `tests/unit/test_anomaly_detector.py` | Anomaly detection threshold tests |
| `apps/web/src/app/fleet/page.tsx` | Real-time fleet dashboard page |

### Technical Spec

**Kafka Topics**:
```
fleet.gps-pings:        { truck_id, lat, lng, speed, timestamp }
fleet.temperature:      { truck_id, sensor_id, temp_celsius, timestamp }
fleet.alerts:           { truck_id, alert_type, severity, details, timestamp }
```

**Anomaly Detection Rules**:
```python
# Tier 1: Rule-based (no LLM cost)
RULES = {
    "temperature_spike": lambda r: r.temp_celsius > r.threshold + 5,
    "gps_deviation": lambda r: haversine(r.position, r.expected_route) > 2.0,  # km
    "speed_anomaly": lambda r: r.speed > 120 or (r.speed == 0 and r.engine_on),
}

# Tier 2: Statistical (still no LLM)
# Z-score > 3 on rolling 1-hour window

# Tier 3: LLM agent (only on confirmed anomalies)
# Triggered via fleet.alerts topic
```

**LangGraph Fleet Response**:
```python
class FleetResponseState(TypedDict):
    alert: FleetAlert
    cargo_manifest: dict | None      # from RAG
    financial_risk: float | None      # calculated
    nearest_facility: dict | None     # from route DB
    action_plan: str | None           # LLM-generated
    notifications: list[dict]         # driver + dispatch alerts

graph = StateGraph(FleetResponseState)
graph.add_node("lookup_cargo", cargo_rag_lookup)
graph.add_node("assess_risk", risk_calculator)
graph.add_node("plan_action", action_planner)
graph.add_node("notify", alert_dispatcher)
```

### Success Criteria
- [ ] Telemetry simulator pushes 1K+ msgs/sec to Kafka topics
- [ ] Rule-based detector filters >95% of normal events (no LLM cost)
- [ ] Temperature spike triggers LangGraph agent within 2 seconds
- [ ] Agent looks up cargo manifest via RAG, assesses perishability
- [ ] Action plan includes nearest cold-storage facility
- [ ] Alert published to fleet.alerts topic and visible in dashboard
- [ ] Langfuse shows cost per alert (not per message)
- [ ] Semantic cache prevents re-analyzing identical anomaly patterns
- [ ] Kafka UI (port 8090) shows topic throughput and consumer lag

## LinkedIn Post Template

### Hook
"Batch processing is dead. Here's how I built an event-driven AI agent that resolves supply chain anomalies in under 2 seconds."

### Body
10,000 trucks. Refrigerated cargo. A temperature sensor spikes at 3 AM.

Old way: batch job checks logs at 6 AM. Cargo is spoiled. $200K loss.

New way: Kafka stream → anomaly detector (rule-based, zero LLM cost for normal events) → confirmed anomaly triggers LangGraph agent → agent checks cargo manifest via RAG → calculates financial risk → finds nearest cold-storage facility → dispatches driver alert.

Total response time: 1.8 seconds.

The trick: two-tier processing. 99% of telemetry data is normal GPS pings. Running those through an LLM would cost thousands per day. Instead, cheap rule-based filters handle the volume. LLM agents only activate on confirmed anomalies — maybe 50 per day.

Cost: $0.03 per anomaly response vs $3,000/day if you LLM-processed everything.

### Visual
Real-time fleet dashboard: map with truck positions, temperature gauges, alert timeline. Langfuse sidebar showing cost per alert.

### CTA
"Anyone else building event-driven AI systems? What's your throughput vs cost trade-off looking like?"

## Key Metrics to Screenshot
- Kafka UI: topic throughput, consumer lag, partition distribution
- Fleet dashboard: map with live truck positions and alert markers
- Langfuse: cost per alert breakdown (RAG + LLM components)
- Response latency histogram: trigger → alert dispatched
- Cost comparison: "LLM-everything" vs "two-tier" approach
