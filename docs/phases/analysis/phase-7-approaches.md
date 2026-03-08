---
phase: 7
date: "2026-03-08"
selected: A
---

# Phase 7 Implementation Approaches

## What Already Exists

Before choosing an approach, the inventory of reusable components:

| Component | Location | Reuse Status |
|-----------|----------|-------------|
| CircuitBreakerReranker (CLOSED/OPEN/HALF_OPEN) | `core/rag/reranker.py:253` | Extract generic pattern |
| ModelRouter (keyword override + LLM + escalation) | `core/infrastructure/llm/router.py` | Extend, don't duplicate |
| SemanticCache (RBAC-partitioned) | `core/infrastructure/llm/cache.py` | Use as last-resort fallback |
| LLMProvider Protocol + factory | `core/infrastructure/llm/provider.py` | Extend factory for multi-provider |
| AzureOpenAIProvider, OllamaProvider | `core/infrastructure/llm/` | Wrap with circuit breakers |

The structural gap: `get_llm_provider()` returns ONE provider. Phase 7 needs a provider-per-tier chain with independent circuit breakers.

---

## Approach A: Generic CircuitBreaker + ProviderChain (Extract & Compose)

**Summary**: Extract a generic `CircuitBreaker[T]` from the reranker, build a `ProviderChain` that composes breaker-wrapped providers, connect the existing `ModelRouter` to the chain for tier-based routing.

**Architecture**:
```
ModelRouter.classify(query) → tier
  → ProviderChain.generate(prompt, tier)
    → Provider[0] + CircuitBreaker → try
    → Provider[1] + CircuitBreaker → fallback
    → SemanticCache → last resort
```

**Files**:
- `core/infrastructure/llm/circuit_breaker.py` — Generic `CircuitBreaker` (extracted from reranker pattern)
- `core/infrastructure/llm/provider_chain.py` — `ProviderChain` with per-provider breakers
- `core/infrastructure/llm/retry.py` — Retry with exponential backoff + jitter
- Modify `core/infrastructure/llm/router.py` — Add tier→provider-chain integration
- Modify `core/infrastructure/llm/provider.py` — Multi-provider factory
- Modify `core/rag/reranker.py` — Replace inline CB with generic import
- Modify `core/config/settings.py` — CB thresholds, retry config

**Pros**:
- Reuses ALL existing components (router, cache, CB pattern)
- Generic CB works for rerankers AND LLM providers AND any future service
- Eliminates ~120 lines of duplicated CB logic in reranker
- ModelRouter already has keyword override, confidence escalation — zero rework

**Cons**:
- Refactoring reranker CB to generic requires updating reranker tests
- More files to touch (but smaller changes per file)

**Effort**: M (3-4 days)
**Risk**: Low — pattern is proven in reranker, just generalizing it

---

## Approach B: LLM-Only Circuit Breaker (No Extraction)

**Summary**: Build a new `CircuitBreaker` class specifically for LLM providers in `circuit_breaker.py`. Leave the reranker's CB untouched. Duplicate the state machine logic but specialize it for LLM error types (429, 5xx, timeout).

**Architecture**: Same as A, but the CB is LLM-specific.

**Pros**:
- Fewer files touched (reranker stays as-is)
- LLM-specific error handling (rate limit detection, 200-OK-garbage validation)
- Faster to ship — no refactoring existing code

**Cons**:
- Two independent CB implementations with identical state machines
- Maintenance burden: fix a CB bug in one place, forget the other
- Violates DRY — the reranker CB and LLM CB are 90% identical
- Future services (embedding providers, MCP tools) would need a third copy

**Effort**: S-M (2-3 days)
**Risk**: Medium — technical debt accumulates fast with duplicated patterns

---

## Approach C: Middleware/Decorator Pattern (Wrap Everything)

**Summary**: Instead of a ProviderChain class, use decorators/middleware: `@with_circuit_breaker`, `@with_retry`, `@with_fallback`. Each LLM provider gets wrapped at factory construction time.

**Architecture**:
```python
provider = with_fallback(
    with_circuit_breaker(azure_provider, threshold=5),
    with_circuit_breaker(ollama_provider, threshold=5),
    cache_fallback
)
```

**Pros**:
- Maximum composability — mix and match wrappers
- Each concern is a single decorator
- Easy to unit test each wrapper independently

**Cons**:
- Decorator chains are hard to debug (deep stack traces)
- State management across decorators is awkward (who owns the breaker state?)
- Overkill for 2-3 providers — this pattern shines at 10+ services
- Harder to log which provider actually served (metadata gets lost in wrapper chain)

**Effort**: M-L (4-5 days)
**Risk**: Medium-high — over-engineering for current scale, debugging pain

---

## Recommendation

**Approach A** — Extract & Compose.

The generic CB eliminates duplication, the ProviderChain is the natural composition point, and the existing ModelRouter + SemanticCache plug in without rework. Approach B ships faster but creates debt. Approach C is architecturally elegant but over-engineered for 2 providers.

The key insight from the analysis: **Phase 7 is 60% integration, 40% new code.** The router, cache, and CB pattern already exist. The work is connecting them into a resilient provider chain with proper retry logic and response quality validation.
