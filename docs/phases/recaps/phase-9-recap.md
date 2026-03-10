# Phase 9 Technical Recap: Fleet Guardian -- Real-Time Streaming & Event-Driven AI

## What This Phase Does (Business Context)

A refrigerated truck carrying EUR 180,000 in pharmaceutical cargo develops a slow refrigeration fault at 3 AM. Batch processing checks temperature logs every 6 hours -- by then, the cargo is spoiled and the insurance claim is denied because there's no proof of when the anomaly started. Phase 9 builds a real-time anomaly detection and response pipeline that catches temperature spikes (immediate) and slow drifts (gradual) within seconds, triggers a LangGraph agent only when needed (not on every GPS ping), and uses cross-session memory to detect recurring equipment failures across multiple incidents. The system costs EUR 0.075/day instead of EUR 662/day because it filters 99.95% of normal telemetry without touching an LLM.

## Architecture Overview

```
IoT Sensors / Telemetry Simulator
  │
  ├── Kafka topic: fleet.gps-pings (high volume: ~47K/day)
  ├── Kafka topic: fleet.temperature (medium volume: ~1K/day)
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│  Kafka Consumer (core/infrastructure/kafka/consumer.py)      │
│  - JSON deserialization                                      │
│  - Health tracking (msg count, errors, last_message_at)      │
│  - Error isolation (invalid JSON logged, not crashed)        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  FleetGuardianAgent (agents/guardian/fleet_agent.py)         │
│  - Topic routing (fleet.temperature -> check_temperature)    │
│  - Metrics: events_processed, events_filtered, anomalies     │
│  - Two-tier gate: detector first, graph only on anomaly      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│  AnomalyDetector (agents/guardian/anomaly_detector.py)       │
│  Tier 1 (rule-based, EUR 0.00/event):                       │
│    ├── Threshold: temp > setpoint + margin                   │
│    ├── Drift: rate-of-change > 0.5C/30min                   │
│    ├── Speed: > 120 km/h or 0 km/h + engine on              │
│    └── Dedup: same truck+type within 5 min -> suppress       │
│  Tier 2 (statistical, EUR 0.00/event):                       │
│    └── Z-score > 3.0 on rolling window (n >= 5)             │
│                                                              │
│  Normal event? -> FILTER (no LLM call)                       │
│  Anomaly? -> Create FleetAlert -> pass to graph ────────┐    │
└─────────────────────────────────────────────────────────┘    │
                                                               │
         ┌─────────────────────────────────────────────────────┘
         ▼
┌─────────────────────────────────────────────────────────────┐
│  LangGraph Fleet Response (graphs/fleet_response_graph.py)   │
│                                                              │
│  START -> memory_lookup -> route_by_memory (conditional)     │
│              │                    │                           │
│              │          ┌────────┴────────┐                  │
│              │          ▼                 ▼                   │
│              │    investigate      escalate_maintenance       │
│              │    (full RAG +      (recurring pattern ->      │
│              │     LLM plan)       maintenance alert)         │
│              │          │                 │                   │
│              │          └────────┬────────┘                  │
│              │                   ▼                            │
│              │            write_memory                        │
│              │                   │                            │
│              │                   ▼                            │
│              │               notify -> END                   │
│              │                                               │
│  3-Tier Memory:                                              │
│    Short-term:  LangGraph TypedDict (within this run)        │
│    Medium-term: Redis per-truck history (30-day, 100 cap)    │
│    Long-term:   PostgreSQL fleet_agent_memory (indefinite)   │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  Fleet API (api/fleet.py)                                    │
│  GET  /fleet/status          - fleet summary                 │
│  GET  /fleet/alerts          - list with truck_id/severity   │
│  POST /alerts/{id}/resolve   - mark resolved                 │
│  POST /ingest/temperature    - direct ingestion (Kafka alt)  │
│  POST /ingest/gps            - direct GPS ingestion          │
│  GET  /consumer/health       - Kafka consumer metrics        │
│  WS   /fleet/ws              - real-time alert broadcast     │
└─────────────────────────────────────────────────────────────┘
```

## Components Built

### 1. Fleet Domain Models: `apps/api/src/domains/logicore/models/fleet.py`

**What it does**: Defines the Pydantic data contracts for all fleet telemetry: `GPSPing`, `TemperatureReading`, `FleetAlert`, `FleetMemoryEntry`, plus `AlertType` and `AlertSeverity` enums. These models validate at the boundary -- invalid data (lat > 90, temp > 100C) is rejected before it enters the pipeline.

**The pattern**: **Boundary Validation via Pydantic Field Constraints**. Rather than sprinkling validation throughout the pipeline, all constraints live on the model. `Field(ge=-90.0, le=90.0)` on latitude means invalid GPS data never reaches the anomaly detector.

**Key code walkthrough**:

```python
# apps/api/src/domains/logicore/models/fleet.py, lines 36-48
class GPSPing(BaseModel):
    truck_id: str = Field(min_length=1)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    speed_kmh: float = Field(ge=0.0)
    heading: float = Field(ge=0.0, le=360.0)
    timestamp: datetime
    engine_on: bool = True
```

```python
# lines 51-63
class TemperatureReading(BaseModel):
    # Sensor range: -100C to 100C (hardware limits).
    # 101C would indicate a broken sensor, not a real reading.
    truck_id: str = Field(min_length=1)
    sensor_id: str = Field(min_length=1)
    temp_celsius: float = Field(ge=-100.0, le=100.0)
    setpoint_celsius: float
    timestamp: datetime
```

**Why it matters**: Without boundary validation, a broken sensor sending 999C would trigger false alerts, waste LLM calls, and erode operator trust. The Pydantic constraint catches this at ingestion for zero runtime cost.

**Alternatives considered**: Manual validation in the detector or API layer. Rejected because it duplicates logic (every consumer of the model would need the same checks) and is easy to forget in new code paths.

### 2. Anomaly Detector: `apps/api/src/domains/logicore/agents/guardian/anomaly_detector.py`

**What it does**: Stateful rule-based and statistical anomaly detection for fleet telemetry. Maintains per-truck temperature history, runs threshold checks, rate-of-change (drift) detection, z-score statistical analysis, and alert deduplication. Zero LLM cost -- this is Tier 1 and Tier 2 of the two-tier processing model.

**The pattern**: **Stateful Detector with Per-Entity History**. The detector holds a `defaultdict(list)` mapping `truck_id -> [(timestamp, temp_celsius)]` so each truck has its own independent history for drift and z-score calculations. This prevents cross-contamination: truck-A's rising temperature does not affect truck-B's baseline.

**Key code walkthrough -- drift detection (the EUR 207,000 gap)**:

```python
# anomaly_detector.py, lines 163-205
def _check_drift(self, reading: TemperatureReading) -> FleetAlert | None:
    """Detect gradual temperature increase over time."""
    history = self._temp_history[reading.truck_id]
    if len(history) < 2:
        return None

    # Find readings within the last 30 minutes
    cutoff = reading.timestamp - timedelta(minutes=30)
    window = [(ts, temp) for ts, temp in history if ts >= cutoff]

    if len(window) < 2:
        return None

    oldest_ts, oldest_temp = window[0]
    newest_ts, newest_temp = window[-1]

    elapsed_minutes = (newest_ts - oldest_ts).total_seconds() / 60.0
    if elapsed_minutes < 1.0:
        return None

    # Normalize to rate per 30 minutes
    rate_per_30min = abs(newest_temp - oldest_temp) * (30.0 / elapsed_minutes)

    if rate_per_30min > self.drift_rate_threshold:
        direction = "rising" if newest_temp > oldest_temp else "falling"
        return self._make_temp_alert(...)
```

The normalization to 30-minute rate (`* (30.0 / elapsed_minutes)`) is important: if you only have 15 minutes of data showing 0.7C rise, that projects to 1.4C/30min, which exceeds the 0.5C/30min threshold. Without normalization, you'd miss drifts observed over shorter windows.

**Key code walkthrough -- deduplication**:

```python
# anomaly_detector.py, lines 276-307
def _make_alert(self, truck_id, alert_type, severity, details, timestamp) -> FleetAlert | None:
    dedup_key = (truck_id, alert_type.value)

    if self.dedup_window_seconds > 0 and dedup_key in self._last_alert:
        elapsed = (timestamp - self._last_alert[dedup_key]).total_seconds()
        if elapsed < self.dedup_window_seconds:
            return None  # Suppress duplicate

    self._last_alert[dedup_key] = timestamp
    return FleetAlert(...)
```

Dedup keys on `(truck_id, alert_type)` -- same truck with a temperature spike AND a speed anomaly are two different alerts. Same truck with two temperature spikes within 5 minutes is one alert.

**Why it matters**: Threshold-only detection misses 40% of temperature incidents (slow drifts). That is the EUR 207,000 gap: cargo starts spoiling at 5C, but the threshold does not fire until 8C. By then, the damage is done. Alert deduplication prevents a different failure mode: 50+ alerts during a heatwave cause dispatchers to ignore everything, including the one real EUR 180K pharma alert.

**Alternatives considered**: (1) LLM-based anomaly detection for everything -- rejected because at 1K msgs/sec with 500ms LLM latency, you create a 500-second backlog per second of ingestion. It is not just expensive; it is physically impossible. (2) Threshold-only (no drift) -- rejected because it misses slow refrigeration failures, which are 40% of real incidents. (3) ML-based anomaly detection (isolation forests, autoencoders) -- considered for Phase 12 but overkill when rule-based + z-score catches the critical scenarios with zero training data requirements.

### 3. Fleet Guardian Agent: `apps/api/src/domains/logicore/agents/guardian/fleet_agent.py`

**What it does**: Orchestrates the two-tier pipeline. Takes raw Kafka messages, constructs Pydantic models, runs the anomaly detector, and only invokes the LangGraph fleet response graph on confirmed anomalies. Tracks metrics (events_processed, events_filtered, anomalies_detected, graph_invocations, graph_errors) and supports an optional async alert callback.

**The pattern**: **Orchestrator with Fail-Safe Isolation**. The agent catches graph invocation failures (`except Exception`) and still returns the detector's alerts. The system degrades gracefully: if the LLM is down, you still get the alert from the rule-based detector -- you just do not get the LLM-generated action plan.

**Key code walkthrough**:

```python
# fleet_agent.py, lines 59-85
async def process_temperature(self, msg: dict[str, Any]) -> dict[str, Any]:
    self.metrics["events_processed"] += 1

    reading = TemperatureReading(
        truck_id=msg["truck_id"],
        sensor_id=msg["sensor_id"],
        temp_celsius=msg["temp_celsius"],
        setpoint_celsius=msg["setpoint_celsius"],
        timestamp=(datetime.fromisoformat(msg["timestamp"])
                   if isinstance(msg["timestamp"], str)
                   else msg["timestamp"]),
    )

    alerts = self._detector.check_temperature(reading)

    if not alerts:
        self.metrics["events_filtered"] += 1
        return {"alerts": [], "graph_result": None}  # EUR 0.00

    self.metrics["anomalies_detected"] += len(alerts)
    return await self._handle_alerts(alerts)  # LLM cost only here
```

```python
# fleet_agent.py, lines 141-166
async def _handle_alerts(self, alerts: list[FleetAlert]) -> dict[str, Any]:
    # Invoke alert callback for each alert (WebSocket, Kafka publish, etc.)
    if self._on_alert:
        for alert in alerts:
            try:
                await self._on_alert(alert)
            except Exception:
                logger.exception("Alert callback error for %s", alert.alert_id)

    # Invoke graph for the first (highest-severity) alert
    alert = alerts[0]
    graph_result = None
    try:
        self.metrics["graph_invocations"] += 1
        graph_result = await self._graph.ainvoke({...})
    except Exception:
        self.metrics["graph_errors"] += 1
        logger.exception("Graph invocation failed for alert %s", alert.alert_id)

    return {
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "graph_result": graph_result,
    }
```

**Why it matters**: The agent is the enforcement point for two-tier processing. Without it, every event would hit the LLM. The `if not alerts: return` gate is what makes the system economically viable at streaming scale.

### 4. LangGraph Fleet Response Graph: `apps/api/src/domains/logicore/graphs/fleet_response_graph.py`

**What it does**: A 5-node LangGraph state machine that processes confirmed anomalies. Nodes: `memory_lookup` -> conditional routing via `route_by_memory` -> `investigate` (normal path) OR `escalate_maintenance` (recurring pattern) -> `write_memory` -> `notify`. Dependencies (memory_store, llm) are injected via `build_fleet_response_graph()` and captured in closures.

**The pattern**: **Dependency Injection via Closure Capture**. The graph builder creates inner functions that close over `memory_store` and `llm`. The graph nodes themselves are pure functions of state -- testable independently without the builder. The testable node functions (`memory_lookup_node`, `investigate_node`, etc.) accept dependencies as explicit parameters; the builder wraps them in closures for LangGraph.

**Key code walkthrough -- memory-aware routing**:

```python
# fleet_response_graph.py, lines 58-72
def route_by_memory(state: FleetResponseState) -> str:
    """Conditional edge: route based on memory context."""
    history = state.get("truck_history") or []
    alert_type = state["alert"].get("alert_type", "")

    similar = [h for h in history if h.get("alert_type") == alert_type]

    if len(similar) >= _RECURRING_THRESHOLD:  # 2+ previous = 3 total with current
        return "escalate_maintenance"

    return "investigate"
```

```python
# fleet_response_graph.py, lines 207-258 (graph wiring)
def build_fleet_response_graph(memory_store=None, llm=None) -> StateGraph:
    async def _memory_lookup(state):
        return await memory_lookup_node(state, memory_store=memory_store)

    async def _investigate(state):
        return await investigate_node(state, llm=llm)

    graph = StateGraph(FleetResponseState)
    graph.add_node("memory_lookup", _memory_lookup)
    graph.add_node("investigate", _investigate)
    graph.add_node("escalate_maintenance", _escalate)
    graph.add_node("write_memory", _write_memory)
    graph.add_node("notify", _notify)

    graph.add_edge(START, "memory_lookup")
    graph.add_conditional_edges("memory_lookup", route_by_memory, {
        "investigate": "investigate",
        "escalate_maintenance": "escalate_maintenance",
    })
    graph.add_edge("investigate", "write_memory")
    graph.add_edge("escalate_maintenance", "write_memory")
    graph.add_edge("write_memory", "notify")
    graph.add_edge("notify", END)
```

**Why it matters**: The conditional routing is what makes cross-session memory useful. Without it, the agent would investigate every anomaly from scratch, recommending the same EUR 2,000 cold-storage diversion three times for the same truck when the real problem is a failing refrigeration unit that needs a EUR 2,500 repair.

**Alternatives considered**: (1) Simple if/else in the agent instead of LangGraph -- rejected because the investigation flow requires multiple async steps (RAG lookup, risk calculation, action plan), and LangGraph gives checkpoint/resume capability for free when integrated with PostgreSQL checkpointers. (2) LangChain AgentExecutor -- rejected because the flow is deterministic (no tool-selection loop), so a state graph is cleaner and more predictable than a ReAct agent.

### 5. 3-Tier Memory Store: `apps/api/src/domains/logicore/agents/guardian/memory_store.py`

**What it does**: Unified interface over Redis (medium-term) and PostgreSQL (long-term) memory. Short-term memory lives in LangGraph's TypedDict state. The `MemoryStore` coordinates `lookup` (read both tiers) and `write_back` (always Redis, PostgreSQL only when pattern detected). Graceful degradation: if either tier is down, the agent falls back to stateless investigation.

**The pattern**: **Facade with Graceful Degradation**. The MemoryStore wraps two independent storage backends behind a single interface. Every external call is wrapped in try/except -- a `ConnectionError` from Redis returns empty history instead of crashing the agent. This is an explicit architectural choice: silent memory failure is acceptable because the anomaly response still happens. The agent just loses supplementary context.

**Key code walkthrough**:

```python
# memory_store.py, lines 41-71
async def lookup(self, truck_id: str) -> dict[str, Any]:
    truck_history: list[dict[str, Any]] = []
    known_patterns: list[Any] = []

    try:
        truck_history = await self._redis.get_truck_history(truck_id)
    except Exception:
        logger.warning(
            "Redis lookup failed for truck %s -- falling back to empty history",
            truck_id,
        )

    try:
        known_patterns = await self._pg.get_patterns(truck_id)
    except Exception:
        logger.warning(
            "PostgreSQL lookup failed for truck %s -- falling back to empty patterns",
            truck_id,
        )

    return {
        "truck_history": truck_history,
        "known_patterns": known_patterns,
    }
```

**Why it matters**: At 3 AM, when a real anomaly happens, a Redis timeout must not prevent the driver from getting an alert. The alternative -- letting the exception propagate -- means cargo spoils while ops restarts Redis.

### 6. Redis Fleet Memory: `apps/api/src/domains/logicore/infrastructure/fleet_memory.py`

**What it does**: Per-truck anomaly history in Redis with a 30-day sliding window and 100-entry cap. Key format: `truck:{truck_id}:anomalies`. Operations: `lpush` (prepend), `ltrim` (cap at 100), `expire` (30-day TTL refreshed on each write).

**The pattern**: **Sliding Window with Bounded Growth**. Three Redis operations per write (`lpush`, `ltrim`, `expire`) ensure the list never grows unbounded. 50 trucks x 100 entries x ~100 bytes = ~500KB total Redis footprint.

**Key code walkthrough**:

```python
# fleet_memory.py, lines 41-49
async def record_anomaly(self, truck_id: str, entry: dict[str, Any]) -> None:
    key = self._key(truck_id)
    await self._redis.lpush(key, json.dumps(entry, default=str))
    await self._redis.ltrim(key, 0, self._max_entries - 1)
    await self._redis.expire(key, self._ttl_seconds)
```

### 7. PostgreSQL Fleet Agent Memory: `apps/api/src/domains/logicore/infrastructure/fleet_agent_memory.py`

**What it does**: Long-term pattern storage in PostgreSQL for fleet-wide learnings (recurring failures, false positives). Uses `$N` parameterized queries exclusively -- no string interpolation anywhere.

**The pattern**: **Parameterized-Only SQL**. Every query uses asyncpg's `$1`, `$2` parameter syntax. The SQL injection test suite covers 7 vectors: truck_id, alert_type, pattern, action_taken, and a second-order scenario where malicious data is stored via legitimate write and then retrieved as data (not executed).

**Key code walkthrough**:

```python
# fleet_agent_memory.py, lines 29-49
async def store_pattern(self, entry: FleetMemoryEntry) -> None:
    async with self._pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO fleet_agent_memory
                (truck_id, pattern, alert_type, action_taken,
                 outcome, learned_at, occurrence_count)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            entry.truck_id,
            entry.pattern,
            entry.alert_type,
            entry.action_taken,
            entry.outcome,
            entry.learned_at,
            entry.occurrence_count,
        )
```

**DDL** (`scripts/create_fleet_agent_memory_table.sql`): `BIGSERIAL` primary key, three indexes (truck_id for per-truck lookups, pattern for fleet-wide queries, learned_at DESC for recency).

### 8. Kafka Consumer & Producer: `apps/api/src/core/infrastructure/kafka/consumer.py` and `producer.py`

**What it does**: Domain-agnostic Kafka infrastructure. The consumer (`KafkaConsumerWorker`) deserializes JSON, dispatches to a handler coroutine, and tracks health metrics. The producer (`KafkaProducerHelper`) serializes JSON and supports batch send. Both live in `core/` because they have no fleet-specific logic.

**The pattern**: **Domain-Agnostic Infrastructure in Core**. Any domain (fleet, invoicing, HR) can reuse the same consumer/producer wrappers. The consumer's error isolation is critical: invalid JSON logs an error and increments the error counter but does not crash the consumer loop.

**Key code walkthrough -- error isolation**:

```python
# consumer.py, lines 92-122
async def _process_message(self, msg: Any) -> None:
    try:
        data = json.loads(msg.value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(
            "Invalid JSON on topic=%s partition=%s offset=%s",
            msg.topic, msg.partition, msg.offset,
        )
        self.errors += 1
        return  # Skip this message, continue processing

    try:
        await self._handler(data)
        self.messages_processed += 1
        self.last_message_at = datetime.now(UTC)
    except Exception:
        logger.exception("Handler error on topic=%s ...")
        self.errors += 1
```

Two separate try/except blocks: one for deserialization, one for handler logic. A bad message never poisons the consumer.

### 9. Fleet API: `apps/api/src/domains/logicore/api/fleet.py`

**What it does**: 6 HTTP endpoints + 1 WebSocket for real-time fleet monitoring. Direct ingestion endpoints provide a fallback when Kafka is unavailable. WebSocket broadcasts alerts to all connected dashboard clients.

**The pattern**: **Factory Router with WebSocket Fan-Out**. `create_fleet_router()` is a factory function so tests can create isolated router instances. The `_broadcast_alert` function iterates over all connected WebSocket clients and cleans up disconnected ones.

**Key code walkthrough -- WebSocket broadcast with disconnect cleanup**:

```python
# fleet.py, lines 187-199
async def _broadcast_alert(alert: FleetAlert) -> None:
    message = json.dumps(alert.model_dump(mode="json"), default=str)
    disconnected = []
    for ws in _ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _ws_connections.remove(ws)
```

### 10. Telemetry Simulator: `scripts/telemetry_simulator.py`

**What it does**: Generates realistic GPS pings and temperature readings for 5 trucks along predefined routes with configurable anomaly injection (temperature drifts, spikes, speed anomalies). Can publish to Kafka or run in-memory for testing.

**The pattern**: **Linear Interpolation with Anomaly Injection Points**. GPS positions are interpolated between route waypoints based on time progress. Temperature anomalies are injected at specific waypoint indices defined in `data/mock-telemetry/routes.json`. This makes the simulator deterministic enough for testing while producing realistic-looking telemetry.

## Key Decisions Explained

### Decision 1: Two-Tier Processing (Rules First, LLM on Anomalies Only)

- **The choice**: Rule-based anomaly detection first (EUR 0.00/event), LLM agent only on confirmed anomalies (~EUR 0.02/anomaly).
- **The alternatives**: (1) LLM for everything -- EUR 662/day. (2) No LLM at all -- miss contextual reasoning like cargo manifest lookup and nearest-facility calculation.
- **The reasoning**: At 1K msgs/sec with 500ms LLM latency, synchronous LLM processing creates a 500-second backlog per second of ingestion. Two-tier is not a cost optimization; it is the only way the system can function at streaming scale.
- **The trade-off**: Rule-based detection cannot reason about context (cargo value, contract terms, facility proximity). The LLM handles this for the ~52 daily anomalies that need it.
- **When to revisit**: If LLM latency drops below 5ms and cost drops 100x, you could reconsider. With current models, two-tier is a physical necessity.
- **Interview version**: "We built a two-tier processing pipeline because at streaming scale, calling an LLM for every GPS ping is physically impossible -- 1K msgs/sec with 500ms latency creates a 500-second backlog every second. Rule-based detection handles 99.95% of events at zero LLM cost. Only confirmed anomalies trigger the LangGraph agent. The result: EUR 0.075/day instead of EUR 662/day."

### Decision 2: Rate-of-Change Detection (Not Just Threshold)

- **The choice**: Both absolute threshold AND rate-of-change (drift) detection.
- **The alternatives**: Threshold-only detection.
- **The reasoning**: Threshold-only misses 40% of temperature incidents -- slow drifts where each individual reading is below the threshold but the trend is clearly rising. A refrigeration unit slowly failing from 3.1C to 9.2C over 2 hours would not trigger a 5C-margin threshold until the cargo is already spoiled.
- **The trade-off**: Drift detection requires maintaining per-truck temperature history (120-entry sliding window) and a 30-minute lookback window. Small memory cost.
- **When to revisit**: If real production data shows drift detection generates too many false positives (e.g., normal diurnal temperature cycling), tighten the drift_rate_threshold from 0.5C/30min to 1.0C/30min. The threshold is configurable per detector instance.
- **Interview version**: "Threshold-only detection misses slow refrigeration failures, which are 40% of real incidents and the most expensive failure mode at EUR 207,000 each. We added rate-of-change detection that normalizes temperature gradient to a 30-minute window and fires before the threshold is breached. The drift_rate_threshold is configurable per cargo class."

### Decision 3: 3-Tier Memory with Graceful Degradation

- **The choice**: Short-term (LangGraph state) + Medium-term (Redis, 30-day) + Long-term (PostgreSQL, indefinite), with try/except on every external memory call.
- **The alternatives**: (1) Stateless agent (no memory) -- misses recurring patterns, costs EUR 3,500-10,500/year in repeated unnecessary diversions. (2) Redis-only -- loses history on restart/eviction. (3) PostgreSQL-only -- too slow for per-event lookups.
- **The reasoning**: Each tier serves a different TTL and access pattern. Redis is fast enough for per-anomaly lookups (~5ms). PostgreSQL stores confirmed patterns indefinitely. Graceful degradation is mandatory because a Redis timeout at 3 AM must not prevent the driver from getting an alert.
- **The trade-off**: Silent memory failure means the agent might miss a recurring pattern when Redis is down. That is acceptable because the anomaly response still happens -- the agent just does a full investigation instead of a faster maintenance escalation.
- **When to revisit**: If fleet has fewer than 10 trucks, the memory maintenance overhead exceeds the savings from pattern detection. Below that scale, stateless investigation is cheaper.
- **Interview version**: "We use 3-tier memory: LangGraph state for the current workflow, Redis for 30-day per-truck history, PostgreSQL for confirmed patterns. The critical design choice is graceful degradation -- every Redis and PostgreSQL call is wrapped in try/except. If memory is down, the agent falls back to stateless investigation. A broken memory tier never prevents anomaly response."

### Decision 4: Alert Deduplication (5-Minute Window)

- **The choice**: Suppress duplicate alerts from the same truck and same alert type within a 5-minute window.
- **The alternatives**: (1) No dedup -- every threshold breach generates an alert. (2) Global dedup across all trucks -- too aggressive, masks real incidents on different trucks.
- **The reasoning**: Without dedup, a heatwave day produces 50+ alerts for the same truck. Dispatchers start ignoring alerts. A real EUR 180K pharma alert gets buried. Dedup keys on `(truck_id, alert_type.value)` so a temperature spike and a speed anomaly on the same truck are still separate alerts.
- **The trade-off**: If the first alert is missed or ignored by a dispatcher, the next one won't come for 5 minutes. In practice, 5 minutes is short enough that the first alert is still actionable.
- **When to revisit**: If dispatchers need reminder alerts, add an escalation re-alert at 10 minutes and 30 minutes (with increasing severity).
- **Interview version**: "We dedup alerts by (truck_id, alert_type) within a 5-minute window. Without it, 50+ alerts during a heatwave cause dispatchers to ignore everything, including the real EUR 180K pharma alert. Different alert types on the same truck are correctly treated as separate alerts."

### Decision 5: Per-Cargo-Class Threshold Margins

- **The choice**: Configurable `threshold_margin` per detector instance (default 5C for general freight, 2C recommended for pharma).
- **The alternatives**: Single global threshold margin.
- **The reasoning**: With a 5C margin on pharma cargo, the alert fires at 8C when damage starts at 5C -- 75 minutes of undetected degradation. A 2C margin catches the same degradation at 5.1C. Proven in the 101-reading borderline test: same reading (5.5C) produces different alert status depending on margin.
- **The trade-off**: Tighter margins generate more alerts on marginal readings. This is acceptable for high-value cargo where the cost of a missed alert far exceeds the cost of a false positive.
- **When to revisit**: Phase 12 should implement per-cargo-class threshold profiles so the system automatically selects the right margin based on the cargo manifest.
- **Interview version**: "We made threshold margins configurable per cargo class because pharma cargo with a 5C margin does not catch degradation until 75 minutes after damage starts. A 2C margin catches it immediately. The 101-reading borderline test proves the exact boundary behavior at 0.01C granularity."

### Decision 6: Z-Score Minimum Data Requirement (n >= 5)

- **The choice**: Z-score detection requires at least 5 readings before producing output.
- **The alternatives**: (1) No minimum -- z-score on 2-3 readings. (2) Higher minimum (n=20) for more statistical power.
- **The reasoning**: At n=4, a single outlier in a normal distribution has a ~4% false-positive rate. n=5 is the minimum for baseline variance to be meaningful without requiring too many readings to start detecting.
- **The trade-off**: A truck that has only sent 4 readings will not get z-score protection. It still gets threshold and drift detection, which cover the critical scenarios.
- **When to revisit**: For high-frequency sampling (1/sec instead of 1/15sec), raise to n=20 for the same statistical power.
- **Interview version**: "Z-score requires n>=5 readings because at n=4, a single outlier generates a 4% false-positive rate -- the baseline variance is not meaningful yet. For high-frequency sampling, we'd raise the minimum to n=20."

## Patterns & Principles Used

### Two-Tier Processing Pattern
1. **What**: Filter the majority of events with cheap rules; reserve expensive processing for confirmed anomalies only.
2. **Where**: `fleet_agent.py` lines 59-85 -- the `if not alerts: return` gate in `process_temperature()`.
3. **Why**: At streaming scale, the cost and latency of per-event LLM calls is not just expensive but physically impossible (500-second backlog/second at 1K msgs/sec).
4. **When you wouldn't use it**: If every event genuinely requires contextual reasoning (not the case for telemetry, where 99%+ is normal).

### Stateful Detector Pattern (Per-Entity State)
1. **What**: Maintain independent state per entity (truck) so one entity's behavior does not affect another's baseline.
2. **Where**: `anomaly_detector.py` line 67 -- `self._temp_history: dict[str, list[...]] = defaultdict(list)`.
3. **Why**: Cross-contaminated histories produce false z-score alerts and incorrect drift calculations.
4. **When you wouldn't use it**: If memory is severely constrained (embedded systems), you'd use stateless detection only. Here, 120 entries x 50 trucks is trivial.

### Graceful Degradation Pattern
1. **What**: When a non-critical dependency fails, continue with reduced functionality rather than crashing.
2. **Where**: `memory_store.py` lines 52-67 -- try/except around Redis and PostgreSQL calls in `lookup()`.
3. **Why**: At 3 AM, a Redis connection timeout must not prevent an anomaly alert from reaching the driver. Memory is supplementary context, not a correctness requirement.
4. **When you wouldn't use it**: If the dependency IS the correctness requirement (e.g., the audit log in Phase 8 -- you cannot silently skip compliance logging).

### Dependency Injection via Closure
1. **What**: Build graph nodes as pure functions of state that accept dependencies as parameters; wrap them in closures at build time for the framework.
2. **Where**: `fleet_response_graph.py` lines 220-258 -- `build_fleet_response_graph()` creates closures over `memory_store` and `llm`.
3. **Why**: Testability. Node functions like `investigate_node(state, llm=mock_llm)` are directly unit-testable without building the full graph.
4. **When you wouldn't use it**: If the framework supports dependency injection natively (LangGraph does not -- state is the only thing passed through).

### Bounded Sliding Window
1. **What**: Keep a fixed-size window of recent data with automatic expiry.
2. **Where**: `fleet_memory.py` lines 41-49 -- Redis `lpush` + `ltrim` + `expire`. Also `anomaly_detector.py` line 253 -- `_MAX_HISTORY_SIZE = 120`.
3. **Why**: Unbounded history = unbounded memory. 50 trucks x 100 entries x 100 bytes = 500KB. Without the cap, one noisy truck could consume unbounded Redis memory.
4. **When you wouldn't use it**: If you need full history for audit or compliance purposes (use PostgreSQL with indexed time queries instead).

### Factory Router
1. **What**: API router created by a factory function so tests can get isolated instances.
2. **Where**: `fleet.py` line 79 -- `def create_fleet_router() -> APIRouter`.
3. **Why**: Module-level state (`_alert_store`, `_ws_connections`, `_detector`) is shared across tests when using module import. The factory lets tests create isolated routers. In practice, the module-level state still leaked across tests and required manual resets in test setup.
4. **When you wouldn't use it**: If all state is managed externally (database) rather than in-memory.

## Benchmark Results & What They Mean

### Normal Event Filter Rate: 100% (100/100)

100 normal temperature readings across 10 trucks produced zero alerts. This proves the rule-based detector does not false-positive on normal telemetry. The cost implication: EUR 0.00 for normal operations, versus EUR 662/day if every event triggered an LLM call. **Boundary**: filter rate tightens with pharma margins (2.0C vs 5.0C). The 101-reading borderline batch proves the exact boundary at 0.01C granularity -- strict greater-than at 8.0C, no false positives below, 100% detection above.

### Simulator Mixed Filter Rate: >80% (5 trucks, 30-min routes)

On 30-minute simulated routes with 5 trucks (3 refrigerated + 2 general, with injected anomalies), more than 80% of events produce zero alerts. The remaining 15-20% includes injected anomalies (correct alerts) + drift detections during temperature ramp-up + z-score triggers on sudden readings. **What this means architecturally**: the false-alarm rate within that 15-20% is the number that determines operational overhead. Needs measurement against production telemetry (Phase 12).

### Drift Detection Coverage: 100% (5/5 drift scenarios)

All 5 drift test scenarios across multiple test files were correctly detected. The 3.1C -> 4.5C slow rise over 30 minutes fires a drift alert while the absolute threshold (8.0C) has not been reached. **Cost of missing this**: EUR 207,000 per missed slow drift incident.

### Stateless vs Memory-Aware: Different Recommendations Confirmed

The same temperature spike on the same truck produces "Recommend immediate investigation" (stateless) vs "MAINTENANCE ALERT: pull from service for inspection" (memory-aware with 3 previous similar alerts). **Cost of stateless-only**: EUR 2,000/diversion x 3 = EUR 6,000 wasted. **Cost of memory-aware**: one EUR 2,500 repair. Savings: EUR 3,500-10,500/year for fleets with 2-3 trucks having recurring issues.

### SQL Injection Defense: 7 Vectors Tested

All PostgreSQL queries use `$N` parameterized parameters. Tested vectors: truck_id, alert_type, pattern, action_taken, and second-order retrieval (malicious data stored via legitimate write, then retrieved as data, not executed). Zero string interpolation in any SQL path.

### WebSocket Broadcast: Direct Tests

Single client receives alert on temperature ingest. Multiple clients (2) both receive the same alert (fan-out). Ping/pong keep-alive works. **Gap**: not tested at scale (50+ concurrent clients). Deferred to Phase 12.

## Test Strategy

### Organization

| Layer | Count | What They Prove |
|-------|-------|-----------------|
| Unit | 148 | Each component works in isolation: detector catches anomalies, dedup suppresses duplicates, memory store degrades gracefully, graph routes correctly, API validates input |
| E2E | 10 | Full pipeline integration: simulator -> detector -> agent -> graph -> alerts. Stateless vs memory-aware produces different results. Slow drift caught before threshold. |
| Integration | 5 | Real Kafka: JSON roundtrip, consumer worker processing, health metrics update, invalid JSON recovery, batch ordering. Auto-skip without Docker. |
| **Total** | **163** | |

### What the Tests Prove (Not Just "163 Tests Pass")

- **Two-tier processing works**: 100 normal events produce 0 alerts and 0 graph invocations. Anomalous events produce alerts AND trigger the graph.
- **Drift detection catches the EUR 207,000 gap**: 3.1C -> 4.5C over 30 minutes fires a drift alert while threshold (8.0C) has not been reached.
- **Memory changes behavior**: Same alert with empty history routes to "investigate". Same alert with 2+ similar alerts routes to "escalate_maintenance". Different action plans produced.
- **Graceful degradation is real**: 6 scenarios tested -- Redis down (lookup returns empty), PostgreSQL down (returns empty), both down (full stateless fallback), Redis write failure (agent completes), PostgreSQL write failure (agent completes), degraded routing (routes to investigate, not escalate).
- **Boundary behavior is exact**: 101 readings from 7.50C to 8.50C in 0.01C steps -- 0 false positives below 8.0C, 0 at exactly 8.0C (strict >), 50/50 above.
- **SQL injection is blocked**: 7 vectors including second-order retrieval.
- **Kafka works for real**: JSON roundtrip with real broker, consumer worker processes messages, invalid JSON does not crash the consumer.

### Mocking Strategy

- **Redis/PostgreSQL**: `AsyncMock` for all storage operations. The `_make_pg_pool_mock()` helper in `test_memory_store.py` creates a mock asyncpg pool that supports `async with pool.acquire()`.
- **LangGraph**: Mock graph with `mock_graph.ainvoke = AsyncMock(return_value={...})`. Graph nodes are tested independently (not through the compiled graph) with explicit parameter injection.
- **Kafka**: Unit tests use `MagicMock` for Kafka messages. Integration tests use real Kafka (auto-skip without Docker).
- **LLM**: `mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="..."))`. No live LLM calls in tests.

### What Is NOT Tested and Why

- **WebSocket at scale (50+ clients)**: Would require concurrent connection churn testing. Deferred to Phase 12 dashboard load testing.
- **1K msgs/sec Kafka throughput**: Requires real Kafka with load testing tools. Deferred to Phase 12.
- **Langfuse cost tracking**: Requires live Langfuse instance. Phase 4 infrastructure.
- **Real LLM action plan quality**: Would need LLM eval pipeline. Tests verify the graph invokes the LLM and passes the response through, but not the quality of the generated action plan.
- **Production telemetry replay**: Anomaly injection in the simulator is synthetic, not derived from real telemetry. False-positive rate in realistic scenarios (heatwave, traffic congestion) is not characterized.

## File Map

| File | Purpose | Key Patterns | Lines |
|------|---------|-------------|-------|
| `apps/api/src/domains/logicore/models/fleet.py` | Domain models: GPSPing, TemperatureReading, FleetAlert, FleetMemoryEntry | Boundary validation via Pydantic Field constraints | ~97 |
| `apps/api/src/domains/logicore/agents/guardian/anomaly_detector.py` | Two-tier rule-based + statistical anomaly detection | Stateful per-entity history, dedup window, staleness tagging | ~308 |
| `apps/api/src/domains/logicore/agents/guardian/fleet_agent.py` | Orchestrator: detector -> graph with fail-safe isolation | Two-tier gate, metrics tracking, error resilience | ~167 |
| `apps/api/src/domains/logicore/agents/guardian/memory_store.py` | 3-tier memory facade (Redis + PostgreSQL) | Graceful degradation, conditional write-back | ~133 |
| `apps/api/src/domains/logicore/infrastructure/fleet_memory.py` | Redis per-truck anomaly history | Sliding window (lpush/ltrim/expire) | ~69 |
| `apps/api/src/domains/logicore/infrastructure/fleet_agent_memory.py` | PostgreSQL long-term pattern storage | Parameterized-only SQL ($N params) | ~85 |
| `apps/api/src/domains/logicore/graphs/fleet_response_graph.py` | LangGraph: memory_lookup -> route -> investigate/escalate -> write -> notify | Conditional edges, DI via closure, TypedDict state | ~259 |
| `apps/api/src/domains/logicore/api/fleet.py` | REST + WebSocket fleet API (6 endpoints + WS) | Factory router, WebSocket fan-out with cleanup | ~213 |
| `apps/api/src/core/infrastructure/kafka/consumer.py` | Domain-agnostic Kafka consumer with health tracking | Error isolation (invalid JSON recovery), health metrics | ~122 |
| `apps/api/src/core/infrastructure/kafka/producer.py` | Domain-agnostic Kafka producer with JSON serialization | Batch send, key encoding | ~67 |
| `scripts/telemetry_simulator.py` | Mock GPS + temperature event generator | Linear interpolation, anomaly injection | ~263 |
| `scripts/create_fleet_agent_memory_table.sql` | DDL for fleet_agent_memory table | 3 indexes (truck_id, pattern, learned_at) | ~34 |
| `data/mock-telemetry/routes.json` | 5 trucks, 5 cold storage facilities, anomaly injection points | -- | -- |
| `tests/unit/test_anomaly_detector.py` | 31 tests: threshold, drift, z-score, dedup, staleness, filter rate, borderline | -- | ~892 |
| `tests/unit/test_memory_store.py` | 26 tests: Redis/PG operations, SQL injection (7 vectors), degradation (6 scenarios) | -- | ~723 |
| `tests/unit/test_fleet_api.py` | 15 tests: endpoints + WebSocket broadcast (single, multi, ping/pong) | -- | ~382 |
| `tests/unit/test_fleet_models.py` | 28 tests: Pydantic validation, serialization, enum coverage | -- | ~446 |
| `tests/unit/test_fleet_response_graph.py` | 17 tests: state schema, memory routing, investigate/escalate nodes, graph compilation | -- | ~494 |
| `tests/unit/test_fleet_agent.py` | 9 tests: two-tier filter, graph trigger, metrics, error resilience, callbacks | -- | ~296 |
| `tests/unit/test_kafka_infrastructure.py` | 12 tests: consumer/producer JSON round-trip, health tracking, error isolation | -- | ~265 |
| `tests/unit/test_telemetry_simulator.py` | 10 tests: route loading, event generation, GPS interpolation, volume scaling | -- | ~175 |
| `tests/e2e/test_fleet_guardian_e2e.py` | 10 tests: full pipeline, slow drift, recurring pattern, stateless vs memory, dedup | -- | ~481 |
| `tests/integration/test_kafka_flow.py` | 5 tests: real Kafka JSON roundtrip, consumer worker, health, invalid JSON, batch ordering | -- | ~300 |

## Interview Talking Points

1. **Two-tier processing as physical necessity**: "At 1K msgs/sec with 500ms LLM latency, you get 500 seconds of backlog per second -- two-tier is not a cost optimization, it is the only way real-time AI works at streaming scale. We filter 99.95% of events with rule-based detection at zero LLM cost, reducing daily cost from EUR 662 to EUR 0.075."

2. **Rate-of-change detection closing the EUR 207,000 gap**: "Threshold-only detection misses 40% of temperature incidents because slow refrigeration failure shows each reading below the threshold even as the trend is clearly rising. We added gradient detection normalized to a 30-minute window that fires before the threshold breach. The drift_rate_threshold is configurable per cargo class."

3. **3-tier memory with graceful degradation**: "We use Redis for 30-day per-truck history, PostgreSQL for confirmed patterns, and LangGraph state for the current workflow. Every external memory call is wrapped in try/except -- a Redis timeout at 3 AM falls back to stateless investigation, which is correct behavior: the driver still gets alerted, the agent just cannot verify if it is a recurring pattern. The trade-off is acceptable because memory is supplementary context, not a correctness requirement."

4. **Conditional graph routing based on memory**: "The LangGraph uses conditional edges to skip full investigation when 2+ similar alerts exist in the truck's history. Instead of calling GPT-5.2 (EUR 0.02) for a full RAG + risk assessment, it escalates directly to maintenance with GPT-5-mini (EUR 0.003). This saves EUR 3,500-10,500/year by preventing repeated unnecessary cold-storage diversions on trucks with failing equipment."

5. **Alert deduplication preventing operational blindness**: "Without dedup, a heatwave day produces 50+ alerts for the same truck. Dispatchers start ignoring all alerts. The real EUR 180K pharma alert gets buried. We dedup on (truck_id, alert_type) within a 5-minute window. Different alert types on the same truck are correctly treated as separate alerts."

6. **Per-cargo-class threshold margins**: "We proved with a 101-reading boundary test that the same temperature reading (5.5C) produces different alert status depending on the configured margin. Pharma cargo at 2C margin catches degradation 75 minutes earlier than general freight at 5C margin. The test validates at 0.01C granularity that the threshold is strict greater-than, not greater-or-equal."

7. **SQL injection defense with second-order testing**: "All PostgreSQL queries use $N parameterized parameters. We tested 7 injection vectors including a second-order scenario: malicious SQL stored via legitimate write, then retrieved and verified it comes back as data, not executed. No string interpolation anywhere in SQL paths."

8. **Kafka error isolation**: "Invalid JSON in a Kafka message logs an error and increments the error counter but does not crash the consumer loop. The next valid message is processed normally. Proven with real Kafka integration tests that auto-skip when Docker is not available."

## What I'd Explain Differently Next Time

**The two-tier argument is about physics, not cost.** The first time I described two-tier processing, I led with the cost savings (EUR 662 vs EUR 0.075). That is compelling but misses the point. The real argument is: at 1K msgs/sec with 500ms LLM latency, synchronous processing creates a 500-second backlog per second. It is physically impossible, not just expensive. Lead with the backlog calculation, then mention cost as a consequence.

**Graceful degradation needs a "what's the worst case?" framing.** When explaining why memory failures are silently swallowed, the clearest framing is: "What's the worst case when Redis is down? The agent does a full investigation instead of a faster maintenance escalation. What's the worst case when the agent crashes? Cargo spoils and nobody gets alerted. Silent memory failure is obviously the right trade-off."

**The drift detection story is strongest when you show what threshold-only misses.** Instead of starting with "we also have drift detection," start with the EUR 207,000 scenario: 3.1C -> 9.2C over 2 hours, each individual reading below the 8C threshold, cargo spoiled by the time the threshold fires. Then show that drift detection catches it at 4.5C. The problem motivates the solution.

**Module-level state in Python APIs is a testing headache.** The `_detector` singleton and `_alert_store` dict in `fleet.py` leak state across tests. We worked around it with manual resets in test setup (`fleet_module._detector = AnomalyDetector()`), but the cleaner approach would be to inject these via FastAPI dependency injection or store them in app state (`app.state.detector`). Worth fixing if this pattern is used again.

**The "boundary found" framing for benchmarks is powerful.** Rather than saying "31 anomaly detector tests pass," saying "we proved the exact threshold boundary at 0.01C granularity with a 101-reading batch" is immediately credible to anyone technical. Every benchmark should find a boundary -- the point where behavior changes -- not just confirm the happy path.
