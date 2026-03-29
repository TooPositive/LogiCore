# ADR-017: Two-Tier Processing for Streaming Telemetry

## Status
Accepted

## Context
Phase 9's fleet monitoring ingests GPS and temperature telemetry at up to 1,000 messages/second from 47 trucks. Each message could trigger an LLM-powered investigation agent. At 500ms LLM latency per message, synchronous LLM processing creates a 500-second backlog for every second of ingestion. This is not a cost problem — it is a physical impossibility.

## Decision
**Rule-based anomaly detection first (EUR 0.00/event), LLM agent only on confirmed anomalies (~EUR 0.02/anomaly).** Three detection methods run synchronously on every event: threshold breach, rate-of-change (drift), and z-score deviation. Only confirmed anomalies (~52/day) trigger the LangGraph investigation agent.

## Rationale

| Approach | Cost/Day | Latency at 1K msgs/sec | Anomaly Coverage |
|----------|---------|----------------------|-----------------|
| **Two-tier (chosen)** | EUR 0.075 | Rules: <1ms, LLM: 500ms on anomalies only | Threshold + drift + z-score + LLM reasoning |
| LLM for everything | EUR 662 | 500s backlog/second | Full contextual reasoning on every event |
| Rules only (no LLM) | EUR 0.00 | <1ms | Misses contextual reasoning (cargo manifest, facility proximity) |

**Rate-of-change detection is mandatory:**
- Threshold-only misses 40% of temperature incidents — slow drifts where each reading is below threshold but the trend is rising
- A refrigeration unit failing from 3.1C to 9.2C over 2 hours wouldn't trigger a 5C threshold until cargo is already spoiled (EUR 207K/incident for pharma)
- Drift detection normalizes temperature gradient to a 30-minute window and fires before threshold breach

## Consequences
- Per-truck state maintained: 120-entry sliding window for temperature history, z-score baseline. Memory cost: trivial (120 entries × 50 trucks)
- Per-cargo-class threshold margins: pharma gets 2C (not default 5C) — catches degradation 75 minutes earlier
- Alert deduplication: 5-minute window per `(truck_id, alert_type)` prevents dispatcher fatigue during heatwaves (50+ alerts → 1 alert per window)
- Z-score requires n≥5 readings before producing output — at n=4, a single outlier has ~4% false-positive rate
- LLM agent handles only the ~52 daily anomalies that need contextual reasoning (cargo manifest lookup, nearest-facility calculation, historical pattern matching)
- When to revisit: if LLM latency drops below 5ms and cost drops 100x, reconsider — but with current models, two-tier is a physical necessity
