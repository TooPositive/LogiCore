# Phase 9: "The Fleet Guardian" — Real-Time Streaming & Event-Driven AI

## Business Problem

A refrigerated truck carrying $200K in pharmaceuticals hits a temperature spike. The driver doesn't notice. The warehouse gets no alert. By the time anyone checks, the cargo is spoiled and the insurance claim is denied because there's no proof of when the anomaly started.

Batch processing checks temperature logs every 6 hours. By then, the damage is done.

**CTO pain**: "We have 10,000 trucks on the road. We need AI that reacts to anomalies in real-time — not after the fact. But we can't afford an LLM call for every GPS ping."

## Real-World Scenario: LogiCore Transport

**Feature: Real-Time Fleet Monitoring Dashboard**

3 AM. Truck-4721 is on the Hamburg→Zurich route carrying €180,000 in pharmaceutical cargo for PharmaCorp AG (contract CTR-2024-001, temperature requirement: 2-8°C continuous). The refrigeration unit develops a fault.

**The timeline**:
- **03:00:00** — Temperature sensor reads 3.2°C (normal, setpoint 3.0°C)
- **03:00:15** — Kafka receives GPS ping #47,291 from truck-4721. Rule-based filter: speed 78 km/h, on expected route. Normal. No LLM call. Cost: €0.00
- **03:01:30** — Temperature reading: 6.1°C. Rule-based anomaly detector: >setpoint + 3°C. Alert triggered.
- **03:01:31** — Event published to `fleet.alerts` Kafka topic
- **03:01:32** — LangGraph Fleet Response agent activates:
  - RAG lookup: "Truck-4721 cargo manifest" → pharmaceutical, PharmaCorp AG, €180K value, 2-8°C required
  - Risk calculator: cargo value €180K × 15% late penalty = €27K penalty exposure. If spoiled: full €180K loss.
  - Action planner: nearest cold storage = CS-CH-ZH-04 (Zurich, 45 min away). Alternative: CS-DE-MU-02 (Munich, 2.5 hours back).
  - Alert: "URGENT: Truck-4721 temperature anomaly. Pharmaceutical cargo at risk. Divert to Zurich cold storage."
- **03:01:33.8** — Driver Hans Muller's phone buzzes. Dispatch dashboard lights up.

**Total response time**: 1.8 seconds from anomaly detection to driver alert.

**Cost efficiency**: 47,291 GPS pings processed today. LLM calls: 3 anomalies — 1 priority-1 (GPT-5.2, €0.02) + 2 priority-3 (GPT-5 nano, €0.0001 each). Total: €0.0202 for the day. If every ping triggered a GPT-5.2 call: €662/day.

**The dashboard**: Fleet map shows 50 trucks in real-time. Green dots = normal. Red pulse on truck-4721 = active alert. Click → temperature chart showing the spike. Alert timeline on the right.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Kafka event streaming | Live truck positions updating every 15 seconds | Real-time visibility, not 6-hour batch reports |
| Two-tier processing (rules first, LLM on anomalies) | Same monitoring quality, 99.99% lower AI cost | €0.02/day vs €662/day — makes real-time AI economically viable |
| LangGraph anomaly response agent | "Divert to Zurich cold storage" — actionable recommendation in 1.8s | From "something's wrong" to "here's what to do" before the driver even notices |
| Anomaly detector (statistical + rule-based) | Red dot on map when something goes wrong | No false alarms flooding the dashboard, no missed real events |
| Kafka topic architecture | Different alert types in separate streams | Fleet team sees temperature alerts, finance sees billing anomalies — each gets their own feed |

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

## Cost of Getting It Wrong

Operating cost: EUR 2.25/month. One missed temperature spike: EUR 207,000.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Slow drift undetected** | Temperature rises 3°C→9°C over 2 hours. Each 15-second reading is below +5°C threshold. Cargo spoils. | EUR 180,000 (cargo) + EUR 27,000 (penalty) = **EUR 207,000** | 1-2/year |
| **Alert fatigue** | 50+ false alerts during heatwave → dispatchers ignore alerts → real pharma alert missed | EUR 180,000+ (spoiled cargo due to ignored alert) | 1/year |
| **Kafka consumer lag** | 30-second delay on temperature event. Alert fires but GPS position is stale. Recommended facility is wrong. | EUR 5,000-180,000 (wrong facility → extended transit → worsened spoilage) | 1-2/year |
| **Wrong cargo manifest** | RAG returns wrong manifest (Phase 1 retrieval failure). Risk calculator treats EUR 180K pharma as EUR 20K general cargo. Alert priority downgraded P1→P3. | EUR 160,000 (difference between immediate response and delayed response) | 1-2/year |
| **Memory false pattern match** | Cross-session memory incorrectly flags one-off anomaly as recurring. Truck pulled from service unnecessarily. | EUR 3,240/day (lost revenue per truck out of service) | 2-3/month |

**The CTO line**: "One missed temperature spike on a PharmaCorp truck costs EUR 207,000. Our entire annual AI operating cost is EUR 27. The system exists to prevent that one event."

### The Slow Drift Problem (Most Expensive Failure Mode)

The rule-based threshold catches sudden spikes. It does NOT catch gradual degradation:

```
03:00:00  Truck-4721 temp: 3.1°C  ✅ Normal
03:15:00  Truck-4721 temp: 3.8°C  ✅ Normal
03:30:00  Truck-4721 temp: 4.5°C  ✅ Normal (but trending up)
03:45:00  Truck-4721 temp: 5.2°C  ✅ Normal (just above threshold? depends on config)
04:00:00  Truck-4721 temp: 6.1°C  ⚠️ ALERT (too late — damage started at 5°C)
04:30:00  Truck-4721 temp: 7.8°C  🚨 CRITICAL (cargo compromised)
05:00:00  Truck-4721 temp: 9.2°C  💀 TOTAL LOSS
```

**Required**: Rate-of-change anomaly detection alongside threshold. If temperature rises >0.5°C in 30 minutes consistently, alert BEFORE it crosses the threshold.

### Cross-Session Memory: Quantified Value

Without memory (stateless): truck-4721 has 3rd temperature spike this quarter. Agent recommends same action every time: divert to cold storage (EUR 2,000/diversion × 3 = EUR 6,000).

With memory (session-aware): agent detects pattern, escalates to maintenance recommendation. One repair: EUR 2,500. Saves EUR 3,500 AND prevents future incidents.

At 5% of 50-truck fleet having recurring issues (2-3 trucks): EUR 7,000-10,500 saved/year.

### Kafka Consumer Lag Tolerance

| Consumer Lag | Impact on Fleet Guardian | Acceptable? |
|---|---|---|
| <5 seconds | GPS position accurate, facility recommendation correct | Yes |
| 5-30 seconds | GPS may be stale, facility could be wrong by 1-2 km | Add staleness warning |
| 30-300 seconds | GPS definitely stale, re-fetch current position before acting | Must re-query |
| >5 minutes | Alert is operationally useless, trigger fresh telemetry request | Discard and re-query |

**Rule**: The Fleet Response agent must check `alert.timestamp` age before acting. If stale, request fresh GPS position before calculating nearest facility.

## AI Decision Tree: Anomaly Response Priority

```
Anomaly detected (rule-based, $0)
  ├─ Severity classifier (GPT-5 nano, ~€0.00002/classification)
  │   ├─ Cargo value > €100K + temperature anomaly → PRIORITY 1
  │   │   └─ Full investigation (GPT-5.2, ~€0.02/call) + HITL alert
  │   │       RAG: cargo manifest, contract terms, insurance coverage
  │   │       Action: nearest cold-storage, driver alert, dispatch escalation
  │   ├─ GPS deviation > 5km + active contract → PRIORITY 2
  │   │   └─ AI triage (GPT-5 mini, ~€0.003/call) → maybe escalate
  │   │       Check: planned detour? Traffic reroute? Theft risk?
  │   ├─ Speed anomaly, no high-value cargo → PRIORITY 3
  │   │   └─ Log + auto-notify driver (GPT-5 nano, ~€0.0001/call)
  │   │       Template response, minimal reasoning needed
  │   └─ Multiple alerts simultaneously → Priority queue by cargo value
  │       Process highest-value cargo first, batch low-priority
  └─ Cost cap: if monthly LLM spend > €X budget, downgrade triage to nano
      (configurable per-customer, default €500/mo)
```

### Cost-Per-Anomaly by Priority (2026 Models)

| Priority | Model Used | Input/1M | Output/1M | Avg Tokens/Call | Cost/Anomaly | Frequency |
|---|---|---|---|---|---|---|
| **P1** (high-value + temp) | GPT-5.2 | $1.75 | $14.00 | ~1,500 in / 500 out | **~€0.02** | ~2/day |
| **P2** (GPS deviation) | GPT-5 mini | $0.25 | $2.00 | ~800 in / 300 out | **~€0.003** | ~10/day |
| **P3** (speed, minor) | GPT-5 nano | $0.05 | $0.40 | ~200 in / 100 out | **~€0.0001** | ~40/day |
| **Classification** | GPT-5 nano | $0.05 | $0.40 | ~100 in / 20 out | **~€0.00002** | ~52/day |
| **Daily total** | | | | | **~€0.075** | ~52 anomalies |
| **Monthly total** | | | | | **~€2.25** | ~1,560 anomalies |

Compare: processing all 47K daily pings through GPT-5 mini would cost ~€140/day (€4,200/month). Two-tier saves **99.95%**.

### When NOT to Use LLM for Anomalies

Some anomaly types are better handled by pure rule-based logic — cheaper, faster, more deterministic:

| Anomaly Type | Why Rules Beat LLMs | Implementation |
|---|---|---|
| **Threshold checks** | "Temperature > 8°C" is a comparison, not reasoning. LLM adds latency and cost for zero benefit. | `if temp > threshold + margin: alert()` |
| **Heartbeat monitoring** | "No GPS ping in 5 minutes" is a timer, not a judgment call. | Dead-letter queue + timeout watchdog |
| **Known patterns** | Repeated traffic jam at the A7/A1 interchange every weekday 7-9 AM. Don't re-analyze what you already know. | Pattern cache with time/location keys |
| **Binary compliance checks** | "Is the driver's rest period > 11 hours?" — EU regulation 561/2006 has exact numbers. | Lookup table, no ambiguity |
| **Duplicate alerts** | Same truck, same anomaly type, within 5 minutes. Don't re-triage. | Dedup window per truck+alert_type |

**Rule of thumb**: If the decision can be expressed as `if X > Y then Z` with no context needed, skip the LLM. Use LLMs only when the response requires *contextual reasoning* — cargo value assessment, contract term interpretation, multi-factor risk calculation.

## Agentic Architecture: Cross-Session Agent Memory

Most agent demos are stateless — every invocation starts fresh. But a real fleet monitoring system needs agents that **remember context across workflow runs**.

### The Problem

Truck-4521 has had 3 temperature anomalies this month. Each time, the Fleet Response agent investigates from scratch: RAG lookup, risk assessment, action plan. It recommends "divert to nearest cold storage" every time. But the real issue isn't a one-off spike — it's a failing refrigeration unit. A human fleet manager would recognize the pattern: "This truck needs maintenance, not another diversion."

### Memory Architecture

```
┌─────────────────────────────────────────┐
│          Agent Memory Tiers             │
├─────────────────────────────────────────┤
│                                         │
│  Short-term (within workflow run)        │
│  ├─ LangGraph state (TypedDict)         │
│  ├─ Lives in: PostgreSQL checkpoint      │
│  ├─ Scope: single anomaly investigation │
│  └─ TTL: until workflow completes       │
│                                         │
│  Medium-term (across recent runs)       │
│  ├─ Redis: per-truck event history      │
│  │   Key: truck:{id}:anomalies          │
│  │   Value: last 30 days of anomalies   │
│  ├─ Scope: pattern detection            │
│  └─ TTL: 30 days sliding window        │
│                                         │
│  Long-term (persistent knowledge)       │
│  ├─ PostgreSQL: fleet_agent_memory      │
│  │   truck_id, pattern, action_taken,   │
│  │   outcome, learned_at                │
│  ├─ Scope: fleet-wide learnings         │
│  └─ TTL: indefinite (manual prune)     │
│                                         │
└─────────────────────────────────────────┘
```

### How It Changes the Agent's Behavior

**Without memory** (stateless):
```
Anomaly: truck-4521 temp spike (3rd this month)
→ RAG lookup: pharmaceutical cargo, €180K
→ Risk: HIGH
→ Action: "Divert to Zurich cold storage"
→ Cost: €0.02 (same investigation every time)
```

**With memory** (cross-session):
```
Anomaly: truck-4521 temp spike
→ Memory check: Redis lookup truck:4521:anomalies
→ Found: 2 previous temp anomalies (March 3, March 12)
→ Pattern match: "recurring_refrigeration_failure"
→ Escalation: SKIP normal triage, go directly to:
  "MAINTENANCE ALERT: truck-4521 refrigeration unit failing.
   3 anomalies in 25 days. Recommend: pull from service for inspection.
   Estimated repair: €2,500. Estimated loss if ignored: €180K cargo per incident."
→ Cost: €0.003 (GPT-5 mini — pattern was pre-identified, no deep investigation needed)
```

### Implementation

```python
class FleetResponseState(TypedDict):
    alert: FleetAlert
    cargo_manifest: dict | None
    financial_risk: float | None
    nearest_facility: dict | None
    action_plan: str | None
    notifications: list[dict]
    # NEW: memory context
    truck_history: list[dict] | None     # from Redis (medium-term)
    known_patterns: list[dict] | None    # from PostgreSQL (long-term)

async def memory_lookup(state: FleetResponseState) -> FleetResponseState:
    """First node in the graph — check what we already know."""
    truck_id = state["alert"]["truck_id"]

    # Medium-term: recent anomalies for this truck
    history = await redis.lrange(f"truck:{truck_id}:anomalies", 0, -1)
    state["truck_history"] = [json.loads(h) for h in history]

    # Long-term: known patterns for this truck
    patterns = await db.fetch(
        "SELECT * FROM fleet_agent_memory WHERE truck_id = $1 ORDER BY learned_at DESC LIMIT 5",
        truck_id,
    )
    state["known_patterns"] = patterns
    return state

def route_by_memory(state: FleetResponseState) -> str:
    """Conditional routing — skip investigation if pattern is known."""
    history = state.get("truck_history", [])
    alert_type = state["alert"]["alert_type"]

    # Same alert type, same truck, 3+ times in 30 days → known pattern
    similar = [h for h in history if h["alert_type"] == alert_type]
    if len(similar) >= 2:
        return "escalate_maintenance"  # skip normal triage

    return "investigate"  # normal flow

# Graph with memory-aware routing
graph = StateGraph(FleetResponseState)
graph.add_node("memory_lookup", memory_lookup)
graph.add_node("investigate", normal_investigation)
graph.add_node("escalate_maintenance", maintenance_escalation)
graph.add_conditional_edges("memory_lookup", route_by_memory)
```

### Memory Write-Back

After every resolved anomaly, the agent writes back what it learned:

```python
async def write_memory(state: FleetResponseState) -> FleetResponseState:
    truck_id = state["alert"]["truck_id"]

    # Medium-term: append to Redis history
    await redis.lpush(f"truck:{truck_id}:anomalies", json.dumps({
        "alert_type": state["alert"]["alert_type"],
        "severity": state["alert"]["severity"],
        "action_taken": state["action_plan"],
        "timestamp": datetime.utcnow().isoformat(),
    }))
    await redis.ltrim(f"truck:{truck_id}:anomalies", 0, 99)  # keep last 100

    # Long-term: if pattern detected, persist learning
    if state.get("pattern_detected"):
        await db.execute(
            "INSERT INTO fleet_agent_memory (truck_id, pattern, action_taken, outcome, learned_at) "
            "VALUES ($1, $2, $3, $4, NOW())",
            truck_id, state["pattern_detected"], state["action_plan"], "pending_verification",
        )
    return state
```

### Decision: What to Remember vs What to Forget

| Memory Type | Store | TTL | Why |
|---|---|---|---|
| Individual anomaly events | Redis list | 30 days | Pattern detection needs recent context, not all history |
| Confirmed patterns (recurring failure) | PostgreSQL | Indefinite | Fleet-wide learning, informs maintenance planning |
| One-off anomalies (traffic jam, weather) | Redis only | 7 days | Noise — don't pollute long-term memory |
| False positives | PostgreSQL | Indefinite | Improves future detection accuracy |
| Driver-specific context | NOT stored | — | Privacy — GDPR. Anomalies are about trucks, not people. |

**Cost of memory**: Redis storage for 50 trucks × 100 events = ~500KB. PostgreSQL for learned patterns = negligible. The memory system adds ~5ms latency (Redis lookup) to each anomaly response — worth it when it prevents a 5th unnecessary cold-storage diversion.

## LinkedIn Post Template

### Hook
"Batch processing is dead. Here's how I built an event-driven AI agent that resolves supply chain anomalies in under 2 seconds."

### Body
10,000 trucks. Refrigerated cargo. A temperature sensor spikes at 3 AM.

Old way: batch job checks logs at 6 AM. Cargo is spoiled. $200K loss.

New way: Kafka stream → anomaly detector (rule-based, zero LLM cost for normal events) → confirmed anomaly triggers LangGraph agent → agent checks cargo manifest via RAG → calculates financial risk → finds nearest cold-storage facility → dispatches driver alert.

Total response time: 1.8 seconds.

The trick: two-tier processing. 99% of telemetry data is normal GPS pings. Running those through an LLM would cost thousands per day. Instead, cheap rule-based filters handle the volume. LLM agents only activate on confirmed anomalies — maybe 50 per day.

Cost: €0.02 per high-priority anomaly response (GPT-5.2) vs €662/day if you LLM-processed every GPS ping.

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
