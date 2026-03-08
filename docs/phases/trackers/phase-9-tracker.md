# Phase 9 Tracker: Fleet Guardian — Real-Time Streaming

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-9-fleet-guardian.md`
**Depends on**: Phases 1-3

## Implementation Tasks

- [ ] `apps/api/src/core/infrastructure/kafka/__init__.py`
- [ ] `apps/api/src/core/infrastructure/kafka/consumer.py` — Kafka consumer base class
- [ ] `apps/api/src/core/infrastructure/kafka/producer.py` — Kafka producer helper
- [ ] `apps/api/src/domains/logicore/agents/guardian/anomaly_detector.py` — rule-based + statistical detection
- [ ] `apps/api/src/domains/logicore/agents/guardian/fleet_agent.py` — LangGraph anomaly response agent
- [ ] `apps/api/src/domains/logicore/graphs/fleet_response_graph.py` — RAG → risk calc → action plan
- [ ] `apps/api/src/domains/logicore/models/fleet.py` — GPSPing, TemperatureReading, FleetAlert models
- [ ] `apps/api/src/domains/logicore/api/fleet.py` — GET /fleet/status, /alerts
- [ ] `scripts/telemetry_simulator.py` — mock GPS + temperature Kafka events
- [ ] `data/mock-telemetry/routes.json` — routes with anomaly injection points
- [ ] `tests/integration/test_kafka_flow.py` — Kafka → agent → alert
- [ ] `tests/unit/test_anomaly_detector.py` — threshold tests
- [ ] `apps/web/src/app/fleet/page.tsx` — real-time fleet dashboard

### Agentic: Cross-Session Agent Memory

- [ ] `apps/api/src/domains/logicore/agents/guardian/memory_store.py` — 3-tier memory abstraction
- [ ] `apps/api/src/domains/logicore/infrastructure/fleet_memory.py` — Redis per-truck event history (30-day sliding window)
- [ ] `apps/api/src/domains/logicore/infrastructure/fleet_agent_memory.py` — long-term learned patterns table
- [ ] `scripts/create_fleet_agent_memory_table.sql` — DDL for `fleet_agent_memory` table
- [ ] `apps/api/src/domains/logicore/graphs/fleet_response_graph.py` — MODIFY: add `memory_lookup` node + `route_by_memory` conditional
- [ ] `apps/api/src/domains/logicore/graphs/fleet_response_graph.py` — MODIFY: add `write_memory` node (post-resolution write-back)
- [ ] `apps/api/src/domains/logicore/models/fleet.py` — MODIFY: add `FleetMemoryEntry` model
- [ ] `tests/unit/test_memory_store.py` — 3-tier read/write, TTL, pattern matching
- [ ] `tests/integration/test_cross_session_memory.py` — stateless vs memory-aware agent behavior difference

## Success Criteria

- [ ] Simulator pushes 1K+ msgs/sec to Kafka
- [ ] Rule-based detector filters >95% of normal events (no LLM cost)
- [ ] Temperature spike triggers LangGraph agent within 2 seconds
- [ ] Agent looks up cargo manifest via RAG
- [ ] Action plan includes nearest cold-storage facility
- [ ] Alert published to fleet.alerts topic + dashboard
- [ ] Langfuse shows cost per alert (not per message)
- [ ] Semantic cache prevents re-analyzing identical patterns
- [ ] Kafka UI shows topic throughput and consumer lag
- [ ] Memory-aware agent detects recurring pattern (e.g., 3rd temp spike on same truck)
- [ ] Stateless vs memory-aware produces different recommendations for same input
- [ ] Memory write-back stores learned pattern after resolution
- [ ] Redis 30-day window auto-expires old entries

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Anomaly detection | rule-based + z-score | | |
| LLM trigger threshold | confirmed anomaly only | | |
| Alert dispatch | Kafka topic + API | | |
| Fleet dashboard | Next.js real-time | | |
| Memory architecture | 3-tier (LangGraph → Redis → PostgreSQL) | | |
| Redis TTL | 30-day sliding window | | |
| Memory write-back | post-resolution pattern storage | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Kafka throughput | | msgs/sec |
| Normal event filter rate | | % filtered without LLM |
| Anomaly → agent trigger latency | | seconds |
| Agent response time (total) | | seconds |
| LLM calls per day | | anomalies only |
| Cost per alert | | EUR |
| Cost if LLM-everything | | EUR/day |
| Cost with two-tier | | EUR/day |
| False positive rate | | % |
| False negative rate | | % |
| Consumer lag | | messages behind |
| Memory lookup latency | | ms (Redis hit vs PostgreSQL fallback) |
| Memory hit rate | | % of anomalies with prior context |
| Behavior change rate | | % of decisions altered by memory |
| Redis memory footprint | | MB per 1K trucks × 30 days |

## Screenshots Captured

- [ ] Kafka UI (topic throughput, consumer lag)
- [ ] Fleet dashboard (map + alert markers)
- [ ] Langfuse (cost per alert breakdown)
- [ ] Response latency histogram
- [ ] Cost comparison (LLM-everything vs two-tier)
- [ ] Memory-aware vs stateless side-by-side (same truck, different response)
- [ ] Redis memory contents for a truck with recurring issues

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
