# Phase 7: "Resilience Engineering" — Circuit Breakers, Model Routing & Fallback Chains

## Business Problem

Phase 6 gave us a provider abstraction — swap Azure for Ollama with a config change. But in production, you don't get a polite notification before Azure goes down. It happens at 3 AM on a Friday. Rate limits hit without warning. And you're burning $0.03 per query on GPT-4o for simple "what's the delivery status?" lookups that a $0.001 model could handle.

**CTO pain**: "Azure had a 4-hour outage last month. Our entire AI system was dead. And why are we paying GPT-4o prices for simple lookups?"

## Architecture

```
Incoming Request
  → Query Classifier
  │   ├── Simple (lookup, status check) → Route to small/cheap model
  │   ├── Medium (summarization, extraction) → Route to mid-tier model
  │   └── Complex (multi-hop reasoning, legal analysis) → Route to GPT-4o/Opus
  → Provider Chain (ordered by preference)
  │   ├── Primary: Azure OpenAI (GPT-4o)
  │   │     └── Circuit Breaker: CLOSED → OPEN after 5 failures in 60s
  │   ├── Fallback 1: Ollama (Llama 3 8B)
  │   │     └── Circuit Breaker: independent state
  │   └── Fallback 2: Cached Response (semantic cache hit)
  │         └── Last resort: return best cached match + disclaimer
  → Retry Logic
  │   ├── Rate limit (429): exponential backoff + jitter
  │   ├── Server error (5xx): retry up to 3x
  │   └── Timeout: cancel after 30s, try next provider
  → Response
      └── Include metadata: which provider served, latency, cost
```

**Key design decisions**:
- Circuit breaker is per-provider, not global — Azure down doesn't disable Ollama
- Model routing by query complexity saves 50-70% on LLM costs
- Graceful degradation: cached response > no response
- Jitter on retries prevents thundering herd on recovery
- Every response includes which model actually served it (observability)

## Implementation Guide

### Prerequisites
- Phase 6 complete (provider abstraction: Azure ↔ Ollama)
- Phase 4 complete (Langfuse tracing, semantic cache)
- Understanding of circuit breaker pattern

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/infrastructure/llm/circuit_breaker.py` | Circuit breaker with CLOSED/OPEN/HALF-OPEN states |
| `apps/api/src/infrastructure/llm/provider_chain.py` | Ordered fallback chain with per-provider breakers |
| `apps/api/src/infrastructure/llm/model_router.py` | Query complexity classifier → model selection |
| `apps/api/src/infrastructure/llm/retry.py` | Exponential backoff with jitter, timeout handling |
| `apps/api/src/infrastructure/llm/provider.py` | **Modify** — integrate circuit breaker + retry |
| `apps/api/src/config/settings.py` | **Modify** — add model routing config, breaker thresholds |
| `apps/api/src/api/v1/analytics.py` | **Modify** — add routing stats endpoint |
| `scripts/simulate_outage.py` | Simulate Azure outage, verify failover |
| `scripts/benchmark_routing.py` | Cost comparison: routed vs unrouted |
| `tests/unit/test_circuit_breaker.py` | State transition tests |
| `tests/unit/test_model_router.py` | Classification accuracy tests |
| `tests/integration/test_failover.py` | Full failover chain test |

### Technical Spec

**Circuit Breaker**:
```python
class CircuitBreaker:
    """Per-provider circuit breaker.
    CLOSED: normal operation, count failures
    OPEN: reject all calls, wait for reset_timeout
    HALF_OPEN: allow one probe request to test recovery
    """
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    async def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time_since(self.last_failure_time) > self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitOpenError(self.provider_name)

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
```

**Model Router**:
```python
class ModelRouter:
    """Classify query complexity, route to appropriate model tier."""

    TIERS = {
        "simple": ModelTier(models=["gpt-4o-mini", "llama3:8b"], max_tokens=500),
        "medium": ModelTier(models=["gpt-4o", "llama3:8b"], max_tokens=2000),
        "complex": ModelTier(models=["gpt-4o", "claude-opus"], max_tokens=4000),
    }

    async def classify(self, query: str) -> str:
        """Fast classification using small model or heuristics."""
        # Heuristic fast-path
        if self._is_simple_lookup(query):
            return "simple"
        # LLM classification for ambiguous queries
        return await self._llm_classify(query)

    def _is_simple_lookup(self, query: str) -> bool:
        """Keyword-based fast classification."""
        simple_patterns = ["status of", "tracking number", "delivery date",
                          "what time", "how many", "list all"]
        return any(p in query.lower() for p in simple_patterns)
```

**Fallback Chain**:
```python
class ProviderChain:
    """Try providers in order until one succeeds."""

    async def generate(self, prompt: str, tier: str) -> Response:
        for provider in self.get_providers_for_tier(tier):
            try:
                result = await provider.breaker.call(provider.generate, prompt)
                return Response(content=result, provider=provider.name,
                              cost=provider.cost_per_token)
            except (CircuitOpenError, TimeoutError, RateLimitError):
                continue

        # All providers failed — try semantic cache as last resort
        cached = await self.cache.get_closest(prompt, threshold=0.90)
        if cached:
            return Response(content=cached, provider="cache",
                          disclaimer="Served from cache — live providers unavailable")

        raise AllProvidersDownError()
```

### Success Criteria
- [ ] Circuit breaker transitions: CLOSED → OPEN after 5 failures, HALF-OPEN after 60s
- [ ] Azure outage simulation: system automatically falls back to Ollama within 5s
- [ ] All providers down: system serves cached responses with disclaimer
- [ ] Model routing: simple queries → mini model, complex → GPT-4o
- [ ] Cost reduction from routing: >50% compared to GPT-4o-for-everything
- [ ] Retry with jitter: no thundering herd on provider recovery
- [ ] Response metadata shows which provider served each request
- [ ] Langfuse traces include routing decision and provider used

## LinkedIn Post Angle
**Hook**: "Our AI system survived a 4-hour Azure outage. Nobody noticed."
**Medium deep dive**: "Circuit Breakers for LLM APIs: How We Built Automatic Failover Across 3 AI Providers" — full implementation with state diagrams, cost analysis, and outage simulation results.

## Key Metrics to Screenshot
- Circuit breaker state transitions during simulated outage
- Cost comparison: routed vs unrouted (pie chart by model tier)
- Failover timeline: Azure down → Ollama serves → Azure recovers → back to primary
- Model routing distribution: % of queries per tier
- Response time comparison across providers
