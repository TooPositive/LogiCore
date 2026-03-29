# ADR-019: Three-Tier Memory with Graceful Degradation

## Status
Accepted

## Context
Phase 9's fleet monitoring agent needs memory across three time horizons: current investigation state (seconds), recent per-truck history (30 days), and long-term confirmed patterns (indefinite). Without memory, the agent treats every anomaly as novel — repeating full investigations for recurring patterns costs EUR 3,500-10,500/year in unnecessary diversions. A Redis failure at 3 AM must not prevent anomaly response.

## Decision
**Three tiers with independent failure handling:**
1. **Short-term**: LangGraph state (in-memory, current workflow)
2. **Medium-term**: Redis (30-day TTL, per-truck history, ~5ms lookups)
3. **Long-term**: PostgreSQL (indefinite, confirmed patterns like "Truck PL-47 sensor drift every 3 weeks")

Every Redis and PostgreSQL call is wrapped in `try/except`. Failure returns empty tier — agent falls back to stateless investigation.

## Rationale

| Approach | Pattern Detection | Failure Behavior | Cost |
|----------|------------------|-----------------|------|
| **Three-tier (chosen)** | Full: recent + historical | Graceful — falls back to stateless | Redis + PostgreSQL (already deployed) |
| Stateless (no memory) | None — every anomaly is novel | No external dependency to fail | EUR 3,500-10,500/year in repeated diversions |
| Redis-only | Recent 30 days | Lost on restart/eviction | Misses long-term patterns |
| PostgreSQL-only | Full history | Too slow for per-event lookups (~50ms vs ~5ms) | Higher latency |

## Consequences
- Silent memory failure means the agent might miss a recurring pattern when Redis is down — acceptable because the anomaly response still happens, just with a full investigation instead of faster maintenance escalation
- Memory maintenance overhead exceeds savings below ~10 trucks — for smaller fleets, stateless investigation is cheaper
- Medium-term tier uses per-truck keys (`fleet:memory:{truck_id}`) — cross-truck contamination is structurally impossible
- Long-term patterns are stored as confirmed facts (e.g., `{"truck": "PL-47", "pattern": "sensor_drift", "interval_days": 21}`) — not raw telemetry
- When to revisit: if Redis becomes a single point of failure for other critical paths (not just memory), add Redis Sentinel or switch to a replicated store
