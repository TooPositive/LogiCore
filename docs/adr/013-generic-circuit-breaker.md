# ADR-013: Generic Circuit Breaker with Error Classification

## Status
Accepted

## Context
Phase 2's reranker had an inline circuit breaker state machine (~120 lines). Phase 7 needs the same pattern for LLM providers, embedding services, and potentially database clients. The key design question: should the breaker count ALL failures, or classify errors and exclude caller-side bugs (4xx) from tripping?

## Decision
**Generic `CircuitBreaker` class for any async callable, with error classification.** Client errors (4xx, `ValueError`) are excluded — only provider-level failures (5xx, timeouts, rate limits) count toward tripping. State machine: CLOSED → OPEN (at failure threshold) → HALF_OPEN (after timeout) → CLOSED (after success threshold).

## Rationale

| Criteria | With Error Classification (chosen) | Count All Failures | Windowed Counting |
|----------|-----------------------------------|-------------------|------------------|
| User sending malformed requests | Does NOT trip breaker | TRIPS breaker — shuts down healthy provider | TRIPS breaker |
| Provider returning 500 | Counts toward threshold | Counts toward threshold | Counts in time window |
| Implementation complexity | `excluded_exceptions` tuple | Simpler | Sliding window data structure |
| False trips | Only on real provider failures | On any caller bug | On failure bursts in window |

**State transitions:**
- HALF_OPEN → any failure → immediate re-OPEN (conservative recovery)
- HALF_OPEN → success threshold reached → CLOSED
- CLOSED → success → reset failure counter (prevents slow-burn accumulation)

## Consequences
- Extracted from Phase 2's reranker — `CircuitBreakerReranker` now delegates to the generic breaker, removing ~60 lines of duplication
- Consecutive failure counting (not windowed) — simpler and equivalent for blocking LLM calls where failures are naturally consecutive
- `success_threshold` is configurable: reranker uses 1 (original behavior), LLM providers use 3 (more conservative recovery)
- When to revisit: at >100 concurrent calls where failure interleaving makes consecutive counting unreliable, switch to windowed
- Metrics tracked: total calls, failures, trips, current state — exposed via `/api/v1/analytics/resilience`
