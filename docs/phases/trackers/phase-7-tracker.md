# Phase 7 Tracker: Resilience Engineering — Circuit Breakers, Model Routing

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-7-resilience-engineering.md`
**Depends on**: Phase 6

## Implementation Tasks

- [ ] `apps/api/src/core/infrastructure/llm/circuit_breaker.py` — CLOSED/OPEN/HALF-OPEN states
- [ ] `apps/api/src/core/infrastructure/llm/provider_chain.py` — ordered fallback chain
- [ ] `apps/api/src/core/infrastructure/llm/model_router.py` — query complexity classifier
- [ ] `apps/api/src/core/infrastructure/llm/retry.py` — exponential backoff with jitter
- [ ] `apps/api/src/core/infrastructure/llm/provider.py` — MODIFY: integrate breaker + retry
- [ ] `apps/api/src/core/config/settings.py` — MODIFY: routing config, breaker thresholds
- [ ] `apps/api/src/core/api/v1/analytics.py` — MODIFY: routing stats endpoint
- [ ] `scripts/simulate_outage.py` — simulate Azure outage
- [ ] `scripts/benchmark_routing.py` — cost comparison: routed vs unrouted
- [ ] `tests/unit/test_circuit_breaker.py` — state transition tests
- [ ] `tests/unit/test_model_router.py` — classification accuracy
- [ ] `tests/integration/test_failover.py` — full failover chain

## Success Criteria

- [ ] Circuit breaker: CLOSED → OPEN after 5 failures, HALF-OPEN after 60s
- [ ] Azure outage → automatic fallback to Ollama within 5s
- [ ] All providers down → cached responses with disclaimer
- [ ] Model routing: simple → mini, complex → GPT-4o
- [ ] Cost reduction from routing: >50% vs GPT-4o-for-everything
- [ ] No thundering herd on recovery (jitter works)
- [ ] Response metadata shows which provider served
- [ ] Langfuse traces include routing decision

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Failure threshold | 5 in 60s | | |
| Reset timeout | 60s | | |
| Simple query patterns | keyword-based | | |
| Routing tiers | 3 (simple/medium/complex) | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Failover time (Azure → Ollama) | | seconds |
| Circuit breaker state transition time | | ms |
| % queries routed to mini model | | of total |
| Cost with routing | | EUR/day |
| Cost without routing | | EUR/day |
| Cost reduction % | | routing savings |
| Retry with jitter — concurrent requests | | thundering herd test |
| Cache fallback response time | | ms |
| Recovery time (HALF-OPEN → CLOSED) | | seconds |

## Screenshots Captured

- [ ] Circuit breaker state transitions (timeline)
- [ ] Cost comparison pie chart (routed vs unrouted)
- [ ] Failover timeline (Azure down → Ollama → recovery)
- [ ] Model routing distribution (% per tier)
- [ ] Response time comparison across providers

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
