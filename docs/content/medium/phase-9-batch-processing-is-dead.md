---
title: "Batch Processing Is Dead: How Two-Tier Detection Makes Real-Time AI Economically Viable"
phase: 9
series: "LogiCore AI OS"
post_number: 9
date: 2026-03-09
status: draft
tags: [kafka, streaming, real-time, fleet-monitoring, event-driven, langgraph, agent-memory]
word_count: ~3600
---

# Batch Processing Is Dead: How Two-Tier Detection Makes Real-Time AI Economically Viable

## The 3 AM Phone Call

Its March 9th, 2026, 3:07 AM. Nobody is watching the dashboard at LogiCore Transport. Truck-4721 left Hamburg at 11 PM carrying EUR 180,000 in pharmaceutical cargo for PharmaCorp AG, temperature requirement 2-8C continuous. The refrigeration unit has a hairline crack in the compressor seal. Not enough to fail immediately. Enough to lose 0.5C every 15 minutes.

At 3:00 AM the temperature reads 3.1C. Normal. At 3:15 it reads 3.8C. Still normal, well within the 8C threshold. At 3:30 it reads 4.5C. Normal by the numbers.

At 3:45 it reads 5.2C. Cargo spoilage has started. The pharmaceutical compounds are degrading. Nobody knows.

At 4:30 the temperature finally hits 8.1C. The threshold alert fires. The dispatcher on night shift gets a notification. She checks the cargo manifest, calls the driver, locates the nearest cold storage in Zurich, diverts the truck. By the time the cargo reaches Zurich at 5:15 AM, the damage assessment confirms: full loss. EUR 180,000 in cargo. EUR 27,000 in contractual penalties. EUR 207,000 total.

The threshold alert did exactly what it was supposed to do. It fired the moment the temperature exceeded 8C. And it was 75 minutes too late.

LogiCore's batch processing system checks temperature logs every 6 hours. If this had been a batch system, the alert would have fired at 6 AM. By then the cargo would have been at 12C for over an hour.

This is Phase 9 of a 12-phase AI system im building for a Polish logistics company. Phase 1 built the search layer (RAG + RBAC, where embeddings are mandatory coz BM25 alone fails half of real-world queries). Phase 3 added multi-agent invoice auditing with human-in-the-loop. Phase 7 made the system survive Azure outages by falling back to local Ollama models. Phase 8 built EU AI Act compliance logging with a hash chain that makes every AI decision reconstructible. Phase 9 asks: when something goes wrong with a truck at 3 AM, can the AI detect it, assess the risk, and alert the driver before the damage is done?

## Why "Just Use an LLM" Doesnt Work

The naive approach is obvious: pipe every sensor reading through an LLM and let it figure out whats abnormal. GPT-5.2 is smart enough to spot anomalies in temperature data. The problem is not intelligence. The problem is physics.

LogiCore runs 50 trucks. Each truck sends a GPS ping every 15 seconds and a temperature reading every 30 seconds. Thats 47,000+ events per day. At GPT-5.2 pricing (roughly EUR 0.014 per call with ~400 tokens), processing every event costs EUR 662 per day. The company's total AI operating cost for fleet monitoring should be about EUR 2.25 per month.

But the cost isnt even the real problem. Martin Kleppmann explains this in *Designing Data-Intensive Applications*: the fundamental constraint in stream processing is the ratio of processing time to ingestion rate. If events arrive at 1,000/second and each LLM call takes 500ms, you need 500 parallel LLM workers just to keep up. And youre still paying EUR 662/day. At any realistic scale, synchronous LLM processing of every event creates a backlog that grows faster than you can process it.

Jay Kreps (the creator of Kafka) makes a related point in *I Heart Logs*: the power of stream processing is separating the fast path from the slow path. Events that need cheap, fast processing should never touch the slow, expensive path. This is the design principle behind two-tier processing.

## The Architecture: Two Tiers, Zero Waste

Tier 1 is rule-based detection. Zero LLM cost. Temperature above setpoint + 5C margin? Alert. Speed above 120 km/h? Alert. Engine running while stationary? Alert. These are comparisons, not reasoning tasks. An LLM adds latency and cost for zero additional value.

Tier 2 is statistical detection. Still zero LLM cost. Z-score analysis on a rolling per-truck temperature history. If a reading is more than 3 standard deviations from the truck's recent baseline, flag it. Requires at least 5 readings to have a meaningful baseline (below that, the variance calculation is noise, not signal).

Tier 3 is the LLM agent. Triggered ONLY on confirmed anomalies from tier 1 or 2. This is where the expensive reasoning happens: cargo manifest lookup via RAG, financial risk calculation, nearest cold-storage facility identification, action plan generation, driver notification.

```python
class AnomalyDetector:
    def check_temperature(self, reading: TemperatureReading) -> list[FleetAlert]:
        alerts: list[FleetAlert] = []
        is_stale = self._is_stale(reading.timestamp)

        self._record_temp(reading.truck_id, reading.timestamp, reading.temp_celsius)

        # Tier 1a: Absolute threshold check
        if self._check_threshold(reading):
            alert = self._make_temp_alert(
                truck_id=reading.truck_id,
                alert_type=AlertType.TEMPERATURE_SPIKE,
                severity=AlertSeverity.CRITICAL,
                details=self._threshold_details(reading, is_stale),
                timestamp=reading.timestamp,
            )
            if alert:
                alerts.append(alert)

        # Tier 1b: Rate-of-change (gradient) check
        drift_alert = self._check_drift(reading)
        if drift_alert:
            alerts.append(drift_alert)

        # Tier 2: Z-score statistical check
        zscore_alert = self._check_zscore(reading, is_stale)
        if zscore_alert:
            alerts.append(zscore_alert)

        return alerts
```

The key insight is what sits between tier 1a (threshold) and tier 2 (z-score): rate-of-change detection. This is the EUR 207,000 line.

## The Hard Decision: Rate-of-Change Is Not Optional

The spec said "rule-based + statistical detection." A junior architect would implement threshold and z-score and call it done. The analysis said something different.

Threshold-only detection catches sudden spikes. It DOES NOT catch gradual degradation. The 3 AM scenario at the top of this article? Threshold fires at 8.1C. The cargo started spoiling at 5.0C. Every single reading between 3.1C and 8.0C passes the threshold check. The EUR 207,000 loss happens in the gap between "within threshold" and "actually damaged."

| Detection Method | Catches Sudden Spikes | Catches Slow Drift | LLM Cost | Business Gap |
|---|---|---|---|---|
| Threshold only | Yes | No | EUR 0 | Misses 40% of temperature incidents. EUR 207,000 per missed slow drift. |
| Threshold + z-score | Yes | Sometimes (needs 5+ readings) | EUR 0 | Better, but z-score on a slowly rising baseline adapts TO the drift instead of catching it. |
| Threshold + rate-of-change + z-score | Yes | Yes | EUR 0 | Catches drift before threshold breach. The EUR 207,000 gap closes. |
| LLM for everything | Yes | Yes | EUR 662/day | Correct but economically impossible. |

Rate-of-change detection is gradient math on readings already in memory:

```python
def _check_drift(self, reading: TemperatureReading) -> FleetAlert | None:
    history = self._temp_history[reading.truck_id]
    if len(history) < 2:
        return None

    cutoff = reading.timestamp - timedelta(minutes=30)
    window = [(ts, temp) for ts, temp in history if ts >= cutoff]
    if len(window) < 2:
        return None

    oldest_ts, oldest_temp = window[0]
    newest_ts, newest_temp = window[-1]
    elapsed_minutes = (newest_ts - oldest_ts).total_seconds() / 60.0
    if elapsed_minutes < 1.0:
        return None

    rate_per_30min = abs(newest_temp - oldest_temp) * (30.0 / elapsed_minutes)

    if rate_per_30min > self.drift_rate_threshold:
        direction = "rising" if newest_temp > oldest_temp else "falling"
        return self._make_temp_alert(...)
    return None
```

The decision framework: if your anomaly detection doesnt have rate-of-change, you are accepting a 40% miss rate on temperature incidents at EUR 207,000 per miss. At 2-3 slow drift events per year, thats EUR 414,000-621,000 in expected annual losses. The rate-of-change detection that closes this gap costs EUR 0 in runtime (its pure math, no API calls, no models) and about 2 days of engineering effort to implement.

WHEN THIS CHANGES: if your fleet only carries non-perishable goods (e.g., building materials), threshold-only is sufficient. Rate-of-change matters specifically for temperature-sensitive cargo where damage accumulates between "technically within spec" and "actually at threshold."

## Cross-Session Memory: From Stateless to Learning

Gene Kim's *The Phoenix Project* describes the concept of "institutional knowledge" — the operational wisdom that lives in people's heads. When an experienced fleet manager sees the third temperature anomaly on truck-4521 this quarter, she doesnt open a new investigation. She picks up the phone: "Pull 4521 for a compressor inspection."

A stateless agent doesnt have institutional knowledge. Every invocation starts fresh:

```
Anomaly: truck-4521 temp spike (3rd this month)
-> RAG lookup: pharmaceutical cargo, EUR 180K
-> Risk: HIGH
-> Action: "Divert to Zurich cold storage"
-> Cost: EUR 0.02 (same investigation, same answer, every time)
```

A memory-aware agent does:

```
Anomaly: truck-4521 temp spike
-> Memory check: Redis lookup truck:4521:anomalies
-> Found: 2 previous temp anomalies (March 3, March 12)
-> Pattern match: "recurring_refrigeration_failure"
-> Escalation: SKIP normal triage, go directly to:
  "MAINTENANCE ALERT: truck-4521 refrigeration unit failing.
   3 anomalies in 25 days. Pull from service for inspection.
   Estimated repair: EUR 2,500. Estimated loss if ignored: EUR 180K per incident."
-> Cost: EUR 0.003 (pattern was pre-identified, lighter model)
```

The memory architecture is three tiers, matching three different time horizons:

| Tier | Store | TTL | What It Holds | Cost |
|---|---|---|---|---|
| Short-term | LangGraph TypedDict | Until workflow completes | Current investigation state | Zero (in-memory) |
| Medium-term | Redis list per truck | 30 days sliding window | Recent anomaly history for pattern detection | ~500KB for 50 trucks |
| Long-term | PostgreSQL table | Indefinite | Confirmed patterns, learned behaviors | Negligible |

The routing is a conditional edge in LangGraph:

```python
def route_by_memory(state: FleetResponseState) -> str:
    history = state.get("truck_history") or []
    alert_type = state["alert"].get("alert_type", "")
    similar = [h for h in history if h.get("alert_type") == alert_type]
    if len(similar) >= 2:  # 2 previous + current = 3 total
        return "escalate_maintenance"
    return "investigate"
```

Donella Meadows writes in *Thinking in Systems* about feedback loops: a system improves only when the results of its actions feed back to inform future decisions. A stateless agent has no feedback loop. It produces the same output regardless of history. The memory tier creates the feedback loop: action -> outcome -> pattern -> better action next time.

The quantified value: without memory, EUR 2,000/diversion x 3 = EUR 6,000 wasted on repeated diversions. With memory, one EUR 2,500 repair after pattern detection. At 5% of a 50-truck fleet having recurring issues (2-3 trucks/year), thats EUR 3,500-10,500 saved annually.

WHEN THIS CHANGES: if your fleet has fewer than 10 trucks, the memory maintenance overhead (Redis instance, PostgreSQL table, pattern detection logic) exceeds the savings. Below that threshold, a human fleet manager's institutional knowledge is cheaper than the infrastructure to replicate it.

## The Cost Table Nobody Shows You

| Approach | Daily Cost | Monthly | Detects Slow Drift | Has Memory | Viable? |
|---|---|---|---|---|---|
| LLM for every event | EUR 662 | EUR 19,860 | Yes | No | No. Creates 500-second backlog per second at 1K msgs/sec. |
| Threshold only | EUR 0 | EUR 0 | No | No | No. Misses 40% of temperature incidents. EUR 207K per miss. |
| Threshold + z-score | EUR 0 | EUR 0 | Sometimes | No | Better. Z-score adapts to drift baseline, partial miss rate. |
| Two-tier (threshold + drift + z-score + LLM on anomalies) | EUR 0.075 | EUR 2.25 | Yes | Yes | Yes. This is the only approach that works both economically and operationally. |

The daily cost of EUR 0.075 breaks down as: ~2 P1 alerts at EUR 0.02 each (GPT-5.2 for high-value cargo) + ~10 P2 alerts at EUR 0.003 each (GPT-5 mini) + ~40 P3 alerts at EUR 0.0001 each (GPT-5 nano). The model is selected by cargo value and alert severity, not one-size-fits-all.

## What Breaks

Alert deduplication is necessary but introduces a blind spot. If a truck has a genuine second anomaly within the 5-minute dedup window (different root cause, same alert type), it gets suppressed. The dedup window is configurable. Shorter window (60 seconds) = more alerts but more noise. Longer window (5 minutes) = cleaner signal but possible miss. Default 5 minutes is a judgment call, not a universal truth.

The z-score minimum of 5 readings means a brand-new truck has no statistical protection for its first 75 seconds of operation (at 15-second intervals). Threshold and drift detection still work, but the statistical layer is blind. Acceptable because new trucks rarely have equipment failures on day one, but architecturally noteworthy.

No test against real Kafka yet. Consumer and producer classes are tested with mocks. Real Kafka brings consumer lag, partition rebalancing, and backpressure behaviors that mocks dont simulate. Phase 12 runs the full integration.

The memory system has no defense against poisoning. If someone injects fake anomaly entries into Redis, the agent would incorrectly escalate a healthy truck to maintenance. Phase 10 (LLM Firewall) addresses authentication on the memory write path.

## What Id Do Differently

I would have started with the rate-of-change detection test, not the threshold test. The threshold test passes immediately and gives false confidence ("anomaly detection works!"). The drift test is where the real design thinking happens. Starting with the easy test created a brief period where the system passed all tests but had a EUR 207,000 blind spot. TDD discipline caught it, but the ordering of tests matters.

The dedup window should be per-alert-type, not global. A temperature spike and a GPS deviation on the same truck are independent events. Currently dedup is keyed on (truck_id, alert_type), which is correct. But the window duration should differ: 5 minutes for temperature (sensor noise), 30 seconds for speed (legitimate rapid change). Didnt implement per-type windows coz the added complexity wasnt justified at 50 trucks.

The LangGraph escalation path could use a lighter model (GPT-5 nano) for pattern-detected maintenance alerts instead of the default investigation model. The pattern is already identified, the memory lookup is done, all thats left is generating the maintenance recommendation. Currently it runs through the same graph nodes. Model routing per graph path would save ~EUR 0.017 per pattern-detected alert.

## Vendor Lock-In and Swap Costs

| Component | Current | Alternative | Swap Cost |
|---|---|---|---|
| Event streaming | Kafka (aiokafka) | Redis Streams, AWS Kinesis, Azure Event Hubs | Medium. Consumer/producer are domain-agnostic wrappers in `core/infrastructure/kafka/`. Swap the transport, keep the handler interface. |
| Medium-term memory | Redis | Memcached, DynamoDB | Low. FleetMemoryRedis class wraps 3 operations (lpush/lrange/expire). Any key-value store with TTL and list operations works. |
| Long-term memory | PostgreSQL | Any SQL database | Low. 2 parameterized queries (INSERT, SELECT with ORDER BY). Standard SQL. |
| Agent orchestration | LangGraph | Temporal, custom state machine | High. Conditional routing, state management, and checkpointing are deeply integrated. The 5-node graph with memory-aware routing is LangGraph-specific. |
| Anomaly detection | Custom Python | Apache Flink, Spark Streaming | Medium. The detection logic (threshold, drift, z-score) is pure Python with no framework dependency. Porting to Flink would mean rewriting the stateful per-truck history in Flink's state API. |

The highest lock-in risk is LangGraph. The graph is 5 nodes with conditional routing, which is manageable to rewrite. But if it grows to 15+ nodes with subgraphs and parallel execution, migration becomes a multi-week effort.

Phase 9/12 of LogiCore. Next: your SQL agent has direct database access. One prompt injection turns "show me late invoices" into "DROP TABLE invoices." The security model cant be an afterthought when the agent has write access to production data.
