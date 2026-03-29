# ADR-014: Per-Provider Retry over Cascade-Level Retry

## Status
Accepted

## Context
Phase 7's `ProviderChain` cascades through multiple LLM providers (Azure → Ollama → cache). When a provider fails, the system retries with exponential backoff + jitter before falling back to the next provider. The architectural question: should retry wrap each individual provider, or wrap the entire cascade?

## Decision
**Retry logic lives inside each provider entry** (3 retries, exponential backoff + full jitter). After retry exhaustion, move to the next provider. Don't touch the failed provider again until the circuit breaker probes.

## Rationale

| Approach | Behavior When Azure Is Flaky | Recovery |
|----------|----------------------------|----------|
| **Per-provider (chosen)** | Azure gets 3 retries → all fail → move to Ollama permanently | Circuit breaker HALF_OPEN probes Azure at 60s mark |
| Cascade-level | Azure fails → Ollama → start over → Azure fails again → Ollama → ... | Keeps re-discovering Azure is down every cycle |

**Full jitter**: `delay = random() * min(base * 2^attempt, max_delay)`. With 50 concurrent retries at the same attempt level, produces >20 unique delay values (tested). Prevents thundering herd on provider recovery.

## Consequences
- If Azure recovers mid-retry (between attempt 2 and 3), per-provider still moves to Ollama after exhausting retries — the circuit breaker's HALF_OPEN probe handles recovery at the 60s mark
- Each provider burns through its own retry budget independently — retry exhaustion at one provider doesn't block trying the next
- RetryPolicy is a separate component (Strategy pattern) — swappable per provider. Aggressive retry for flaky providers, conservative for rate-limited ones
- When to revisit: if sub-second recovery detection is needed (faster than the 60s reset timeout), cascade retry with a short retry count (1-2) becomes more attractive
