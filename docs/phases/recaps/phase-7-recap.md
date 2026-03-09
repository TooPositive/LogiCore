# Phase 7 Technical Recap: Resilience Engineering -- Circuit Breakers, Model Routing & Fallback Chains

## What This Phase Does (Business Context)

A logistics company running 47 trucks on European routes relies on AI for fleet monitoring, invoice auditing, and contract analysis. When Azure OpenAI goes down at 3 AM, every request fails — temperature alerts stop processing, dispatchers can't query truck status, and a refrigeration failure on pharmaceutical cargo goes undetected for 4 hours (EUR 180,000 cost). Phase 7 makes the AI system survive provider outages automatically: circuit breakers detect failures, fallback chains reroute to local models, and tiered routing cuts daily AI costs from EUR 14.00 to EUR 2.28 by sending simple queries to cheap models.

## Architecture Overview

```
User Query
  |
  v
ResilientLLM (orchestrator)
  |
  ├── ModelRouter.classify(prompt) -> QueryComplexity (SIMPLE/MEDIUM/COMPLEX)
  |     (reuses Phase 4 router -- keyword overrides + LLM classification)
  |
  └── ProviderChain (ordered fallback, per-tier or default)
        |
        ├── [Entry 0] Azure OpenAI
        |     ├── CircuitBreaker (CLOSED/OPEN/HALF_OPEN)
        |     ├── RetryPolicy (3 retries, exponential backoff + jitter)
        |     └── ResponseQualityGate (catches 200-OK-garbage)
        |
        ├── [Entry 1] Ollama (local model)
        |     ├── CircuitBreaker (independent state)
        |     └── RetryPolicy
        |
        └── [Last Resort] Cache Lookup (async callback)
              └── Returns cached answer + disclaimer
                  + is_degraded=True, cache_used=True

Output: ProviderChainResponse
  ├── content, model, provider_name, latency_ms
  ├── fallback_used, cache_used, disclaimer
  └── is_degraded (property) -> downstream governance checks this
```

## Components Built

### 1. Generic CircuitBreaker: `apps/api/src/core/infrastructure/llm/circuit_breaker.py`

**What it does**: State machine for any async callable. Tracks consecutive failures, trips to OPEN after a threshold, probes with HALF_OPEN after a timeout, recovers to CLOSED after consecutive successes.

**The pattern**: State Machine with Error Classification. The breaker doesn't just count failures — it classifies them. Client errors (4xx) are excluded because they're caller bugs, not provider failures. Only provider-level failures (5xx, timeouts, rate limits) count toward tripping.

**Key code walkthrough**:
```python
# circuit_breaker.py:114-158 — the core call() method
async def call(self, func, *args, **kwargs):
    self._metrics.total_calls += 1

    # OPEN: check if reset_timeout elapsed -> HALF_OPEN
    if self._state == CircuitState.OPEN:
        elapsed = time.monotonic() - self._last_failure_time
        if elapsed >= self.reset_timeout:
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
        else:
            raise CircuitOpenError(
                provider_name=self.name,
                time_until_reset=self.reset_timeout - elapsed,
            )

    # Execute through the state machine
    try:
        result = await func(*args, **kwargs)
        self._on_success()  # HALF_OPEN: count toward recovery threshold
        return result
    except Exception as exc:
        if self._is_excluded(exc):
            raise  # 4xx: don't count, just re-raise
        self._on_failure()  # CLOSED: increment counter. HALF_OPEN: immediate re-open
        raise
```

**Why it matters**: Without error classification, a user sending malformed requests (400 errors) would trip the circuit breaker, shutting down a healthy provider. The `excluded_exceptions` tuple makes the breaker distinguish "the provider is broken" from "the caller sent garbage."

**The state transitions that matter**:
- `_on_failure()` in HALF_OPEN = immediate back to OPEN (any failure during recovery re-trips)
- `_on_failure()` in CLOSED = increment counter, trip at threshold
- `_on_success()` in HALF_OPEN = count toward `success_threshold` (need 3 consecutive)
- `_on_success()` in CLOSED = reset failure counter (prevents slow-burn accumulation)

**Alternatives considered**: Windowed failure counting (5 failures in 60s window). Rejected because consecutive failures are simpler and just as effective — if you get 5 failures in 60s, they're almost certainly consecutive since each call blocks.

### 2. RetryPolicy: `apps/api/src/core/infrastructure/llm/retry.py`

**What it does**: Exponential backoff with optional full jitter. Wraps any async callable. Only retries on configured exception types (TimeoutError by default).

**The pattern**: Decorator/Wrapper with Configurable Strategy. The retry doesn't know what it's retrying — it's just an async-callable wrapper with a sleep-between-attempts loop.

**Key code walkthrough**:
```python
# retry.py:50-59 — full jitter calculation
def calculate_delay(self, attempt: int) -> float:
    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
    if self.jitter:
        delay = random.random() * delay  # Full jitter: uniform [0, delay]
    return delay
```

**Why full jitter instead of decorrelated jitter**: Full jitter (uniform random between 0 and the calculated delay) is simpler and produces sufficient spread. With 50 concurrent retries at the same attempt level, full jitter produces >20 unique delay values (tested). Decorrelated jitter adds state tracking between attempts with marginal benefit for this use case.

**Why retry lives INSIDE each provider (not at cascade level)**: This is the key architectural decision. Two options:

| Approach | How It Works | Failure Mode |
|---|---|---|
| Cascade-level retry | Retry the WHOLE chain: Azure -> Ollama -> start over | Azure is flaky. You retry the cascade. Azure fails again. You go to Ollama. Azure is still flaky on the next cycle. Keeps bouncing. |
| Per-provider retry (chosen) | Retry WITHIN each provider, then move to next | Azure gets 3 retries. All fail. Move to Ollama permanently. Don't touch Azure again until circuit breaker probes. |

Per-provider means retry exhaustion at one provider doesn't block trying the next. Each provider burns through its own retry budget independently.

### 3. ProviderChain: `apps/api/src/core/infrastructure/llm/provider_chain.py`

**What it does**: Ordered fallback across LLM providers. Each entry has its own CircuitBreaker + optional RetryPolicy. If all providers fail, falls back to a cache lookup callback. Response includes full routing metadata.

**The pattern**: Chain of Responsibility with Composition. Each `ProviderEntry` bundles a provider + breaker + retry. The chain iterates through entries, trying each. The cache is a decoupled callback (`async (str) -> str | None`), not a concrete class.

**Key code walkthrough**:
```python
# provider_chain.py:158-209 — the core fallback loop
async def _try_providers(self, prompt, method="generate", **kwargs):
    self._total_requests += 1
    is_fallback = False

    for i, entry in enumerate(self._providers):
        if i > 0:
            is_fallback = True

        try:
            result = await self._call_provider(entry, prompt, method, **kwargs)

            # Quality gate: catch 200-OK-garbage
            if self._quality_gate and not self._quality_gate.is_acceptable(result):
                entry.breaker._on_failure()  # Count as provider failure
                continue

            # Success — return with metadata
            return ProviderChainResponse(
                content=result.content,
                model=result.model,
                # ... full metadata ...
                fallback_used=is_fallback,
                cache_used=False,
            )
        except (CircuitOpenError, Exception):
            continue  # Try next provider

    # All providers failed — try cache as last resort
    if self._cache_lookup is not None:
        cached = await self._cache_lookup(prompt)
        if cached is not None:
            return ProviderChainResponse(
                content=cached,
                provider_name="cache",
                fallback_used=True,
                cache_used=True,
                disclaimer="This response is from cache -- live AI providers are currently unavailable.",
            )

    raise AllProvidersDownError("All LLM providers are down and no cached response available.")
```

**Why the quality gate calls `entry.breaker._on_failure()` directly**: This is the critical integration point. A provider returning 200 OK with empty content looks like success to the circuit breaker (no exception). The quality gate converts invisible failures into visible ones by manually recording a failure in the breaker. Without this, repeated garbage responses would never trip the circuit, and the system would keep hitting a provider that's technically alive but functionally dead.

**Cache lookup is a callback, not a class**: The chain accepts `CacheLookupFn = Callable[[str], Coroutine[Any, Any, str | None]]`. This decouples it from any specific cache implementation. In production, it wraps the RBAC-partitioned SemanticCache from Phase 4. In tests, it's a simple `AsyncMock`.

### 4. ResponseQualityGate: `apps/api/src/core/infrastructure/llm/provider_chain.py` (lines 41-76)

**What it does**: Validates that a provider actually returned useful content, not empty strings, whitespace, or invisible Unicode characters.

**The pattern**: Validation Gate (pipeline filter). Operates on the response object after the provider call but before the chain accepts it.

**Key code walkthrough**:
```python
# provider_chain.py:41-76
class ResponseQualityGate:
    # str.strip() does NOT strip these — they pass len() but contain zero visible chars
    _INVISIBLE_CHARS = "\u200b\ufeff\u200c\u200d\u00ad\u2060"

    def __init__(self, min_length: int = 10) -> None:
        self.min_length = min_length

    def is_acceptable(self, response: LLMResponse) -> bool:
        content = response.content.strip()          # Standard whitespace
        for char in self._INVISIBLE_CHARS:
            content = content.replace(char, "")      # Unicode invisible chars
        content = content.strip()                     # Re-strip after removal
        return len(content) >= self.min_length
```

**Why explicit char removal, not regex or Unicode category checks**: The gate strips 6 specific invisible characters: U+200B (zero-width space), U+FEFF (byte order mark), U+200C (zero-width non-joiner), U+200D (zero-width joiner), U+00AD (soft hyphen), U+2060 (word joiner). A regex approach (`\p{Cf}`) would also strip legitimate formatting characters. Unicode category checks are broader than needed and harder to reason about. Explicit enumeration means the gate does exactly what's tested and nothing more. Phase 10 (LLM Firewall) expands to comprehensive Unicode normalization.

**The bug this catches**: Azure can return 200 OK with an empty string or whitespace during partial degradation. Your monitoring shows zero errors (all 200s). Your circuit breaker stays CLOSED. Your users see empty answer boxes. The quality gate converts this silent failure into a breaker failure.

### 5. ProviderChainResponse: `apps/api/src/core/infrastructure/llm/provider_chain.py` (lines 79-104)

**What it does**: Frozen dataclass carrying the LLM response plus routing metadata (which provider served, fallback status, cache status, disclaimer text).

**The pattern**: Value Object with Derived Property. The `is_degraded` property is computed from two booleans, creating a single flag for downstream governance.

**Key code walkthrough**:
```python
# provider_chain.py:79-104
@dataclass(frozen=True)
class ProviderChainResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    provider_name: str
    fallback_used: bool
    cache_used: bool
    disclaimer: str | None = None

    @property
    def is_degraded(self) -> bool:
        return self.fallback_used or self.cache_used
```

**Why `is_degraded` is a property, not a constructor argument**: It's a derived fact, not independent data. You can't have `is_degraded=False` with `fallback_used=True` — that would be a lie. Making it a property eliminates this class of bugs.

**Why frozen dataclass, not Pydantic**: Consistency with `LLMResponse` (also a frozen dataclass from Phase 6). Could have used Pydantic, but the response is an internal data carrier, not an API boundary model. Frozen dataclass is lighter and makes immutability explicit.

### 6. ResilientLLM: `apps/api/src/core/infrastructure/llm/resilient_llm.py`

**What it does**: Orchestrator composing the Phase 4 ModelRouter with Phase 7 ProviderChains. Classifies query complexity, routes to the appropriate tier-specific or default chain, tracks routing stats.

**The pattern**: Composition over Inheritance (Facade). Neither the router nor the chain knows the other exists. ResilientLLM wires them together. Swapping the router requires zero changes to the chain. Swapping the chain requires zero changes to the router.

**Key code walkthrough**:
```python
# resilient_llm.py:142-161
async def generate(self, prompt: str, **kwargs) -> ProviderChainResponse:
    route = await self._router.classify(prompt)
    chain = self._tier_chains.get(route.complexity, self._default_chain)

    self._total_routed += 1
    complexity_key = route.complexity.value
    self._by_complexity[complexity_key] = (
        self._by_complexity.get(complexity_key, 0) + 1
    )

    return await chain.generate(prompt, **kwargs)
```

**Why not one big class**: The alternative (one class that classifies, retries, fails over, and caches) becomes unmaintainable at the third feature request. Adding a new provider is a 10-line change (implement LLMProvider Protocol, add to factory). Adding a new retry strategy is a swap of the RetryPolicy instance. Neither touches the other. Separation of concerns scales with feature count.

### 7. Reranker Refactoring: `apps/api/src/core/rag/reranker.py` (CircuitBreakerReranker)

**What it does**: Refactored to use the generic CircuitBreaker instead of an inline state machine. Removed ~60 lines of duplicated state management.

**Key code walkthrough**:
```python
# reranker.py:259-296 — before: 120 lines with inline state machine. After:
class CircuitBreakerReranker(BaseReranker):
    def __init__(self, primary, fallback, failure_threshold=3, recovery_timeout=60.0):
        self._breaker = CircuitBreaker(
            name="reranker",
            failure_threshold=failure_threshold,
            reset_timeout=recovery_timeout,
            success_threshold=1,  # Original behavior: one success closes
        )

    async def rerank(self, query, results, top_k=5):
        try:
            return await self._breaker.call(self.primary.rerank, query, results, top_k)
        except CircuitOpenError:
            return await self.fallback.rerank(query, results, top_k)
        except Exception:
            return await self.fallback.rerank(query, results, top_k)
```

**Why `success_threshold=1`**: The original reranker behavior was "one successful call = provider is back." The generic CircuitBreaker defaults to 3. Passing `success_threshold=1` preserves backward compatibility. This is documented as a deliberate choice in the tracker.

### 8. Settings & Factory: `apps/api/src/core/config/settings.py` + `resilient_llm.py`

**What it does**: 7 new Settings fields for resilience configuration. `build_provider_chain()` factory builds the chain from Settings, wiring Azure/Ollama providers with breakers, retry, and quality gate.

**The pattern**: Config-Driven Factory. All thresholds are configurable via environment variables. No hardcoded resilience values. The factory decides provider order based on `settings.llm_provider` ("azure" or "ollama").

### 9. Analytics Endpoint: `apps/api/src/core/api/v1/analytics.py`

**What it does**: `GET /api/v1/analytics/resilience` returns circuit breaker states and routing statistics.

**The pattern**: Dependency Injection via Factory Function. `create_analytics_router()` takes `provider_chain` as an optional parameter. No chain = empty response (backward compatible). This avoids global state and makes the endpoint testable.

## Key Decisions Explained

### Decision 1: Per-Provider Retry (not Cascade-Level)

- **The choice**: Retry logic lives inside each provider entry (3 retries with exponential backoff + jitter), then move to next provider
- **The alternatives**: Cascade-level retry (retry the entire chain: Azure -> Ollama -> start over)
- **The reasoning**: Per-provider prevents "bounce-back" — when Azure is flaky, cascade retry keeps re-discovering it's down. Per-provider exhausts Azure's retries once, then moves on permanently until the circuit breaker probes
- **The trade-off**: If Azure recovers mid-retry (e.g., between attempt 2 and 3), per-provider still moves to Ollama after exhausting retries. Cascade would try Azure again. But the circuit breaker's HALF_OPEN probe handles this recovery path at the 60s mark
- **When to revisit**: If you need sub-second recovery detection (faster than the 60s reset timeout), cascade retry with a short retry count (1-2) becomes more attractive
- **Interview version**: "We chose per-provider retry over cascade-level because cascade keeps bouncing back to a dying provider. Per-provider exhausts each provider's retry budget independently, then moves on. Recovery is handled by the circuit breaker's probe mechanism, not retry."

### Decision 2: Quality Gate Over Content Validation

- **The choice**: Length check after stripping whitespace + 6 Unicode invisible characters
- **The alternatives**: JSON structure validation, semantic similarity to prompt, LLM-based response grading
- **The reasoning**: The gate targets 200-OK-garbage during partial degradation, not adversarial content. Structure validation is domain-specific (belongs in agents, not the chain). LLM grading adds latency. Length check is O(n) with zero network calls
- **The trade-off**: A provider returning "I don't know" (19 chars) passes the gate. The gate catches "response looks like something" but not "response is useful." That's the agent's job
- **When to revisit**: If providers start returning plausible-length garbage (hallucinated non-answers), add semantic similarity checking at the agent layer
- **Interview version**: "The quality gate catches the cheapest failure mode — providers returning nothing while claiming success. We strip whitespace AND 6 Unicode invisible characters that Python's strip() misses. Content quality validation belongs at the agent layer, not the infrastructure layer."

### Decision 3: Composition Over Monolith

- **The choice**: CircuitBreaker, RetryPolicy, QualityGate, ProviderChain, ResilientLLM as independent components
- **The alternatives**: Single `ResilientProvider` class handling everything
- **The reasoning**: Each component is independently replaceable and testable. Adding a new provider = implement LLMProvider Protocol (~50 lines). The circuit breaker works for any async callable (rerankers, embedding providers, database clients)
- **The trade-off**: More files, more indirection. A developer reading the code has to understand 5 components instead of 1
- **When to revisit**: Never. This is the right level of decomposition for this problem
- **Interview version**: "We composed five independent components instead of building one monolithic resilient provider. The CircuitBreaker is generic — we extracted it from the reranker and now it protects any async callable. Adding a new LLM provider is 50 lines: implement the Protocol, add to the factory."

### Decision 4: Frozen Dataclass for Response

- **The choice**: `ProviderChainResponse` as a frozen dataclass with `is_degraded` as a computed property
- **The alternatives**: Pydantic model, mutable dataclass
- **The reasoning**: Frozen = immutable after creation. `is_degraded` as a property (not a field) means it can't be set independently of `fallback_used` and `cache_used` — eliminates inconsistent state
- **The trade-off**: Can't use Pydantic's serialization features. But this is an internal data carrier, not an API model
- **When to revisit**: If this needs to cross API boundaries (serialization to JSON), switch to Pydantic
- **Interview version**: "The response is a frozen dataclass with is_degraded as a computed property rather than a stored field. This means you literally cannot construct a response that claims it's not degraded when it was served from fallback — the type system prevents the inconsistency."

### Decision 5: Consecutive Failures (not Windowed)

- **The choice**: Circuit breaker counts consecutive failures, trips at threshold
- **The alternatives**: Time-windowed counting (N failures in M seconds)
- **The reasoning**: Consecutive is simpler and equivalent for blocking calls — if you get 5 failures in 60 seconds, they're also 5 consecutive failures (each call blocks). Windowed adds a sliding window data structure with marginal benefit
- **The trade-off**: If calls are non-blocking with high concurrency, a burst of 4 failures followed by 1 success resets the counter. In a windowed approach, 4/5 failures in 10 seconds would trip
- **When to revisit**: When running high-concurrency (>100 concurrent LLM calls) where failure interleaving is common
- **Interview version**: "We use consecutive failure counting instead of time-windowed because our LLM calls are blocking — if you get 5 failures in 60 seconds, they're also 5 consecutive failures. Windowed counting adds a sliding window data structure for a distinction that doesn't exist in practice."

## Patterns & Principles Used

### 1. State Machine (CircuitBreaker)
- **What**: Finite state machine with 3 states (CLOSED/OPEN/HALF_OPEN) and defined transitions
- **Where**: `circuit_breaker.py` — `_on_success()` and `_on_failure()` handle all transitions
- **Why it fits**: Circuit breaker behavior is naturally modeled as states with transition rules. The state determines which operations are allowed (CLOSED = all calls pass, OPEN = all calls rejected, HALF_OPEN = probes allowed)
- **When you wouldn't**: For binary on/off behavior. The HALF_OPEN state is what makes the circuit breaker recoverable — without it, you'd need manual intervention

### 2. Chain of Responsibility (ProviderChain)
- **What**: Request passes through a chain of handlers; first handler that succeeds terminates the chain
- **Where**: `provider_chain.py:158-209` — the for loop over `self._providers`
- **Why it fits**: Provider fallback is literally "try this, if it fails, try the next one." The chain is ordered by preference (primary first)
- **When you wouldn't**: When handlers should ALL process the request (pipeline pattern), not compete

### 3. Composition (ResilientLLM)
- **What**: Complex behavior assembled from independent components rather than inherited from a base class
- **Where**: `resilient_llm.py:128-137` — constructor takes router + chains, neither knows about the other
- **Why it fits**: Router and chain are orthogonal concerns. Router decides "which tier." Chain decides "which provider." They compose, not inherit
- **When you wouldn't**: When components share significant state or implementation. But router and chain share zero state

### 4. Strategy Pattern (RetryPolicy)
- **What**: Algorithm encapsulated in an object, swappable at runtime
- **Where**: `retry.py` — RetryPolicy wraps any async callable with configurable backoff strategy
- **Why it fits**: Different providers might need different retry strategies (aggressive for flaky providers, conservative for rate-limited ones). Strategy pattern makes this a config change, not a code change
- **When you wouldn't**: When there's only one retry strategy. But we already have "jitter" and "no jitter" as variants

### 5. Dependency Injection via Callback (Cache Lookup)
- **What**: Pass behavior as a function parameter instead of depending on a concrete class
- **Where**: `provider_chain.py:126-129` — `cache_lookup: CacheLookupFn | None`
- **Why it fits**: Decouples the chain from any specific cache implementation. Tests use `AsyncMock`. Production uses the RBAC-partitioned SemanticCache. The chain doesn't know or care
- **When you wouldn't**: When you need the cache to expose multiple methods (get, set, invalidate). Then you'd inject an interface, not a callback

### 6. Structural Subtyping / Protocol (LLMProvider)
- **What**: Duck typing with type safety. Any class with the right methods satisfies the Protocol
- **Where**: `provider.py` (Phase 6) — `LLMProvider` Protocol. All providers implement `generate`, `generate_structured`, `model_name`
- **Why it fits**: Adding a new provider doesn't require inheriting from a base class. Just implement the methods
- **When you wouldn't**: When you need shared implementation (template method pattern). Protocols are for shared interface

### 7. Deterministic Test Doubles
- **What**: Using controlled mocks/fakes instead of real services to test behavior predictably
- **Where**: Every test file — `_make_provider()`, `_make_failing_provider()`, `AsyncMock` for cache
- **Why it fits**: Testing circuit breaker transitions requires precise control over which calls succeed and fail. Real Azure/Ollama would be non-deterministic
- **When you wouldn't**: Integration tests (Phase 12) should test with real providers

## Benchmark Results & What They Mean

### Cost Model Sensitivity

**What was tested**: Is the 83.5% cost savings headline defensible across different query distributions?

| Distribution (simple/medium/complex) | Savings | What It Means |
|---|---|---|
| 100/0/0 | ~97% | Ceiling. All simple = maximum savings |
| 70/20/10 (baseline) | ~83% | Our assumed distribution. EUR 351/month |
| 50/30/20 (balanced) | ~68% | Still strong even with more medium queries |
| 30/30/40 (complex-heavy) | ~45% | EUR 190/month. Still funds engineering |
| 10/20/70 (mostly complex) | ~20% | Marginal. Routing complexity may not be justified |
| 0/0/100 | <1% | Routing adds classifier cost with zero benefit |

**Boundary found**: Crossover at ~90% complex. Below that, routing saves money. Above that, it's overhead.

**Monotonicity proven**: Savings decrease strictly as complex% increases across 11 distribution points. No anomalous crossover. The cost model is internally consistent.

### Jitter Distribution

**What was tested**: Does full jitter actually prevent thundering herd?

**Key numbers**: 100 draws at the same attempt level produce >20 unique delay values. All delays are bounded within [0, `calculated_delay`].

**What it means**: When 50 clients retry simultaneously after a provider recovery, their retries are spread across the entire backoff window instead of hitting at the same millisecond.

### Quality Gate Unicode Bypass

**What was tested**: Can a malfunctioning (or adversarial) provider bypass the quality gate with invisible characters?

**Key finding**: Python's `str.strip()` does NOT strip U+200B, U+FEFF, U+200C, U+200D, U+00AD, or U+2060. A response of 100 zero-width spaces passes `len()` as 100 characters but contains zero visible content. The gate explicitly removes these 6 characters before checking length.

**Boundary**: Real content containing embedded zero-width spaces passes correctly — the gate strips invisible chars but the remaining real content exceeds `min_length`.

### Degraded Mode Governance

**What was tested**: When the system is running on fallback/cache, does downstream logic respect the `is_degraded` flag?

**Key finding**: The governance contract works — `is_degraded=True` blocks auto-approve, `cache_used=True` blocks financial decisions, recovery clears the flag. The actual integration with Phase 3's HITL gateway is deferred (Phase 8/12).

## Test Strategy

### Organization

- **Unit tests** (168): All 10 test files. Fast (~6s total). No external dependencies. All use mocks
- **Integration tests** (0): Deferred to Phase 12. Requires Azure + Ollama running simultaneously
- **Red team tests** (24): 7 attack categories. Prove what the system REFUSES to do

### What the Tests Prove

**Circuit breaker tests (44)**: State transitions are correct. CLOSED -> OPEN at threshold. OPEN -> HALF_OPEN after timeout. HALF_OPEN -> CLOSED after success threshold. HALF_OPEN -> OPEN on any failure. Excluded exceptions never trip. Concurrent calls during HALF_OPEN don't crash. Metrics track accurately across multiple trip cycles.

**Retry tests (21)**: Exponential backoff follows `base * 2^attempt`. Max delay caps growth. Jitter produces varied delays. Non-retriable errors stop immediately. Retries actually sleep (mocked verification). Retry count is a hard limit.

**Provider chain tests (18)**: Primary serves when healthy. Fallback serves when primary fails. Three-provider cascade works. Cache serves when all providers down. Cache miss raises AllProvidersDownError. Retry integrates with chain (retry before fallback). Structured generation falls back correctly.

**Quality gate tests (11)**: Empty, too-short, whitespace-only all fail. Valid content passes. Configurable min_length. Gate failure counts as provider failure in circuit breaker.

**Degraded mode tests (11)**: Primary response = not degraded. Fallback = degraded. Cache = degraded. Logs warnings on fallback. Governance functions block auto-approve during degradation. Flag propagates end-to-end. Recovery clears flag.

**Red team tests (24)**: Excluded exceptions can't trip breaker. Rapid open/close cycles tracked. 50 concurrent requests during HALF_OPEN don't crash. Jitter produces >20 unique values. Cache always carries disclaimer. Whitespace/newline padding caught. 6 Unicode invisible chars caught. Real content with embedded ZWSP passes. Non-retriable errors stop immediately. Max retries is hard limit. Circuit breaker stops retries from hitting dead provider.

### What ISN'T Tested

- **Real provider integration**: No tests hitting actual Azure/Ollama. All mocked. Deferred to Phase 12
- **Failover latency measurement**: <100ms is architectural reasoning, not empirical. Phase 12 should instrument
- **End-to-end governance**: `is_degraded` flag works, but Phase 3's HITL gateway doesn't check it yet. Phase 8/12
- **Additional Unicode categories**: Only 6 chars covered. RTL override (U+202E), Hangul filler (U+3164) not tested. Phase 10
- **Load testing**: 50 concurrent = functional correctness. Not sustained throughput testing. Phase 10/12

## File Map

| File | Purpose | Key Patterns | ~Lines |
|------|---------|-------------|--------|
| `apps/api/src/core/infrastructure/llm/circuit_breaker.py` | Generic circuit breaker state machine | State Machine, Error Classification | 195 |
| `apps/api/src/core/infrastructure/llm/retry.py` | Exponential backoff with full jitter | Strategy, Configurable Wrapper | 106 |
| `apps/api/src/core/infrastructure/llm/provider_chain.py` | Ordered fallback chain with quality gate | Chain of Responsibility, Callback DI | 265 |
| `apps/api/src/core/infrastructure/llm/resilient_llm.py` | ModelRouter + ProviderChain orchestrator | Composition/Facade, Factory | 193 |
| `apps/api/src/core/rag/reranker.py` | Refactored CircuitBreakerReranker | Delegation (to generic CB) | 323 |
| `apps/api/src/core/config/settings.py` | 7 new resilience fields | Config-Driven | 52 |
| `apps/api/src/core/api/v1/analytics.py` | /resilience endpoint | DI via Factory Function | 147 |
| `scripts/simulate_outage.py` | 3-phase outage simulation | Script | ~80 |
| `scripts/benchmark_routing.py` | Cost model routed vs unrouted | Script | ~60 |
| `tests/unit/test_circuit_breaker.py` | 44 state machine tests | Deterministic Test Doubles | ~620 |
| `tests/unit/test_retry.py` | 21 backoff/jitter tests | Mocked Sleep Verification | ~280 |
| `tests/unit/test_provider_chain.py` | 18 fallback/cache tests | Mock Providers | ~460 |
| `tests/unit/test_quality_gate.py` | 11 response validation tests | Boundary Testing | ~230 |
| `tests/unit/test_degraded_mode.py` | 11 governance tests | Contract Testing | ~370 |
| `tests/unit/test_resilient_llm.py` | 9 orchestrator tests | Mock Router | ~225 |
| `tests/unit/test_resilience_settings.py` | 11 config/factory tests | Mocked Providers | ~160 |
| `tests/unit/test_resilience_analytics.py` | 4 endpoint tests | ASGI TestClient | ~165 |
| `tests/unit/test_outage_simulation.py` | 15 simulation + cost model tests | Parameterized Cost Model | ~335 |
| `tests/unit/test_resilience_redteam.py` | 24 red team tests | Attack Simulation | ~615 |

## Interview Talking Points

1. **Circuit breaker extraction**: "We had a circuit breaker embedded in the reranker since Phase 2. Phase 7 extracted it into a generic component that works for any async callable — LLM providers, embedding services, database clients. Saved 60 lines of duplication and now every new external service gets circuit breaking by plugging into the same class."

2. **Per-provider retry**: "We chose per-provider retry over cascade-level because cascade keeps re-discovering the same dying provider. Per-provider exhausts each provider's budget independently, then moves on. Recovery is handled by the circuit breaker's HALF_OPEN probe, not retry. The trade-off: if a provider recovers mid-retry, we don't notice until the next probe cycle (60s)."

3. **200-OK-garbage detection**: "The most expensive silent failure in LLM APIs isn't a 500 error — it's a 200 OK with empty content. Your monitoring shows all green, your users see nothing. We built a quality gate that strips whitespace AND 6 Unicode invisible characters (Python's strip() doesn't handle zero-width spaces), then checks length. This converts invisible failures into visible ones that trip the circuit breaker."

4. **Cost model sensitivity**: "The 83.5% savings headline holds at 70/20/10 query distribution. A CTO will ask 'what about my distribution?' — so we stress-tested across 6 distributions and found the crossover: routing stops being worth it when >90% of queries are complex. Below that, even small percentages of simple queries justify routing because GPT-5 nano is 35x cheaper than GPT-5.2."

5. **Degraded mode governance**: "The system doesn't pretend fallback quality equals primary quality. Every response carries an `is_degraded` flag that downstream systems check. During an outage, invoice auto-approve switches to human review regardless of the discrepancy amount. The flag is a computed property — you literally can't construct a response that hides its degraded status."

6. **Composition architecture**: "Router decides 'which tier.' Chain decides 'which provider.' Neither knows the other exists. Adding a new LLM provider is ~50 lines: implement the Protocol (3 methods), add to the factory. The circuit breaker, retry, quality gate, and router don't change. This is what makes the 'swap Azure for Anthropic' claim credible."

7. **Unicode invisible char vulnerability**: "Python's str.strip() doesn't strip U+200B (zero-width space) or U+FEFF (byte order mark). A malfunctioning provider returning 100 zero-width spaces looks like a 100-character response to naive length validation. We found this during code review, not production. The fix is explicit: strip 6 specific invisible chars before checking length."

## What I'd Explain Differently Next Time

**The circuit breaker extraction should have happened in Phase 2.** Phase 2's reranker already had an inline state machine that proved the pattern worked. I just didn't generalize it. In a real project, build the generic CircuitBreaker alongside the first external service integration, not after the fourth. Werner Vogels' "everything fails all the time" principle should be Phase 1 thinking.

**The quality gate is embarrassingly simple — and that's the point.** I initially overdesigned it with ideas about semantic validation and JSON structure checking. But the failure mode it targets (empty/invisible content during partial degradation) is not adversarial. It's a provider returning nothing. Length check after invisible char stripping catches that at zero latency cost. Content quality validation is the agent's job, not the infrastructure layer's.

**Retry-within-provider vs retry-at-cascade is the decision that matters most.** I spent time on circuit breaker thresholds and jitter algorithms, but the architectural decision that prevents the most real-world pain is where retry lives. Getting this wrong means your system keeps bouncing back to a dying provider every cascade cycle. The per-provider approach makes retry exhaustion local and recovery global (via the breaker probe).

**The `is_degraded` flag is a CONTRACT, not a feature.** The flag itself is 2 lines of code. What matters is that every downstream consumer checks it. The tests prove the contract pattern, but the actual Phase 3 HITL integration is deferred. In hindsight, I'd wire at least one real downstream check (the auto-approve path) in the same phase to prove the integration, not just the contract.
