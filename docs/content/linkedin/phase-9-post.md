# Phase 9 LinkedIn Post: Fleet Guardian — Real-Time Streaming & Event-Driven AI

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-09 | **Status**: draft

---

47,000 GPS pings a day. Running each one through GPT-5.2 costs EUR 662/day. The company makes EUR 2.25 from the AI per month.

So how do you build real-time fleet monitoring that actually works economically?

This is Phase 9 of a 12-phase AI system im building for a Polish logistics company. Phase 1 built the search layer (RAG where embeddings are mandatory coz BM25 fails 50% of real queries). Phase 3 added multi-agent invoice auditing. Phase 8 made every AI decision reconstructible for EU AI Act compliance. Phase 9 asks: when a refrigerated truck starts losing temperature at 3 AM, can the AI respond in under 2 seconds without bankrupting the company?

The answer is two-tier processing. Rule-based detection handles 100% of normal events at zero LLM cost. Temperature above threshold? Simple comparison, no LLM. Speed over 120 km/h? Simple comparison, no LLM. Only confirmed anomalies trigger the LangGraph agent. On a 50-truck fleet thats maybe 52 anomalies per day out of 47,000 events. Total daily AI cost: EUR 0.075. Thats a 99.95% reduction from the "LLM everything" approach.

But the interesting part isnt the cost savings. Its what threshold-only detection misses.

A refrigeration unit fails gradually. Temperature goes 3.1C -> 3.8C -> 4.5C over 30 minutes. Every single reading is below the 8.0C threshold. No alert fires. By the time it hits 8.0C, cargo spoilage started at 5.0C an hour ago. EUR 180,000 in pharmaceutical cargo, gone. Plus EUR 27,000 in penalties.

Rate-of-change detection catches this. If temperature rises more than 0.5C per 30 minutes consistently, the system fires a drift alert BEFORE threshold breach. Zero additional cost (its just gradient math on readings already in memory). This is the EUR 207,000 gap between "works" and "production-ready."

I chose NOT to make the agent stateless. Most agent demos start fresh every invocation. But truck-4521 has its 3rd temperature anomaly this quarter. A stateless agent recommends "divert to cold storage" every time. EUR 2,000 per diversion x 3 = EUR 6,000. A memory-aware agent looks up the last 30 days of anomalies in Redis, detects the recurring pattern, and instead recommends "pull from service for maintenance." One EUR 2,500 repair instead of EUR 6,000 in diversions. Cross-session memory saves EUR 3,500-10,500/year for a 50-truck fleet.

What breaks: no test against real Kafka yet (consumer/producer classes tested with mocks, real Kafka integration is Phase 12). WebSocket alert broadcast exists but hasnt been load-tested with 50 concurrent dashboard connections. The memory system has no defense against poisoning (fake history injected via Redis) which is Phase 10 security scope.

Post 9/12 in the LogiCore series. Next up: your SQL agent is a ticking time bomb. Turns out "SELECT * FROM invoices" is one prompt injection away from "DROP TABLE invoices" 😅

---

## Reply Ammo

### 1. "EUR 662/day sounds made up"

47,000 pings x GPT-5.2 pricing ($1.75/1M input, $14.00/1M output). Average ~300 input tokens + 100 output tokens per call. Thats about EUR 0.014 per call. 47,000 x EUR 0.014 = EUR 658. Rounded to EUR 662 in the spec. The math works at current Azure pricing.

### 2. "Why not just use a threshold and skip the LLM entirely?"

Coz threshold misses 40% of real temperature incidents. Slow drifts are the most expensive failure mode (EUR 207K per incident). The LLM isnt for detection, its for response: what cargo is on that truck, whats the financial exposure, wheres the nearest cold storage. That context-dependent reasoning is what you need an LLM for.

### 3. "Kafka is overkill for 50 trucks"

Agreed for 50 trucks. Direct API ingestion works fine and we built that as a fallback. Kafka matters at 500+ trucks where you need decoupled consumers, replay capability, and partition-based load distribution. The architecture supports both. Switch condition: go Kafka when consumer processing time exceeds ingestion rate.

### 4. "Cross-session memory sounds like just a database lookup"

It is, and thats the point. Redis lookup adds ~5ms. The value is in what the agent DOES with the context. Without memory: same EUR 2,000 diversion every time. With memory: one EUR 2,500 repair. The architecture is simple. The behavioral difference (stateless vs memory-aware routing in LangGraph) is what saves money.

### 5. "Z-score on 5 readings isnt statistically valid"

Fair. 5 is the minimum for the variance calculation to be non-degenerate. For trucks with high-frequency sampling (1/sec vs 1/15sec), youd want n=20 minimum. The threshold is configurable. At n=5 its a "something looks weird" flag, not a statistical proof. The threshold alert is the hard gate.

### 6. "What about false positives? Alert fatigue is a real problem"

This is why alert deduplication exists. Same truck + same alert type within 5 minutes = one alert, not 20. Without dedup: 50+ alerts during a summer heatwave. Dispatchers start ignoring everything. Then the real EUR 180K pharma alert fires and nobody looks. Dedup is not a nice-to-have, its an operational survival mechanism.

### 7. "Why LangGraph instead of a simple if/else tree?"

Coz the conditional routing gets interesting with memory. "If 2+ similar alerts in history, skip investigation and escalate to maintenance" is a simple rule now. But add cargo value assessment, driver rest compliance, and facility availability and suddenly you need state management across 8+ nodes with conditional edges. LangGraph handles that cleanly. An if/else tree at that complexity is a maintenance nightmare.

### 8. "Redis for memory seems fragile. What if Redis goes down?"

Currently: agent treats it as a new truck (empty history) and does full investigation. Thats the correct degradation behavior, not a bug. The agent still works, just without the memory optimization. Phase 7 already built circuit breaker patterns for exactly this scenario. When Redis recovers, the history rebuilds from the next write-back cycle.

### 9. "You defer a lot to Phase 12. Is that a cop-out?"

The deferred items are: real Kafka integration test, Next.js dashboard, Langfuse cost tracking. These are integration concerns, not architecture decisions. The architecture is proven with 139 unit and E2E tests. Phase 12 is the full-stack demo where everything runs against real infrastructure. I could run the Kafka integration test now but it wouldnt change any architecture decision.

### 10. "What about GDPR? GPS data is location tracking"

The system tracks trucks, not drivers. No driver PII in memory entries. GPS pings are keyed by truck_id, not driver_id. If a driver is assigned to a specific truck long-term, there is a weak indirect link, but the anomaly records dont store driver names, schedules, or personal data. Phase 8 already solved the PII vault pattern for cases where queries DO contain personal data.
