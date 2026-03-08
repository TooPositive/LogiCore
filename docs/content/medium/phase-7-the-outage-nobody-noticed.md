---
phase: 7
title: "Our AI Survived a 4-Hour Outage. Nobody Noticed."
subtitle: "Circuit Breakers, Invisible Failures, and the EUR 180,000 Question"
slug: phase-7-the-outage-nobody-noticed
series: "LogiCore: Building an Enterprise AI System"
series_position: "7/12"
date: "2026-03-08"
status: draft
word_count: ~3200
tags: ["circuit-breaker", "resilience", "llm-ops", "cost-modeling", "ai-architecture"]
---

# Our AI Survived a 4-Hour Outage. Nobody Noticed.

## The Call Nobody Wants to Get

Tomasz runs the night dispatch at LogiCore Transport. Forty-seven trucks on European routes, twelve of them carrying temperature-controlled pharmaceutical cargo. At 2:47 AM on a Friday, Azure OpenAI starts returning 503 Service Unavailable errors. Five in sixty seconds.

Tomasz doesnt notice. He types "what's the temperature status on truck-4721" into the search bar, gets an answer in two seconds instead of the usual half-second, and moves on. The answer came from a local Ollama model instead of Azure's GPT-5.2. The dashboard tagged it "Served by: ollama/qwen3:8b" in small gray text at the bottom of the response card. Tomasz doesnt read small gray text at 3 AM. He reads the temperature value: 4.2C, within spec.

At 6:30 AM, Azure recovers. The system sends three probe requests. All succeed. Traffic gradually shifts back to Azure. The incident log shows: 247 requests served during outage, zero failures, zero user complaints.

Now imagine the same scenario without the automatic failover. 247 requests hit a dead endpoint. Each one times out after 30 seconds. Dispatchers wait, refresh, wait again. Temperature alerts dont process. At 4:15 AM, truck-4721's refrigeration compressor fails. Nobody catches it for four hours. EUR 180,000 in pharmaceutical cargo, spoiled.

This is Phase 7 of a 12-phase AI system im building for a logistics company. Phase 1 proved embeddings are mandatory for search. Phase 4 built the model router that sends simple queries to cheap models. Phase 6 made the entire pipeline run on a local model with one env var change. Phase 7 asks the question that matters for production: when Azure goes down at 3 AM, does anyone notice?

## The Failure Mode Nobody Tests For

Nassim Taleb talks about antifragility, systems that gain from disorder. I'm not building antifragile AI (maybe thats Phase 12). Im building something simpler: AI that doesnt die when its cloud provider does.

The circuit breaker pattern is well-known. Michael Nygard described it in "Release It!" back in 2007. CLOSED state, count failures, trip to OPEN after a threshold, probe with HALF_OPEN after a timeout. Every distributed systems engineer has seen the state diagram.

But heres what Nygard's original pattern misses for LLM APIs: the 200-OK-garbage problem.

When Azure has a partial degradation event, the endpoint doesnt always return 5xx errors. Sometimes it returns 200 OK with an empty string. Or a response thats just whitespace. Your circuit breaker sees a successful response. Your monitoring dashboard shows zero errors. Your users see an empty answer box.

This is what Donella Meadows would call a missing feedback loop. The system has no way to distinguish "the provider answered" from "the provider answered with nothing." Without that feedback, the circuit breaker cant trip, the fallback cant engage, and every request keeps hitting a provider thats technically alive but functionally dead.

The fix is embarrassingly simple. A quality gate that checks response length after stripping whitespace:

```python
class ResponseQualityGate:
    _INVISIBLE_CHARS = "\u200b\ufeff\u200c\u200d\u00ad\u2060"

    def __init__(self, min_length: int = 10) -> None:
        self.min_length = min_length

    def is_acceptable(self, response: LLMResponse) -> bool:
        content = response.content.strip()
        for char in self._INVISIBLE_CHARS:
            content = content.replace(char, "")
        content = content.strip()
        return len(content) >= self.min_length
```

Except its not embarrassingly simple, coz Python's `str.strip()` does not strip Unicode zero-width characters. U+200B (zero-width space) and U+FEFF (byte order mark) both pass `len()` checks, both look like "content" to naive validation, and both contain exactly zero visible characters. A malfunctioning provider returning a hundred zero-width spaces looks like a 100-character response to your monitoring. Found that during code review, not in production. The gate explicitly strips six invisible Unicode characters before checking length.

## The Architecture: Composition Over Inheritance

Gene Kim's constraint theory from "The Phoenix Project" suggests that system throughput is limited by its bottleneck. For LLM-dependent systems, that bottleneck is provider availability. Everything downstream (agents, RAG, audit workflows) stops when inference stops.

The resilience architecture is three components composed together. Each is independently replaceable:

```python
class ResilientLLM:
    def __init__(
        self,
        router: ModelRouter,
        default_chain: ProviderChain,
        tier_chains: dict[QueryComplexity, ProviderChain] | None = None,
    ) -> None:
        self._router = router
        self._default_chain = default_chain
        self._tier_chains = tier_chains or {}

    async def generate(self, prompt: str, **kwargs) -> ProviderChainResponse:
        route = await self._router.classify(prompt)
        chain = self._tier_chains.get(route.complexity, self._default_chain)
        return await chain.generate(prompt, **kwargs)
```

ModelRouter (built in Phase 4) classifies query complexity. ProviderChain (built in Phase 7) handles failover. ResilientLLM wires them together. Neither component knows the other exists. Swapping the router requires zero changes to the chain. Swapping the chain requires zero changes to the router.

This matters coz the alternative (one class that classifies, retries, fails over, and caches) becomes unmaintainable at the third feature request. Separation of concerns isnt just clean code ideology. Its the difference between "add a new provider" being a 10-line change vs a 200-line refactor.

## The Hard Decision: Where Does Retry Live?

I had two options for retry logic and picked the less obvious one.

| Approach | How It Works | Failure Mode |
|---|---|---|
| **Cascade-level retry** | Retry the WHOLE chain: Azure -> Ollama -> cache -> start over | Azure is flaky. You retry the cascade. Azure fails again. You go to Ollama. Azure is still flaky on the next cycle. You keep bouncing back. |
| **Per-provider retry** (chosen) | Retry WITHIN each provider, then move to next | Azure gets 3 retries with exponential backoff. All fail. Move to Ollama permanently. Dont touch Azure again until the circuit breaker probes. |

The per-provider approach means retry exhaustion at one provider doesnt block trying the next. Each provider gets its own retry budget. When Azure is dying, you burn through Azure's retries once, then stop hitting it. The cascade approach keeps re-discovering that Azure is down.

Martin Kleppmann makes a related point in "Designing Data-Intensive Applications" about the difference between detecting failure and recovering from it. Per-provider retry handles detection (is Azure really down, or just slow?). The circuit breaker handles recovery (when should we try Azure again?). Separating these concerns means each can be tuned independently.

The retry uses full jitter to prevent thundering herd:

```python
def calculate_delay(self, attempt: int) -> float:
    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
    if self.jitter:
        delay = random.random() * delay
    return delay
```

Without jitter, fifty clients retrying at the same exponential delay create a synchronized spike that can re-trip a recovering provider. Full jitter (random between 0 and the calculated delay) spreads retries across the entire window. Tested: 50 concurrent retries produce more than 20 unique delay values at the same attempt level.

## The Evidence: Stress-Testing the Cost Model

The headline number is 83.5% cost reduction through tiered model routing. EUR 2.28/day vs EUR 14.00/day at 1000 queries, routing simple status lookups to GPT-5 nano (EUR 0.0004/query) instead of GPT-5.2 (EUR 0.014/query).

But that number assumes 70% of queries are simple, 20% medium, 10% complex. A logistics CTO will ask: "what if our mix is different?"

So I stress-tested across six distributions:

| Distribution (simple/medium/complex) | Savings | Verdict |
|---|---|---|
| 100/0/0 (all simple) | ~97% | Max savings. Unrealistic but proves the ceiling. |
| 70/20/10 (baseline) | ~83% | EUR 351/month at 1000 queries/day |
| 50/30/20 (balanced) | ~68% | Still strong. More medium queries barely dent savings. |
| 30/30/40 (complex-heavy) | ~45% | EUR 190/month. Lower but still covers engineering cost. |
| 10/20/70 (mostly complex) | ~20% | Marginal. Consider whether routing complexity is justified. |
| 0/0/100 (all complex) | <1% | Routing adds classifier cost with zero benefit. |

The crossover where routing stops being worth the engineering investment is around 90% complex queries. Below that, even small percentages of simple and medium queries justify routing because GPT-5 nano is 35x cheaper than GPT-5.2. The savings decrease monotonically as complex percentage increases (tested across 11 distribution points with no anomalous crossovers).

Daniel Kahneman would probably point out that the 83.5% number anchors the discussion regardless of context. Presenting it with the sensitivity analysis prevents that anchor from becoming misleading. A CTO running a financial audit shop (80% complex queries) needs to know their savings are ~30%, not 83%.

## The Governance Gap

The circuit breaker solves availability. But availability without quality governance is dangerous.

When Azure goes down and traffic shifts to Ollama's local model, the system keeps answering. But the local model might have lower accuracy on complex financial queries. Phase 3's invoice auditor has an auto-approve band: discrepancies under EUR 50 get approved automatically. At 3 AM, with a degraded model, you dont want auto-approved financial decisions.

The response carries a structural flag:

```python
@dataclass(frozen=True)
class ProviderChainResponse:
    content: str
    model: str
    provider_name: str
    fallback_used: bool
    cache_used: bool
    disclaimer: str | None = None

    @property
    def is_degraded(self) -> bool:
        return self.fallback_used or self.cache_used
```

Downstream systems check this flag. Auto-approve path: if `is_degraded`, force human review regardless of the discrepancy amount. Financial decisions: if `cache_used`, reject entirely (a cached response is stale by definition). This isnt a business rule that can be bypassed by a config change. Its a structural property of the response type.

Peter Drucker's line about "what gets measured gets managed" applies in reverse: what gets flagged gets governed. Without the `is_degraded` flag, the system would silently serve lower-quality answers during outages. With it, every downstream consumer can make informed decisions about how to handle degraded responses.

## What Breaks

Three honest boundaries:

The failover latency (<100ms) is architectural reasoning, not measured. Skipping a tripped circuit breaker involves no network call, so its effectively instantaneous. But I havent instrumented it under real load with real providers. Phase 12 will.

The cost model assumes a 70/20/10 query distribution thats not validated against production data. The sensitivity analysis covers the range, but the "typical logistics distribution" claim is an assumption. Phase 12 will measure the actual distribution from production query logs.

The degraded mode governance proves the contract (the `is_degraded` flag works) but doesnt prove the end-to-end integration. The governance functions live in test code, not in Phase 3's actual HITL gateway. Wiring them is Phase 8/12 scope. This is an honest gap between "the API contract works" and "the business workflow respects it."

## What Id Do Differently

I extracted the circuit breaker from Phase 2's reranker module, which already had an inline state machine. Should have built it as a generic component from the start. The extraction saved ~60 lines of duplication and now any new external service (embedding provider, database client, MCP tool) gets circuit breaking by plugging into the same generic class.

Werner Vogels' "everything fails all the time" principle should have been Phase 2 thinking, not Phase 7. The reranker circuit breaker proved the pattern worked. I just didnt generalize it soon enough. In a real project, Id build the generic CircuitBreaker alongside the first external service integration, not after the fourth.

The quality gate is deliberately simple (length check). A more sophisticated approach would validate response structure (is the JSON parseable? does it contain expected fields?). But structure validation is domain-specific and belongs in the agent layer, not the provider chain. The chain's job is "did the provider return something?" The agent's job is "did the provider return something useful for my task."

## Vendor Lock-In & Swap Costs

The ProviderChain is provider-agnostic by design. Adding a new provider:

| Component | Swap Cost | What Changes |
|---|---|---|
| LLM Provider | ~50 lines | Implement LLMProvider Protocol (generate, generate_structured, model_name). Add to factory. |
| Circuit Breaker | 0 lines | Generic. Works with any async callable. |
| Retry Policy | 0 lines | Generic. Exception types are configurable. |
| Quality Gate | 0 lines | Operates on LLMResponse, not provider-specific. |
| Model Router | 0 lines | Routes by query complexity, not by provider. |

The entire resilience layer is a composition of domain-agnostic components. Switching from Azure to Anthropic or Cohere requires implementing one Protocol with three methods. The circuit breaker, retry, quality gate, and router dont change.

Phase 7 of 12 in the LogiCore series. Next: EU regulators want an immutable audit trail of every AI decision. Compliance isnt optional anymore.
