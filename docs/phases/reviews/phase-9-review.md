---
phase: 9
phase_name: "The Fleet Guardian -- Real-Time Streaming & Event-Driven AI"
date: "2026-03-09"
score: 27/30
verdict: "PROCEED"
---

# Phase 9 Architect Review: The Fleet Guardian -- Real-Time Streaming & Event-Driven AI

## Score: 27/30

| Category | Score | Weight |
|---|---|---|
| Framing Quality | 9/10 | 33% -- are conclusions useful to a CTO? |
| Evidence Depth | 8/10 | 33% -- do benchmarks have enough cases, categories, and boundaries to back the claims? |
| Architect Rigor | 5/5 | 17% -- security model sound, negative tests, benchmarks designed to break things? |
| Spec Compliance | 5/5 | 17% -- was the promise kept? |

## Framing Failures Found

| Where | Junior Framing (current) | Architect Reframe (fix) | Impact |
|---|---|---|---|
| Tracker "Normal event filter rate: 100% (100/100 normal events)" | Reports a percentage backed by one controlled test. Does not address whether real-world telemetry with borderline readings (e.g., 7.9C on 8.0C threshold) achieves the same rate. | "Two-tier processing is a physical necessity at streaming scale: synchronous LLM at 1K msgs/sec creates a 500-second backlog per second. 100% filter rate on normal readings (n=100) + >80% on mixed simulated routes (5 trucks, 30 min) confirms viability. BOUNDARY: filter rate degrades as margin shrinks (pharma with 2.0C margin vs general freight with 5.0C margin). Recommend: per-cargo-class threshold profiles." | LOW -- the underlying analysis is architect-grade, the tracker metric just reads as a test count |
| Tracker "Simulator mixed filter rate: >80%" | Reports a loose threshold without specifying exact value or what the non-filtered 20% comprises. | "On 30-minute simulated routes (5 trucks, 3 anomaly injection points), 80-85% of events are filtered as normal. The remaining 15-20% includes: injected anomalies (correct alerts), drift detections during ramp-up periods, and z-score triggers on sudden readings. DECISION: the false-alarm rate within that 15-20% determines operational overhead. Recommend: track false-positive rate per alert type once integrated with real Kafka." | LOW -- the context is there in the code, just not surfaced in tracker |
| Tracker "Z-score minimum data: Requires 5+ readings" | States a configuration without framing the design decision. | "Z-score on fewer than 5 readings produces random noise, not signal. At n=4, a single outlier in a normal distribution has ~4% false-positive rate. n=5 is the minimum for the baseline variance calculation to be meaningful. WHEN THIS CHANGES: for trucks with high-frequency sampling (1/sec vs 1/15sec), consider raising to n=20 for the same statistical power." | LOW -- correct decision, just framed as config |

## Evidence Depth Failures Found

| Claim | Cases (n) | Credible? | Missing Categories | Boundary Found? | Phase Teaser |
|---|---|---|---|---|---|
| Two-tier filter rate >95% on normal events | 100 normal + 100 mixed + simulator pipeline | YES -- controlled and realistic scenarios | Borderline readings (7.5-7.9C on 8.0C threshold), cargo-class-specific margins | No -- all tests use 5.0C margin | Phase 12: per-cargo-class threshold profiles |
| Rate-of-change drift catches slow drift | 5 drift scenarios across unit + E2E | YES -- covers gradual rise, stable baseline, configurable threshold, per-truck isolation, E2E slow drift | Drift in falling direction (frozen cargo), non-linear drift (step changes), ambient temperature interference | Boundary found: requires 2+ readings over 1+ minute | Phase 12: ambient temperature compensation |
| Alert deduplication prevents flooding | 5 dedup tests (suppress, expiry, cross-truck, cross-type, E2E flooding) | YES -- covers key dedup behaviors | Multi-type simultaneous alerts on same truck, dedup state persistence across consumer restarts | Boundary found: 5-minute window configurable | Phase 12: persistent dedup state in Redis |
| Cross-session memory changes behavior | 5 memory tests (stateless vs memory, recurring escalation, write-back, pattern detection, threshold check) | YES -- covers the behavioral difference | Memory poisoning (injected fake history), memory eviction under pressure (Redis OOM), stale pattern (pattern from 2 years ago still triggers) | Boundary found: 2+ similar alerts triggers escalation | Phase 10: memory poisoning defense |
| 3-tier memory (Redis + PostgreSQL) | 16 memory store tests + 2 E2E | YES -- covers all tiers, TTL, trim, count, SQL injection, write-back logic | Redis connection failure fallback, PostgreSQL connection failure fallback, cross-tier consistency (Redis evicted but PG still has pattern) | No graceful degradation boundary | Phase 7 circuit breaker patterns available |
| SQL injection defense | 2 tests (parameterized query verification, injection via truck_id) | PARTIAL -- verifies parameterization but only 2 injection vectors | Injection via alert_type, injection via pattern field, second-order injection (malicious pattern stored then retrieved) | No -- only tests basic vector | Phase 10 LLM Firewall: SQL injection hardening |
| LangGraph conditional routing works | 4 routing tests + 2 graph structure tests | YES -- covers all routing conditions (new, few alerts, recurring, mixed types) | Concurrent graph invocations, graph timeout handling, state corruption mid-graph | No concurrency boundary | Phase 12: LangGraph with real checkpointer |
| WebSocket alert broadcast | API tests mention broadcast but no direct WS test | PARTIAL -- WebSocket connect/disconnect tested via E2E but no direct broadcast verification | Multiple concurrent WS clients, WS reconnection after disconnect, backpressure on slow WS clients | No -- WS not load-tested | Phase 12: WS load testing |
| API endpoints work correctly | 12 unit + 3 E2E | YES -- covers status, alerts, resolve, ingest, health, validation (422), 404 | Concurrent API requests, large response payloads, pagination for large alert sets | No pagination boundary | Phase 12: API pagination |

1 out of 9 major claims backed by fewer than 5 cases (SQL injection at n=2). Not over 30% threshold, so no forced DEEPEN BENCHMARKS.

## What a CTO Would Respect

The two-tier processing architecture is the centerpiece, and it is framed correctly: this is not an optimization, it is a physical necessity. The math is compelling -- at 1K msgs/sec, synchronous LLM processing creates a 500-second backlog per second of ingestion, making the system literally impossible to operate without rule-based filtering. The rate-of-change detection closes the most expensive gap (EUR 207,000 per slow drift incident) with a zero-cost rule (no LLM, no external call, just gradient math on a sliding window). The cross-session memory architecture demonstrates genuine agent sophistication: the system evolves its response based on truck history, automatically escalating from "divert cargo" to "pull truck for maintenance" when patterns emerge. The cost quantification throughout is precise and decision-relevant (EUR 0.075/day vs EUR 662/day, EUR 3,500-10,500/year memory savings).

## What a CTO Would Question

"You have the Kafka consumer/producer classes but no test against a real Kafka broker. How do you know this works under backpressure? What happens when the consumer falls behind?" The answer is that Kafka infrastructure is domain-agnostic and tested with mocks at the interface level -- real Kafka integration is deferred to Phase 12. A CTO running 10,000 trucks would accept this for an architecture demo but would want consumer lag metrics and partition rebalancing tests before any production conversation. The WebSocket broadcast also lacks a direct test -- the E2E tests prove the API routes work, but there is no test proving that when an alert is ingested, connected WebSocket clients actually receive it.

## Architect Rigor Checklist

| Check | Status | Note |
|---|---|---|
| Security/trust model sound | PASS | All PostgreSQL queries use $N parameterized SQL. SQL injection via truck_id explicitly tested and blocked. Pydantic validation at API boundaries (422 for out-of-range temperatures). No string interpolation anywhere in SQL. |
| Negative tests | PASS | Boundary conditions tested: exact threshold (no alert), just above threshold (alert). Invalid JSON in Kafka consumer handled gracefully. Handler errors caught without crashing consumer. Graph invocation errors caught without crashing agent. Invalid temperature (200C) rejected by API with 422. Nonexistent alert resolve returns 404. |
| Benchmarks designed to break | PASS | 100-event filter rate test proves zero false positives. Mixed-event test verifies only anomalous events trigger alerts. Dedup expiry test proves alerts resume after window. Cross-truck isolation test proves no history contamination. Stale data test proves warning tag applied. |
| Test pyramid | PASS | 129 unit tests (fast, mocked), 0 integration (deferred with rationale -- needs real Kafka/Redis/PG), 10 E2E (full pipeline with mocked externals). Pyramid is appropriate: rule-based detection correctness matters more than integration at demo stage. |
| Spec criteria met | PASS | 8 of 12 spec criteria met or proven. 4 deferred with documented rationale: Kafka throughput test (needs real Kafka), RAG cargo lookup (Phase 1 dependency), Langfuse cost tracking (Phase 4 dependency), semantic cache (Phase 7 dependency). No criteria silently skipped. |
| Deviations documented | PASS | 3 deviations documented: Next.js dashboard deferred to Phase 12, Kafka integration tests deferred, no Langfuse integration in this phase. Each has clear rationale. Graph routing uses 2+ threshold instead of spec's 3+ (with explanation: "with current alert, that's 3 total"). |

## Benchmark Expansion Needed

These are future-phase items, not blockers.

1. **Borderline temperature readings** (Phase 12 integration)
   - Feed 100 readings at 7.5-8.0C with 8.0C threshold
   - Verify: no threshold alerts at 7.9C, alert at 8.1C
   - Test configurable margins per cargo class (pharma: 2.0C, general: 5.0C)
   - Expected: margin config changes filter rate from 95% to 85% for tight-margin cargo

2. **Memory poisoning defense** (Phase 10 LLM Firewall)
   - Inject fake history entries via Redis (simulating compromised client)
   - Verify: agent does not escalate to maintenance on fabricated patterns
   - Test: rate-limit memory writes, validate entry source
   - Expected: need authentication on memory write path

3. **Kafka consumer under backpressure** (Phase 12 integration)
   - Produce 10K msgs/sec to real Kafka, consumer processing at 1K/sec
   - Measure: consumer lag growth, alert latency degradation
   - Test: what happens when lag exceeds 30s/300s/5min thresholds
   - Expected: staleness tagging catches stale alerts, but consumer needs backpressure config

4. **WebSocket broadcast verification** (Phase 12 full-stack)
   - Connect 10 WS clients, ingest anomalous reading
   - Verify: all 10 clients receive the alert within 1 second
   - Test: slow client doesn't block broadcast to fast clients
   - Expected: current sequential broadcast blocks on slow client -- need async fan-out

5. **Graceful degradation on memory tier failure** (Phase 7 resilience)
   - Simulate Redis down during memory_lookup_node
   - Verify: agent falls back to investigation (no history = treat as new truck)
   - Test: PostgreSQL down during write_memory_node
   - Expected: agent should still complete notification, just skip memory write
   - Phase 7 circuit breaker patterns are already available for this

## Gaps to Close (ranked by "CTO impression" impact)

1. **WebSocket broadcast needs direct test.** The broadcast function exists and is wired into the ingest endpoints, but no test verifies that connected WebSocket clients actually receive alerts. This is a gap a CTO would notice during a demo. Add a test that connects via WS, ingests a reading, and asserts the WS message arrives. (Test gap, not code gap.)

2. **SQL injection tests should cover more vectors.** Currently only truck_id injection is tested. Add injection via alert_type parameter and via the pattern field in store_pattern. The parameterized queries handle this correctly already -- the tests just need to prove it for more entry points. (Evidence gap, not code gap.)

3. **Tracker should note that routing threshold is 2+ not 3+.** The spec says "3 anomalies in 25 days" triggers escalation. The implementation uses 2+ previous alerts (so 3 total including current). The tracker mentions this but it could be clearer that this matches the spec's intent (2 previous + 1 current = 3 total).

## Architect Recommendation: PROCEED

The phase demonstrates three architect-level insights that a CTO would immediately recognize:

1. **Two-tier processing is not optional -- it is a physical constraint.** At streaming scale, synchronous LLM processing creates an impossible backlog. The 8,826x cost reduction (EUR 662/day to EUR 0.075/day) is not a nice-to-have efficiency gain; it is the difference between a system that can operate and one that cannot.

2. **Rate-of-change detection closes the most expensive gap.** Threshold-only detection is the default approach every junior architect would build. It misses 40% of temperature incidents (slow drifts). Each missed drift costs EUR 207,000. Rate-of-change detection catches it with zero additional cost (no LLM, no external service -- just gradient math on the readings already in memory).

3. **Cross-session memory transforms a stateless agent into one that learns.** The behavioral difference between "recommend diversion #5" and "recommend pulling from service for maintenance" is not a feature -- it is the difference between an AI that burns money repeating the same advice and one that actually solves the problem. Quantified: EUR 3,500-10,500/year saved for a 50-truck fleet.

The code is clean, well-separated between core/ (Kafka infrastructure) and domains/logicore/ (fleet models, agents, graphs, API), follows TDD throughout, and all 139 tests pass with zero regressions on the 1390-test full suite. Deferred items (real Kafka integration, Next.js dashboard, Langfuse wiring) are correctly categorized as Phase 12 scope and do not undermine the architectural demonstration.

139 tests, 0 failures, lint clean. The phase is solid.
