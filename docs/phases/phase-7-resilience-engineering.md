# Phase 7: "Resilience Engineering" — Circuit Breakers, Model Routing & Fallback Chains

## Business Problem

Phase 6 gave us a provider abstraction — swap Azure for Ollama with a config change. But in production, you don't get a polite notification before Azure goes down. It happens at 3 AM on a Friday. Rate limits hit without warning. And you're burning $0.014 per query on GPT-5.2 for simple "what's the delivery status?" lookups that a $0.0004 GPT-5 nano call could handle.

**CTO pain**: "Azure had a 4-hour outage last month. Our entire AI system was dead. And why are we paying GPT-4o prices for simple lookups?"

## Real-World Scenario: LogiCore Transport

**Feature: AI That Never Goes Down**

Friday, 3 AM. Azure OpenAI returns 5 consecutive 503 errors in 60 seconds. The circuit breaker flips to OPEN.

**What happens without Phase 7**: Every request fails. The fleet monitoring dashboard shows errors. Temperature alerts aren't processed. Anomalies go undetected for 4 hours until Azure recovers. Cost: one undetected temperature spike on truck-4721 = €180K spoiled pharmaceutical cargo.

**What happens with Phase 7**: Circuit breaker detects 5 failures, flips to OPEN, routes all traffic to Ollama (local Llama 4 Scout). Response time increases from 500ms to 2s — but every request is served. After 60 seconds, HALF-OPEN: one probe request to Azure. Still failing → stays OPEN. After another 60s, Azure responds → gradual traffic shift back.

**Model routing saves money every day**: Hans Muller asks "What's the status of truck-0892?" — simple lookup, no reasoning needed. Model router classifies it as "simple" → sends to GPT-5 nano at €0.0004/query instead of GPT-5.2 at €0.014/query. Legal counsel Stefan Braun asks "Analyze CTR-2024-004 against EU chemical transport regulations" — complex multi-hop reasoning → routes to GPT-5.2 ($1.75/$14 per 1M tokens). Result: 70% of queries are simple, saving €340/day.

**Graceful degradation (last resort)**: All providers down AND Ollama is overloaded? Semantic cache serves the closest matching previous answer with a disclaimer: "This answer is from cache — live AI providers are currently unavailable. Cached at: 2026-03-04 14:23."

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Circuit breaker (CLOSED/OPEN/HALF-OPEN) | AI switches to backup automatically, zero downtime | No more "AI is down" calls to IT at 3 AM |
| Model routing by query complexity | Same search bar, optimal model per question | 70% cost reduction without sacrificing quality on hard questions |
| Fallback chain | Worst case: cached answer with disclaimer, not an error page | Users always get something useful, even during total outage |
| Retry with jitter | Invisible — requests don't pile up on recovery | No "thundering herd" crash when the primary provider comes back |
| Response metadata | Small tag: "Served by: ollama/llama4-scout" | Full transparency about which AI answered |

## Architecture

```
Incoming Request
  → Query Classifier
  │   ├── Simple (lookup, status check) → Route to small/cheap model
  │   ├── Medium (summarization, extraction) → Route to mid-tier model
  │   └── Complex (multi-hop reasoning, legal analysis) → Route to GPT-5.2/Opus 4.6
  → Provider Chain (ordered by preference)
  │   ├── Primary: Azure OpenAI (GPT-5.2)
  │   │     └── Circuit Breaker: CLOSED → OPEN after 5 failures in 60s
  │   ├── Fallback 1: Ollama (Llama 4 Scout)
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
| `apps/api/src/core/infrastructure/llm/circuit_breaker.py` | Circuit breaker with CLOSED/OPEN/HALF-OPEN states |
| `apps/api/src/core/infrastructure/llm/provider_chain.py` | Ordered fallback chain with per-provider breakers |
| `apps/api/src/core/infrastructure/llm/model_router.py` | Query complexity classifier → model selection |
| `apps/api/src/core/infrastructure/llm/retry.py` | Exponential backoff with jitter, timeout handling |
| `apps/api/src/core/infrastructure/llm/provider.py` | **Modify** — integrate circuit breaker + retry |
| `apps/api/src/core/config/settings.py` | **Modify** — add model routing config, breaker thresholds |
| `apps/api/src/core/api/v1/analytics.py` | **Modify** — add routing stats endpoint |
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
        "simple": ModelTier(models=["gpt-5-nano", "llama4-scout"], max_tokens=500),
        "medium": ModelTier(models=["gpt-5-mini", "llama4-scout"], max_tokens=2000),
        "complex": ModelTier(models=["gpt-5.2", "claude-opus-4.6"], max_tokens=4000),
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
- [ ] Model routing: simple queries → GPT-5 nano, medium → GPT-5 mini, complex → GPT-5.2
- [ ] Cost reduction from routing: >50% compared to GPT-5.2-for-everything
- [ ] Retry with jitter: no thundering herd on provider recovery
- [ ] Response metadata shows which provider served each request
- [ ] Langfuse traces include routing decision and provider used

## Cost of Getting It Wrong

The circuit breaker adds 55ms overhead. Not having one costs EUR 180,000 per incident.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Router misclassifies complex query** | "What's the PharmaCorp rate?" looks simple but requires cross-referencing base rate + Q4 amendment + volume discount. Routed to GPT-5 nano. Gets only the base rate. | EUR 486-3,240/misrouted query | 10-20/month at 5-10% misclassification |
| **Circuit doesn't trip (200 OK, garbage content)** | Azure returns malformed JSON with 200 status. Not counted as failure. Circuit stays closed. Users get nonsense. | EUR 500-5,000 per incident | 1-2/year |
| **Stale cache served during outage** | Fallback chain serves 30-minute-old cached fleet status. Dispatcher sends driver to wrong location. | EUR 200-5,000 (wasted fuel + time + potential cargo risk) | 1-2/year |
| **Quality masked during failover** | All traffic on Llama 4 Scout (88% accuracy) during Azure outage. Auto-approve band still active. Financial decisions at degraded quality. | Hidden: every decision during outage at risk | Per outage event |

**The CTO line**: "The router misclassification rate is the most expensive number in our system. Every 1% of complex queries misrouted to nano costs EUR 5,832/year in wrong financial answers."

### Router Misclassification: The Hidden Cost

The query router saves 84% on LLM costs. But a misclassified complex query costs more than the savings.

| | Correct Routing | Misclassified (complex → nano) |
|---|---|---|
| Cost/query | EUR 0.02 (GPT-5.2) | EUR 0.0004 (nano) |
| Answer quality | Complete (base + amendment + discount) | Partial (base rate only) |
| Business impact | Correct audit | Wrong discrepancy calculation |
| Annual cost of misclassification | — | EUR 58,320-777,600/year at 5-10% rate |

**Rule**: Any query touching contract rates, invoice amounts, or penalty clauses should always route to GPT-5.2 minimum, regardless of apparent simplicity. Add a keyword override list to the router.

### Degraded Mode Governance

When circuit breaker is OPEN (Azure down, traffic on Ollama):

1. **Disable auto-approve** on all financial decisions → force HITL review
2. **Add disclaimer** to all responses: "Served by local model — verify critical decisions"
3. **Log degraded-mode flag** in Langfuse for post-incident quality review
4. **Alert operations** — don't just route silently, surface that the system is degraded

## LinkedIn Post Angle
**Hook**: "Our AI system survived a 4-hour Azure outage. Nobody noticed."
**Medium deep dive**: "Circuit Breakers for LLM APIs: How We Built Automatic Failover Across 3 AI Providers" — full implementation with state diagrams, cost analysis, and outage simulation results.

## AI Decision Tree: Query Routing

```
Query arrives
  ├─ Complexity classifier (GPT-5 nano, ~€0.00001/classification)
  │   ├─ Simple (lookup/yes-no)?
  │   │   └─ GPT-5 nano ($0.05 in / $0.40 out per 1M tokens)
  │   │       ~€0.0004/query — status checks, tracking lookups
  │   ├─ Medium (summary/RAG generation)?
  │   │   └─ GPT-5 mini ($0.25 in / $2.00 out per 1M tokens)
  │   │       ~€0.003/query — document summaries, triage, RAG answers
  │   └─ Complex (multi-hop reasoning)?
  │       └─ GPT-5.2 ($1.75 in / $14.00 out per 1M tokens)
  │           ~€0.014/query — legal analysis, multi-document reasoning
  └─ Provider health check
      ├─ Azure healthy? → Use cloud model (GPT-5 tier)
      └─ Azure down? → Circuit breaker → Llama 4 Scout (local, $0)
```

### Cost Savings: Routed vs Unrouted

Assume 1,000 queries/day with typical distribution: 70% simple, 20% medium, 10% complex.

| Strategy | Simple (700) | Medium (200) | Complex (100) | Daily Total |
|---|---|---|---|---|
| **Unrouted** (all GPT-5.2) | 700 × €0.014 = €9.80 | 200 × €0.014 = €2.80 | 100 × €0.014 = €1.40 | **€14.00** |
| **Routed** (tiered) | 700 × €0.0004 = €0.28 | 200 × €0.003 = €0.60 | 100 × €0.014 = €1.40 | **€2.28** |
| **Savings** | | | | **€11.72/day (84%)** |

Over 30 days: **€351 saved/month**. The classifier itself costs ~€0.01/day (1,000 nano calls). ROI is immediate.

## Decision Framework: Circuit Breaker Thresholds

### When to Trip the Breaker

| Parameter | Recommended Value | Rationale |
|---|---|---|
| Failure threshold | 5 errors in 60s | Tolerates transient blips (1-2 timeouts) without tripping. 5 in 60s = sustained outage. |
| Error types that count | 5xx, timeout (>30s), rate limit (429) | Client errors (400/401) are caller bugs, not provider outage — don't count them. |
| Reset timeout (OPEN → HALF-OPEN) | 60 seconds | Long enough for most transient Azure issues. Short enough to recover fast. |
| Half-open probe count | 1 request | Single probe minimizes exposure. Success → CLOSED. Failure → OPEN again for another 60s. |
| Success threshold (HALF-OPEN → CLOSED) | 3 consecutive successes | Prevents premature return after a single lucky probe. |

### Half-Open Testing Strategy

1. After `reset_timeout` expires, allow exactly **one probe request** through to the primary provider
2. If probe succeeds: move to HALF-OPEN-TESTING, allow 3 more requests
3. If all 3 succeed: transition to CLOSED, resume full traffic
4. If any fail: back to OPEN, restart the timer
5. During HALF-OPEN, all non-probe requests still go to fallback (Llama 4 Scout)

### Cost of Getting It Wrong

| Error Type | What Happens | Cost |
|---|---|---|
| **False positive** (trip too early, cloud is fine) | Routes to Llama 4 Scout unnecessarily. Slower (2s vs 500ms), slightly lower quality on complex queries. | Quality degradation for 60s. ~€0 direct cost (local model is free), but user experience dip. |
| **False negative** (don't trip, cloud is broken) | Requests keep hitting a dead endpoint. Users see errors or 30s timeouts. | Every failed request = wasted time + bad UX. At 100 req/min, 60s delay = 100 failed requests. |
| **Verdict** | **Bias toward false positives.** Fallback to local is cheap. Hammering a broken endpoint is expensive in user trust. |

## Key Metrics to Screenshot
- Circuit breaker state transitions during simulated outage
- Cost comparison: routed vs unrouted (pie chart by model tier)
- Failover timeline: Azure down → Ollama serves → Azure recovers → back to primary
- Model routing distribution: % of queries per tier
- Response time comparison across providers
