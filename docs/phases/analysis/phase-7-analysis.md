---
phase: 7
phase_name: "Resilience Engineering -- Circuit Breakers, Model Routing & Fallback Chains"
date: "2026-03-08"
agents: [business-critical, cascade-analysis, cto-framework, safety-adversarial]
---

# Phase 7 Deep Analysis: Resilience Engineering

## Top 5 Architect Insights

1. **The ModelRouter already exists in `core/infrastructure/llm/router.py` with keyword override + LLM classification -- Phase 7's "model routing" is not a new build, it is an INTEGRATION problem.** The Phase 7 spec proposes a new `model_router.py` in the same directory. But the existing `ModelRouter` class already classifies queries into SIMPLE/MEDIUM/COMPLEX, maps them to gpt-5-nano/mini/5.2, has 10 financial keyword overrides, and handles confidence escalation. Phase 7 does not need a new router -- it needs to connect the existing router to the new `ProviderChain` so that the complexity tier selects both the model AND the provider fallback order. Building a second router would create conflicting routing logic and a maintenance nightmare. The architect decision: extend, do not duplicate.

2. **The circuit breaker pattern already exists in `core/rag/reranker.py` (Phase 2) -- Phase 7 must generalize it, not rebuild it.** The `CircuitBreakerReranker` has CLOSED/OPEN/HALF_OPEN states, failure threshold, recovery timeout, and automatic fallback. It wraps a `BaseReranker` primary/fallback pair. Phase 7's LLM circuit breaker needs identical state machine logic but wrapping `LLMProvider` instead of `BaseReranker`. The architect move: extract a generic `CircuitBreaker[T]` that both rerankers and LLM providers can use. This eliminates ~120 lines of duplicated state machine code and proves the "core/ is domain-agnostic" principle. If Phase 2's breaker has 3-failure threshold and Phase 7 spec says 5, document WHY the thresholds differ (reranker failures are cheaper to retry than LLM failures, so LLM breaker tolerates more before tripping).

3. **The SemanticCache in `core/infrastructure/llm/cache.py` is RBAC-partitioned -- using it as a "last resort fallback" creates an RBAC-correct degraded mode by default.** Most cache-as-fallback designs accidentally serve cross-user data during outages. LogiCore's cache is partitioned by `cl:{clearance}|dept:{depts}|ent:{entities}`. When the ProviderChain falls through to cache, it MUST pass the requesting user's RBAC context -- and the cache enforces isolation structurally. This is a genuine architectural advantage: the fallback path inherits security from the cache layer, not from the fallback logic. The content angle: "Our fallback is RBAC-safe by construction, not by hope."

4. **The spec's cost savings math (EUR 11.72/day, 84% reduction) assumes GPT-5-nano exists and costs EUR 0.0004/query -- but the current codebase only supports gpt-5-mini and gpt-5.2 via Azure, and qwen3:8b via Ollama.** The `AzureOpenAIProvider` takes a single `deployment` parameter. To route different complexity tiers to different models, Phase 7 needs MULTIPLE Azure providers (one per deployment) or a single provider that switches deployments. The current factory (`get_llm_provider`) returns ONE provider instance. This is a structural gap: the ProviderChain needs a provider-per-tier-per-priority matrix, not a single provider. Estimated rework: modify `get_llm_provider` to return a `Dict[str, LLMProvider]` keyed by deployment name, or build the ProviderChain to manage its own provider pool.

5. **The 200-OK-but-garbage-content failure mode is the most expensive bug Phase 7 can ship -- EUR 500-5,000 per incident, and the circuit breaker will not catch it.** Circuit breakers count 5xx errors and timeouts. But Azure OpenAI can return 200 with malformed JSON, empty content, or hallucinated garbage. The circuit breaker sees "success" and stays CLOSED while users get nonsense. The defense: a response quality gate between the provider and the consumer. If `LLMResponse.content` is empty, under 10 characters for a generation request, or fails JSON parsing for a structured request, count it as a failure for circuit breaker purposes. This is the difference between a circuit breaker that protects against infrastructure failures and one that protects against QUALITY failures.

## Gaps to Address Before Implementation

| Gap | Category | Impact | Effort to Fix |
|---|---|---|---|
| Existing ModelRouter vs spec's new model_router.py -- conflicting designs | Architecture | Two routers = conflicting routing logic, doubled maintenance, confusion for downstream phases | Medium (1 day): integrate spec's ProviderChain with existing ModelRouter rather than building a parallel router |
| Existing CircuitBreakerReranker vs new CircuitBreaker -- duplicated state machine | Architecture | ~120 lines of duplicated logic, divergent bug fixes over time, violates DRY | Medium (1 day): extract generic CircuitBreaker[T], refactor reranker to use it |
| Single-provider factory vs multi-provider-per-tier requirement | Architecture | Cannot route SIMPLE to nano and COMPLEX to 5.2 with current factory returning single provider | High (2 days): build provider pool or modify factory to return tier-mapped providers |
| No response quality gate for 200-OK-garbage | Safety | EUR 500-5,000 per incident, circuit breaker blind to content quality failures | Medium (1 day): add content validation between provider and circuit breaker |
| Cache fallback needs RBAC context threading | Security | Fallback without RBAC context = cross-user data leak during outage | Medium (1 day): ensure ProviderChain passes UserContext through to cache.get() |
| Spec says failure_threshold=5 but existing reranker uses 3 -- no documented rationale for difference | Documentation | Inconsistent thresholds across system, unclear which is correct | Low (30 min): document threshold rationale per component |
| No degraded-mode quality tracking in Langfuse | Observability | Cannot measure accuracy degradation during Ollama fallback periods post-incident | Medium (1 day): add `degraded_mode: bool` flag to TraceRecord, tag Langfuse traces |
| Retry jitter implementation not specified -- stdlib random vs cryptographic | Implementation | Predictable jitter = coordinated retries = thundering herd not actually prevented | Low (30 min): use `random.uniform()` with full-jitter algorithm per AWS architecture blog |
| Settings.py has no circuit breaker or routing config fields | Config | All thresholds hardcoded, cannot tune per deployment without code changes | Low (1 hour): add CB_FAILURE_THRESHOLD, CB_RESET_TIMEOUT, ROUTING_CONFIDENCE_THRESHOLD to Settings |

## Content Gold

- **"Our AI Survived a 4-Hour Azure Outage. Nobody Noticed."** -- The LogiCore scenario where circuit breaker detects 5 failures in 60 seconds, routes to local Ollama, and when Azure recovers, gradually shifts traffic back. The technical story is the 3-state machine. The business story is EUR 180,000 in pharmaceutical cargo that would have been lost without failover. The architect angle: the circuit breaker adds 55ms overhead. Not having one costs EUR 180,000 per incident. That is a 3,272,727x ROI on the overhead.

- **"We Already Had a Circuit Breaker. We Just Didn't Know It."** -- The story of extracting a generic CircuitBreaker from Phase 2's reranker-specific implementation. How the same pattern that protects re-ranking (fallback from Cohere to local BGE-m3) now protects LLM inference (fallback from Azure to Ollama). The architect lesson: resilience patterns are reusable; resilience implementations usually are not -- until you refactor them to be.

- **"The 200 OK That Cost EUR 5,000"** -- Azure returns HTTP 200 with garbage content. The circuit breaker sees "success." Users get nonsense for hours. The fix: response quality gates that treat semantically-empty 200s as failures. The broader lesson for any team building LLM failover: HTTP status codes are necessary but not sufficient for health checking.

- **"84% Cost Reduction, 0% Quality Loss on 70% of Queries"** -- The model routing story. Status checks and tracking lookups go to GPT-5-nano at EUR 0.0004. Legal analysis goes to GPT-5.2 at EUR 0.014. The router misclassification risk: 1% of complex queries sent to nano costs EUR 5,832/year. The defense: keyword override list that forces financial queries to COMPLEX regardless of LLM classification.

## Recommended Phase Doc Updates

1. **Replace the `model_router.py` in Files to Create/Modify with "Modify existing `core/infrastructure/llm/router.py`."** The ModelRouter already exists with keyword override, LLM classification, confidence escalation, and a `DEFAULT_MODEL_MAP`. Phase 7 should extend it to integrate with the ProviderChain, not duplicate it.

2. **Add a "Generic CircuitBreaker Extraction" task.** Extract the state machine from `core/rag/reranker.py`'s `CircuitBreakerReranker` into a standalone `CircuitBreaker[T]` class in `core/infrastructure/llm/circuit_breaker.py`. Refactor `CircuitBreakerReranker` to use the generic breaker. This proves the pattern is domain-agnostic.

3. **Add a "Response Quality Gate" section to the Technical Spec.** Define what counts as a "failure" beyond HTTP errors: empty content, content under 10 chars, JSON parse failure for structured requests, content containing only whitespace or error messages. These quality failures must increment the circuit breaker's failure counter.

4. **Update the provider factory discussion.** The current `get_llm_provider(settings)` returns a single provider. Phase 7 needs multiple providers (one per tier, one per priority level). Document the ProviderChain's provider management strategy: does it call the factory multiple times? Does it maintain a pool? How does it map tier + priority to a specific provider instance?

5. **Add "Degraded Mode Governance" to the Implementation Guide.** When circuit breaker is OPEN: (a) set `degraded_mode=True` on all TraceRecords, (b) disable auto-approve on financial decisions (Phase 3 HITL), (c) add disclaimer to all responses, (d) alert operations via log + future webhook. This is already in the spec's "Cost of Getting It Wrong" section but needs to be in the implementation tasks.

6. **Add Settings fields for Phase 7.** `cb_failure_threshold: int = 5`, `cb_reset_timeout_seconds: int = 60`, `cb_half_open_success_threshold: int = 3`, `routing_confidence_threshold: float = 0.7` (already exists in router.py but not in Settings), `fallback_cache_similarity_threshold: float = 0.90`.

## Red Team Tests to Write

1. **test_circuit_breaker_transitions_closed_to_open** -- Inject 5 consecutive failures (mock provider raises `httpx.HTTPStatusError(503)`). Verify: state transitions from CLOSED to OPEN after exactly the 5th failure (not 4th, not 6th). Verify the 6th call does NOT reach the primary provider. Verify the fallback provider handles the 6th call. This proves the threshold is exact and the state machine is correct.

2. **test_circuit_breaker_half_open_probe** -- After OPEN state and 60s timeout, verify exactly ONE probe request goes to the primary. If probe succeeds, verify 3 more consecutive successes required before CLOSED. If any of the 3 fail, verify immediate return to OPEN. This tests the graduated recovery strategy from the spec (not just "one success = closed").

3. **test_200_ok_garbage_counts_as_failure** -- Mock Azure to return HTTP 200 with empty content string. Verify the response quality gate counts this as a failure for circuit breaker purposes. After 5 such "successful" garbage responses, verify the breaker trips to OPEN. This catches the EUR 500-5,000 per incident silent failure mode.

4. **test_provider_chain_rbac_preserved_in_cache_fallback** -- All providers down. ProviderChain falls through to semantic cache. Verify: (a) cache.get() receives the correct clearance_level, departments, and entity_keys from the requesting user, (b) a clearance-1 user cannot receive a cached response from a clearance-3 partition, (c) the response includes the disclaimer "Served from cache -- live providers unavailable." This proves the fallback path does not bypass RBAC.

5. **test_model_routing_financial_override_with_provider_chain** -- Send "What's the contract rate for PharmaCorp?" through the routing + provider chain pipeline. Verify: (a) ModelRouter classifies as COMPLEX due to "contract" and "rate" keywords, (b) ProviderChain selects GPT-5.2 (not nano), (c) if GPT-5.2 provider's breaker is OPEN, it falls to Ollama (not to nano). This ensures the router's financial safety override is respected through the entire fallback chain.

6. **test_retry_jitter_prevents_thundering_herd** -- Simulate 100 concurrent requests hitting a rate-limited provider (429). Collect retry timestamps. Verify: (a) no two retries occur within 10ms of each other (jitter working), (b) retry delays increase exponentially (base * 2^attempt), (c) total retry time does not exceed 30s timeout. This proves jitter actually decorrelates retries.

7. **test_degraded_mode_disables_auto_approve** -- Trigger circuit breaker to OPEN (Azure down, traffic on Ollama). Send an audit workflow that would normally auto-approve. Verify: (a) the workflow forces HITL review regardless of discrepancy amount, (b) the response includes "Served by local model -- verify critical decisions" disclaimer, (c) Langfuse trace (or mock) includes `degraded_mode: true` tag. This prevents Phase 3 auto-approve from running at degraded quality.

8. **test_concurrent_circuit_breaker_state_safety** -- Send 50 concurrent requests through a breaker in HALF_OPEN state. Verify: (a) exactly ONE probe reaches the primary (not 50), (b) remaining 49 go to fallback, (c) no race condition causes the breaker to get stuck in an invalid state. This catches the concurrency bug that would let the thundering herd through during recovery.

9. **test_all_providers_down_returns_cached_with_disclaimer** -- Azure OPEN, Ollama OPEN, cache has a 0.92 similarity match. Verify: (a) the cached response is returned, (b) the response includes "Served from cache" disclaimer with the cached timestamp, (c) no `AllProvidersDownError` is raised. Then: no cache match (similarity < 0.90). Verify: `AllProvidersDownError` IS raised. This tests the complete fallback chain terminus.

10. **test_stale_cache_during_outage_includes_warning** -- Cache entry is 30 minutes old. All live providers are down. Verify: (a) the stale cached response is returned (better than nothing), (b) the response includes the cache timestamp so the user knows the data age, (c) if cache entry is > 24 hours old (TTL expired), it is NOT returned and `AllProvidersDownError` is raised. This prevents dispatchers from acting on day-old fleet status data.

---

<details>
<summary>Business-Critical AI Angles (full report)</summary>

## Business-Critical Angles for Phase 7

### High-Impact Findings (top 3, ranked by EUR cost of failure)

1. **EUR 180,000 -- Undetected temperature spike during Azure outage.** Without circuit breaker + fallback, a 4-hour Azure outage means zero AI processing for fleet monitoring. Truck-4721 carrying EUR 180,000 in pharmaceutical cargo for PharmaCorp hits a temperature spike at 3 AM. No anomaly detection, no alert, no diversion to cold storage. The cargo spoils. Insurance denies the claim because there is no proof of monitoring during the outage window. With Phase 7: circuit breaker trips after 5 failures (max 60s exposure), routes to Ollama. Temperature alert is processed with 2s latency instead of 500ms. The cargo is saved.

2. **EUR 58,320-777,600/year -- Router misclassification of complex financial queries.** The model router saves 84% on LLM costs (EUR 11.72/day at 1,000 queries). But a misclassified complex query -- "What's the PharmaCorp rate?" routed to GPT-5-nano instead of GPT-5.2 -- returns only the base rate without cross-referencing the Q4 amendment and volume discount. At 5-10% misclassification rate on 10-20 complex queries/month, cost is EUR 486-3,240 per misrouted query. Annual exposure: EUR 58,320-777,600. Defense: the existing ModelRouter's 10-keyword override list forces "contract," "rate," "invoice," "penalty" etc. to COMPLEX regardless of LLM classification. This override is free (no LLM call), deterministic, and proven by 27 unit tests.

3. **EUR 500-5,000/incident -- 200 OK with garbage content (silent provider degradation).** Azure OpenAI returns HTTP 200 with malformed JSON or empty content. The circuit breaker counts it as a success. Users see nonsense responses for hours until a human notices. At 1-2 incidents/year, annual cost: EUR 1,000-10,000 plus trust erosion. Defense: response quality gate that validates `LLMResponse.content` length, format, and basic coherence before counting as a breaker success.

### Technology Choice Justifications

| Choice | Alternatives Considered | Why This One | Why NOT the Others |
|---|---|---|---|
| Per-provider circuit breaker (independent state per Azure/Ollama) | Global circuit breaker (single state for all providers) | Azure going down should not disable Ollama. Independent breakers allow partial system function. | Global breaker would disable all providers when one fails -- defeats the purpose of having a fallback. |
| Exponential backoff with full jitter | Fixed delay retry, linear backoff, exponential without jitter | Full jitter (random between 0 and base * 2^attempt) decorrelates concurrent retries, preventing thundering herd on recovery. AWS architecture recommendation. | Fixed delay: all retries at same time = thundering herd. Linear: too slow to back off. Exponential without jitter: all clients still synchronized. |
| Keyword override list for financial routing (10 terms) | LLM-only classification, regex complexity detection, no override | Free (zero LLM calls), deterministic, 100% recall on financial queries. Every "contract" or "invoice" query goes to COMPLEX. | LLM-only: 5-10% misclassification = EUR 58K-778K/year. Regex: brittle, language-dependent. No override: unacceptable risk. |
| Semantic cache as last-resort fallback | Error page, static response, queue for later processing | Cache returns RBAC-partitioned, contextually relevant previous answer with disclaimer. Better than "AI is down." | Error page: zero value to user. Static response: misleading. Queue: user gets no immediate answer. |
| 3-consecutive-success threshold for HALF_OPEN to CLOSED | Single probe success = CLOSED, 5-success threshold | 1 success could be a fluke (Azure recovered for one request but is still degrading). 3 consecutive successes = sustained recovery. 5 is too cautious (keeps traffic on fallback unnecessarily). | 1-success: premature return risks immediate re-tripping. 5-success: delays recovery by 4 extra probe cycles (~240s minimum). |

### Metrics That Matter to a CTO

| Technical Metric | Business Translation | Who Cares |
|---|---|---|
| Circuit breaker trip time: <60s from first failure to OPEN | "AI switches to backup in under a minute. Users experience at most 5 degraded responses before failover." | Operations -- no 3 AM pages for Azure blips |
| Cost per query: EUR 0.0004 (nano) vs EUR 0.014 (5.2) = 35x difference | "70% of our queries cost 35x less with routing. That's EUR 351/month saved on a 1,000 query/day workload." | CFO -- direct line-item savings |
| Fallback latency: 500ms (Azure) vs 2,000ms (Ollama) vs <10ms (cache) | "Worst case, queries are 4x slower during outage. Best case (cache hit), they are 50x faster." | Product -- user experience during degraded mode |
| Router misclassification rate target: <1% on financial queries | "Every 1% misclassification on financial queries costs EUR 5,832/year. Keyword override makes misclassification structurally impossible for financial terms." | CFO + Legal -- accuracy on money decisions |
| Cache fallback similarity threshold: 0.90 | "Only cached answers with 90%+ semantic match are served. Below that, we show an error rather than risk a misleading cached answer." | Product + Legal -- answer quality floor |

### Silent Failure Risks

1. **Quality degradation during failover is invisible without degraded-mode tracking.** Ollama (qwen3:8b) may have lower accuracy than GPT-5.2 on complex reasoning. If the breaker routes to Ollama for 4 hours, all complex queries during that window have degraded quality -- but no metric captures this. Phase 5's DriftDetector checks model versions periodically, not per-request. The fix: tag every TraceRecord with `provider_used` and `degraded_mode` flags, and run Phase 5 eval on degraded-mode responses retroactively. Blast radius: 4 hours * ~40 complex queries/hour = 160 potentially degraded financial decisions.

2. **Cache staleness during extended outage.** The cache TTL is 24 hours. During a 4-hour outage, cached responses from 20 hours ago are still served. For fleet status queries, a 20-hour-old answer is dangerously stale (truck has moved, temperature has changed, cargo has been delivered). For contract rate queries, a 20-hour-old answer is probably fine. The fix: different TTLs per query category (fleet: 15 min, contracts: 24h). Blast radius: dispatchers acting on stale fleet data = EUR 200-5,000 per incident (misdirected driver, wrong warehouse).

3. **Retry storm if jitter is implemented with insufficient randomness.** If all 100 concurrent requests use `random.uniform(0, base * 2^attempt)` but the random seed is process-global and deterministic, retries may cluster. In Python, `random` module uses Mersenne Twister with adequate entropy for this purpose, but in containerized environments with identical startup, seeds could collide. Blast radius: thundering herd on recovery = provider rate-limited again = cycle repeats. Fix: seed from `os.urandom()` (Python default) -- verify in test.

4. **Circuit breaker state is in-memory -- lost on process restart.** If the API server restarts while the breaker is OPEN, it resets to CLOSED and immediately hammers the still-broken provider with requests until it trips again (5 failures = 5 failed user requests). Fix for Phase 7: accept this limitation with documentation. Fix for production: persist breaker state in Redis with TTL. Blast radius: 5 users experience failures on every server restart during an outage.

### Missing Angles (things the phase doc should address but doesn't)

1. **Multi-deployment Azure support.** The spec assumes three Azure model tiers (nano, mini, 5.2) but `AzureOpenAIProvider` takes a single deployment. How does the ProviderChain instantiate three Azure providers? The factory needs modification.

2. **Health check endpoint for circuit breaker state.** Operations needs a `/health/providers` endpoint showing each provider's breaker state (CLOSED/OPEN/HALF_OPEN), failure count, and last failure time. Without this, ops cannot distinguish "Azure is down and we're on fallback" from "everything is normal."

3. **Graceful traffic shift on HALF_OPEN recovery.** The spec mentions "gradual traffic shift back" after Azure recovers, but the implementation shows binary states (OPEN -> HALF_OPEN -> CLOSED). There is no canary percentage (e.g., route 10% to Azure, then 25%, then 50%, then 100%). This is an acceptable simplification for Phase 7 but should be documented as a future enhancement.

4. **Interaction with Phase 4's CostTracker.** When a query is routed to Ollama (local, EUR 0.00/query) instead of Azure (EUR 0.014/query), the CostTracker must reflect the actual provider used, not the intended provider. Otherwise cost reports undercount savings during fallback periods.

</details>

<details>
<summary>Cross-Phase Failure Cascades (full report)</summary>

## Cross-Phase Cascade Analysis for Phase 7

### Dependency Map

```
Phase 1 (RAG + RBAC) ──────────────────────────────────┐
Phase 2 (Retrieval + Reranker CircuitBreaker) ──────────┤
Phase 3 (Multi-Agent + HITL) ──────────────────────────┤
Phase 4 (Trust Layer: Router, Cache, Cost, Langfuse) ───┼──► Phase 7 (Resilience)
Phase 5 (Eval Rigor: Drift Detection) ─────────────────┤        │
Phase 6 (Air-Gapped: LLMProvider Protocol, Factory) ───┘        │
                                                                 │
                         ┌───────────────────────────────────────┘
                         ▼
Phase 8 (Regulatory Shield) ── needs: audit of routing decisions, provider used
Phase 9 (Fleet Guardian) ── needs: real-time failover for streaming anomaly detection
Phase 10 (LLM Firewall) ── needs: security on fallback path, guardrail model availability
Phase 12 (Full Stack Demo) ── needs: circuit breaker demo (Azure 429 → Ollama)
```

### Cascade Scenarios (ranked by total EUR impact)

| Trigger | Path | End Impact | EUR Cost | Mitigation |
|---|---|---|---|---|
| Azure outage + Ollama overloaded | Phase 7 breaker OPEN on both → cache fallback only → Phase 9 fleet monitoring has no LLM for anomaly response | Temperature spike on pharma truck unprocessed for duration of dual outage | EUR 180,000 per incident | Priority-1 fleet queries bypass cache threshold (serve any cached answer with disclaimer); dedicated Ollama instance for fleet |
| Router misclassifies complex as simple | Phase 7 routes to nano → Phase 3 reader agent gets incomplete contract rate → Phase 3 auditor compares wrong rate → Phase 3 HITL sees incorrect discrepancy | Wrong dispute filed with vendor, or real discrepancy missed | EUR 486-3,240 per query | Keyword override (already in Phase 4 router) forces financial queries to COMPLEX; Phase 7 must preserve this override in ProviderChain |
| Circuit breaker state lost on restart during outage | Phase 7 breaker resets to CLOSED → 5 requests fail → breaker trips again → 5 users get errors | 5 failed requests per restart event; if Phase 9 is running, 5 fleet alerts delayed by ~60s | EUR 50-500 (5 delayed alerts, wasted user time) | Accept for Phase 7; persist state in Redis for production |
| Degraded Ollama quality + Phase 3 auto-approve still active | Phase 7 routes to Ollama (88% accuracy) → Phase 3 auto-approves a financial decision based on degraded quality | Financial decision made on degraded AI output without human review | EUR 136-588 per auto-approved audit | Degraded mode governance: disable auto-approve when primary breaker is OPEN |
| Phase 5 drift detector does not distinguish providers | Phase 7 routes some queries to Ollama during partial outage → Phase 5 drift check includes Ollama responses in Azure baseline → baseline shifts → false alerts | Alert fatigue from spurious drift alerts, or worse, baseline contamination masks real drift | EUR 0 direct, but corrupts quality metrics for weeks | Tag every trace with `provider_used`; Phase 5 filters drift detection by provider |
| Cache fallback serves stale fleet status | Phase 7 cache fallback returns 30-min-old fleet position → Phase 9 dispatcher acts on stale data → driver sent to wrong location | Wasted fuel, delayed delivery, potential cargo risk | EUR 200-5,000 per incident | Category-specific cache TTL: fleet queries = 15 min, contract queries = 24h |
| Retry storm overwhelms recovered Azure | Phase 7 retries with insufficient jitter → 100 concurrent retries hit Azure simultaneously on recovery → Azure rate-limits again → breaker re-trips | Extended outage duration; cascade to all downstream phases depending on LLM | EUR varies by outage duration | Full jitter: `random.uniform(0, base * 2^attempt)` decorrelates retries |

### Security Boundary Gaps

1. **Cache fallback must preserve RBAC partitioning.** The SemanticCache in `core/infrastructure/llm/cache.py` uses `_partition_key(clearance_level, departments, entity_keys)`. The ProviderChain's cache fallback must thread the requesting user's RBAC context through to `cache.get()`. If the ProviderChain calls `cache.get()` without RBAC context (e.g., using a default partition), it could serve cross-clearance cached responses during an outage. **Current risk: MEDIUM.** The cache is structurally safe (returns None if no partition match), but the ProviderChain integration must be tested explicitly.

2. **Ollama fallback bypasses Azure-level API key scoping.** Azure OpenAI deployments can be scoped by API key (different keys for different tenants). Ollama has no API key authentication. When traffic fails over to Ollama, any tenant-level API key isolation on Azure is lost. For LogiCore's current single-tenant deployment, this is irrelevant. For multi-tenant: Ollama would need per-tenant model instances or a proxy layer. **Current risk: LOW (single-tenant).**

3. **Degraded mode responses still go through Phase 1 RBAC (Qdrant filter).** RBAC is enforced at the Qdrant query level, independent of the LLM provider (Phase 6 proved this with 3 RBAC independence tests). This means the security model is preserved during failover -- the LLM provider change does not affect retrieval authorization. **No gap here -- this is a strength to highlight.**

4. **Circuit breaker error messages could leak provider configuration.** `CircuitOpenError(self.provider_name)` in the spec includes the provider name. If this error propagates to the API response, it reveals infrastructure details (e.g., "Azure OpenAI provider circuit is OPEN"). The error should be sanitized before reaching the client: "Service temporarily using backup provider" rather than naming Azure/Ollama. **Current risk: LOW but easy to fix.**

### Degraded Mode Governance

| Dependency State | This Phase Behavior | Recommended Action |
|---|---|---|
| Azure OPEN, Ollama CLOSED | All traffic on Ollama. Latency 500ms -> 2,000ms. Quality may degrade on complex queries. | Log `degraded_mode=true`. Add disclaimer to responses. Disable Phase 3 auto-approve. Alert operations. |
| Azure OPEN, Ollama OPEN | Cache-only mode. Only queries with >= 0.90 similarity cached match get answers. | Log `full_outage=true`. Return cached responses with disclaimer and timestamp. For uncached queries, return AllProvidersDownError with estimated recovery time. |
| Azure CLOSED, Ollama CLOSED | Normal operation. Azure serves all tiers. Ollama is idle standby. | No action. |
| Azure rate-limited (429) | Retry with exponential backoff + jitter. If rate limit persists past 3 retries, count as failure for breaker. | Log rate limit events. If frequency increases, alert operations about approaching quota. Suggest quota increase or traffic redistribution. |
| Phase 2 reranker OPEN (Cohere down) | Independent of Phase 7. Reranker has its own CircuitBreakerReranker fallback to local BGE-m3. | No Phase 7 action needed. Demonstrates independent resilience layers. |
| Phase 4 Langfuse down | Non-blocking (Phase 4 design). Traces go to in-memory fallback store. Phase 7 routing decisions still logged locally. | Reconciliation backfills Langfuse after recovery. Phase 7 traces not lost. |
| Phase 4 SemanticCache (Redis) down | Cache fallback in ProviderChain cannot serve cached responses. Last resort is AllProvidersDownError if Azure + Ollama both down. | Log cache unavailability. If Azure/Ollama healthy, no user impact (cache is optimization, not requirement). |

</details>

<details>
<summary>CTO Decision Framework (full report)</summary>

## CTO Decision Framework for Phase 7

### Executive Summary (3 sentences max)

Phase 7 adds production-grade resilience to an AI system that currently has a single point of failure on Azure OpenAI. The circuit breaker + fallback chain transforms a "4-hour outage = 4-hour downtime" scenario into "4-hour outage = 4x slower responses on local model." Model routing reduces LLM costs by 84% (EUR 351/month at 1,000 queries/day) with ROI on day one -- the classifier itself costs EUR 0.01/day.

### Build vs Buy Analysis

| Component | Build Cost | SaaS Alternative | SaaS Cost | Recommendation |
|---|---|---|---|---|
| Circuit breaker for LLM | 3-5 dev-days | AWS Bedrock cross-region failover; Azure OpenAI multi-region | EUR 0/month (built into platform) but locks you to one cloud | **Build.** AWS/Azure failover only works within their ecosystem. LogiCore needs Azure-to-Ollama failover (cross-provider), which no SaaS offers. The generic CircuitBreaker also protects re-ranking (Phase 2) -- SaaS can't do that. |
| Model routing by complexity | 2-3 dev-days (extending existing router) | OpenRouter (model routing SaaS), Martian (auto-routing) | OpenRouter: ~EUR 50-100/month overhead on API costs; Martian: custom pricing | **Build.** Existing ModelRouter is 185 lines with keyword override, LLM classification, and confidence escalation. OpenRouter adds latency (extra hop) and cost (margin on API calls). More critically, it cannot enforce the financial keyword override that prevents EUR 58K/year misclassification. Custom routing logic is a competitive advantage, not a commodity. |
| Retry with jitter | 1 dev-day | tenacity library (Python) | EUR 0 (open source) | **Use tenacity as implementation base.** The library is battle-tested, supports exponential backoff + jitter out of the box. Writing retry logic from scratch invites edge-case bugs. 14.5K GitHub stars, actively maintained. |
| Fallback to cached responses | 1 dev-day (integration with existing SemanticCache) | N/A -- no SaaS provides RBAC-partitioned semantic cache fallback | N/A | **Build.** The RBAC-partitioned cache from Phase 4 is already built. Phase 7 just adds a "last resort" code path that calls `cache.get()` when all providers are down. 20-30 lines of integration code. |
| Provider health dashboard | 2-3 dev-days | Datadog LLM Observability, Helicone | Datadog: EUR 15-25/host/month; Helicone: EUR 0-50/month | **Defer to Phase 12.** A basic `/health/providers` JSON endpoint (1 dev-day) covers Phase 7 needs. Full dashboard with historical state transitions is a Phase 12 capstone feature. |

### Scale Ceiling

| Component | Current Limit | First Bottleneck | Migration Path |
|---|---|---|---|
| Circuit breaker (in-memory) | Single process; state lost on restart | Multi-process deployment: each process has independent breaker state, leading to inconsistent failover behavior | Persist breaker state in Redis. TTL = reset_timeout. All processes share state. Cost: ~10 lines of Redis get/set. |
| Model router (LLM-based classification) | ~100 classifications/second (limited by GPT-5-nano latency) | At 10,000 queries/minute, classification becomes a bottleneck (100ms per call = 1,667 qps max) | Distill classifier to a local model (TinyBERT fine-tuned on classification examples). Eliminates API dependency and reduces latency to ~5ms. |
| SemanticCache (in-memory) | ~10,000 entries (configurable `max_entries`), single-process | Memory consumption: 10K entries * ~2KB per entry = ~20MB. At 100K entries, 200MB. | Redis Stack with RediSearch for vector similarity. Already documented as the production path in cache.py comments. |
| ProviderChain (concurrent requests) | Limited by asyncio event loop + provider rate limits | Azure rate limits: 240K tokens/minute on S0 tier. At 1,000 queries/hour with 500 tokens average, that is 500K tokens/hour = well within limits. | Azure provisioned throughput (PTU) for guaranteed capacity. Ollama: horizontal scaling with multiple instances behind a load balancer. |
| Fallback latency (Ollama on single GPU) | ~2s per response on dev hardware (Apple Silicon) | At 50 concurrent requests during failover, queue depth grows. 50 * 2s = 100s queue for last request. | vLLM with continuous batching on production GPU. Or multiple Ollama instances with round-robin. |

### Team Requirements

| Component | Skill Level | Bus Factor | Documentation Quality |
|---|---|---|---|
| CircuitBreaker state machine | Mid-level Python dev (async, state management) | 2 -- pattern is well-known, code is ~100 lines | High -- the state machine is textbook, extensively documented in the codebase |
| ModelRouter extension | Mid-level Python + understanding of LLM pricing | 2 -- existing router has 27 unit tests serving as documentation | High -- keyword list is self-documenting, pricing table in docstring |
| ProviderChain (fallback orchestration) | Senior Python dev (async error handling, timeout management) | 1 -- integration logic between breaker, router, cache, providers is the complex part | Medium -- needs clear architecture diagram showing the integration points |
| Retry with jitter (tenacity) | Junior Python dev (library configuration) | 3+ -- tenacity is standard, well-documented | High -- library docs + examples in codebase |
| Degraded mode governance | Architect-level (cross-phase implications) | 1 -- requires understanding of Phase 3 HITL, Phase 5 drift, Phase 9 fleet | Low -- this is the gap. Phase 7 must document degraded mode rules explicitly. |

### Compliance Gaps

1. **EU AI Act Article 14 (Human Oversight) during degraded mode.** When the system falls back to Ollama (potentially lower accuracy), the auto-approve mechanism in Phase 3 should be disabled. The EU AI Act requires "appropriate human oversight measures" for high-risk AI. Auto-approving financial decisions on a degraded model may not meet Article 14 requirements. **Recommendation: degraded mode = mandatory HITL on all financial decisions.**

2. **Audit trail for routing decisions.** Phase 8 (Regulatory Shield) will need to reconstruct why a specific model was used for a specific decision. Phase 7 must log: which model was selected, why (routing decision), whether it was the primary or fallback, the breaker state at decision time. This must be in the immutable audit log, not just Langfuse. **Recommendation: include `ModelRoute` + `provider_used` + `breaker_state` in every audit entry.**

3. **GDPR implications of cache fallback.** Cached responses may contain personal data. Serving a cached response to a different user (even within the same RBAC partition) could violate data minimization principles. The RBAC partitioning mitigates this (same clearance + department + entity), but if a cached response contains User A's specific query results and User B asks a similar question, User B sees User A's answer. **Risk: LOW.** The cache stores LLM-generated answers, not raw personal data. The source documents are RBAC-filtered before LLM generation.

### ROI Model

| Item | Month 1 | Month 3 | Month 6 | Month 12 |
|---|---|---|---|---|
| **Implementation cost** | EUR 4,000-6,000 (2-3 dev-weeks at EUR 500/day) | -- | -- | -- |
| **Monthly LLM cost without routing** | EUR 420 (1,000 queries/day * EUR 0.014/query * 30 days) | EUR 420 | EUR 420 | EUR 420 |
| **Monthly LLM cost with routing** | EUR 68 (70% nano + 20% mini + 10% 5.2) | EUR 68 | EUR 68 | EUR 68 |
| **Monthly savings from routing** | EUR 352 | EUR 352 | EUR 352 | EUR 352 |
| **Avoided outage cost (amortized)** | EUR 0-15,000 (EUR 180K/incident * 1 incident/year / 12) | EUR 15,000 | EUR 15,000 | EUR 15,000 |
| **Cumulative ROI** | EUR -3,648 to -5,648 (implementation cost) | EUR +6,408 to +4,408 | EUR +20,964 to +18,964 | EUR +50,076 to +48,076 |
| **Break-even** | Month 1 if outage avoided; Month 2 from routing savings alone | -- | -- | -- |

**The CTO line**: "Phase 7 pays for itself in routing savings by month 2. If it prevents even ONE outage-related cargo loss, the ROI is 30x the implementation cost."

</details>

<details>
<summary>Safety & Adversarial Analysis (full report)</summary>

## Safety & Adversarial Analysis for Phase 7

### Attack Surface Map

```
User Query
  │
  ├──[A1]──► Model Router (query complexity classifier)
  │              │  Attack: craft query to force misclassification
  │              │  Defense: keyword override + escalation on low confidence
  │              ▼
  ├──[A2]──► ProviderChain
  │              ├── Primary (Azure) ──[A3]──► Circuit Breaker
  │              │     │  Attack: force breaker OPEN to degrade service
  │              │     │  Attack: force breaker CLOSED on broken provider
  │              │     ▼
  │              ├── Fallback (Ollama) ──[A4]──► Local model
  │              │     │  Attack: exhaust local GPU to slow all users
  │              │     ▼
  │              └── Last Resort ──[A5]──► Semantic Cache
  │                    │  Attack: poison cache, serve misleading data
  │                    │  Defense: RBAC partition + similarity threshold
  │                    ▼
  ├──[A6]──► Retry Logic
  │              │  Attack: trigger retry storm to amplify DoS
  │              ▼
  └──[A7]──► Response (with provider metadata)
                 │  Attack: use metadata to fingerprint infrastructure
```

### Critical Vulnerabilities (ranked by impact x exploitability)

| # | Attack | Vector | Impact | Exploitability | Mitigation |
|---|---|---|---|---|---|
| 1 | **Forced misclassification to bypass quality** | Craft a complex financial query without trigger keywords (e.g., "How much should we pay for the last shipment?" avoids "contract," "invoice," "rate") | HIGH: Complex query routed to nano, wrong financial answer, EUR 486-3,240 per query | MEDIUM: Requires knowledge of keyword list, but natural phrasing may accidentally bypass | Expand keyword list to 20+ terms including "pay," "cost," "charge," "bill," "shipment fee." Add Phase 3 domain-specific keywords. Monitor misclassification rate in production. |
| 2 | **Cache poisoning via crafted queries during normal operation** | Attacker sends queries with carefully chosen wording during normal operation. The LLM response is cached. During outage, other users with same RBAC partition get the poisoned cached response. | HIGH: Misleading cached responses served during outage when users cannot verify | LOW: Requires same RBAC partition as target user + similarity threshold 0.90 match + outage timing | Mark responses with low quality scores as non-cacheable. Add `cacheable: bool` flag (already exists in cache.put). Phase 5 eval scores can gate caching. |
| 3 | **Deliberate circuit breaker manipulation** | Internal attacker (or compromised API client) sends requests designed to trigger 5xx from Azure (e.g., malformed prompts that cause Azure to error). After 5 such requests, breaker opens and all users go to fallback. | MEDIUM: All traffic forced to Ollama (slower, potentially lower quality) | MEDIUM: Requires valid API access. 5 malformed requests in 60s is detectable. | Rate-limit per-user error rates. If one user causes >3 errors in 60s, exclude that user's errors from breaker failure count. |
| 4 | **GPU exhaustion on Ollama fallback** | During Azure outage (all traffic on Ollama), attacker sends many long-context queries to exhaust GPU memory. Ollama OOM-kills or becomes extremely slow for all users. | MEDIUM: Ollama becomes unresponsive, entire system falls to cache-only | MEDIUM: Requires valid API access during outage window. Long-context queries are normal usage. | Set Ollama `--max-loaded-models 1` and context length limits in Ollama config. Add request timeout (30s) in ProviderChain. Queue management: reject requests when Ollama queue > 50. |
| 5 | **Provider metadata leaks infrastructure details** | Response includes `provider: "azure/gpt-5.2"` or `provider: "ollama/qwen3:8b"`. Attacker learns: (a) which providers are available, (b) when Azure is down, (c) what local model is used. | LOW: Information disclosure, aids further attacks (e.g., craft prompts that exploit qwen3:8b weaknesses) | HIGH: Every response includes metadata per spec | Sanitize provider metadata for external API responses: show "primary" or "fallback" instead of specific provider/model names. Keep detailed metadata for internal Langfuse traces only. |
| 6 | **Retry amplification DoS** | Attacker sends burst of 1,000 requests. All hit rate-limited Azure (429). All retry with backoff. Combined retry volume = 3,000+ requests. Azure rate-limits harder. Cycle continues. | MEDIUM: Amplified load on Azure, extended rate limiting, possible account suspension | LOW: Requires ability to send 1,000+ concurrent requests (rate limiting should prevent this) | Per-user rate limiting at API level (before retry logic). Global retry budget: max 100 outstanding retries across all users. Circuit breaker trips before retry budget is exhausted. |

### Red Team Test Cases (implementable as pytest)

**Test 1: Financial query bypass via natural phrasing**
```python
def test_router_natural_financial_phrasing_not_misclassified():
    """Queries about money that avoid keyword list should still route to COMPLEX."""
    queries = [
        "How much should we pay for the last shipment?",  # no "invoice" or "rate"
        "Is that charge correct for 500kg of cargo?",      # "charge" not in default list
        "What did we agree to pay per kilometer?",          # "pay" not in default list
        "Check if the billing is right for truck-0892",     # "billing" not in default list
    ]
    # Setup: router with default keywords
    # Action: classify each query
    # Expected: all COMPLEX (via LLM classification if keywords miss)
    # Gap found: if LLM classifies "How much should we pay" as SIMPLE, that's a EUR 486 error
```

**Test 2: Cache poisoning during normal operation**
```python
def test_cache_poisoning_low_quality_response_not_cached():
    """Responses with quality score below threshold must not be cached."""
    # Setup: ProviderChain with quality gate
    # Action: send query that produces a low-quality LLM response (mocked)
    # Expected: response returned to user but NOT stored in cache
    # Verify: cache.size() unchanged after low-quality response
```

**Test 3: Per-user error isolation from circuit breaker**
```python
def test_single_user_errors_dont_trip_breaker_for_all():
    """One user's malformed requests should not trip the global breaker."""
    # Setup: Circuit breaker with failure_threshold=5
    # Action: user_A sends 5 requests causing 5xx (malformed prompts)
    # Expected: breaker state depends on implementation
    # Ideal: per-user error tracking, user_A's errors don't affect user_B
    # Acceptable: breaker trips globally but user_A is rate-limited
```

**Test 4: Metadata sanitization for external responses**
```python
def test_external_response_hides_provider_details():
    """API response should say 'fallback' not 'ollama/qwen3:8b'."""
    # Setup: ProviderChain with Ollama as active provider
    # Action: query through API endpoint
    # Expected: response.metadata.provider == "fallback" (not "ollama/qwen3:8b")
    # Internal Langfuse trace should have full details
```

**Test 5: GPU exhaustion protection on Ollama**
```python
def test_ollama_timeout_prevents_gpu_exhaustion():
    """Ollama requests must timeout at 30s, not block indefinitely."""
    # Setup: Mock Ollama that takes 60s to respond
    # Action: send request through ProviderChain
    # Expected: TimeoutError after 30s, fallback to cache
    # Verify: no hanging coroutine left
```

### Defense-in-Depth Recommendations

| Layer | Current | Recommended | Priority |
|---|---|---|---|
| Request rate limiting | Phase 4: per-endpoint rate limits | Add per-user error rate tracking. If user causes >3 provider errors in 60s, rate-limit that user specifically. | HIGH -- prevents deliberate breaker manipulation |
| Response quality validation | None (HTTP status only) | Quality gate: content length >10 chars, valid JSON for structured requests, no error-string patterns | HIGH -- catches 200-OK-garbage failure mode |
| Provider metadata exposure | Spec says include provider name in response | Sanitize for external API: "primary"/"fallback"/"cache" labels. Full details only in Langfuse traces. | MEDIUM -- prevents infrastructure fingerprinting |
| Cache entry quality gate | Phase 4: `cacheable: bool` flag exists | Integrate with Phase 5 eval: responses below quality threshold are marked non-cacheable automatically | MEDIUM -- prevents cache poisoning with low-quality answers |
| Ollama resource limits | Docker compose memory limit (16G) | Add `--max-loaded-models 1`, context length limit, request timeout 30s, queue depth limit | MEDIUM -- prevents GPU exhaustion during failover |
| Circuit breaker state persistence | In-memory (lost on restart) | Redis-backed state with TTL for multi-process consistency | LOW for Phase 7, HIGH for production |

### Monitoring Gaps

1. **No alert for sustained degraded mode.** If the circuit breaker is OPEN for >30 minutes, operations should receive an escalated alert (PagerDuty, not just log). Currently, the spec only mentions logging. A 4-hour outage with only a log line means nobody is working on recovery.

2. **No tracking of misclassification rate.** The router classifies queries, but there is no feedback loop to measure if the classification was correct. Without this, the EUR 58K/year misclassification cost is invisible. Recommendation: sample 5% of routed queries for human review, track misclassification rate weekly.

3. **No monitoring of cache hit rate during outage vs normal.** If cache hit rate during outage is 10% (most queries are unique), then 90% of users during an outage get AllProvidersDownError. The cache fallback provides a false sense of resilience. Monitoring this number helps set expectations.

4. **No circuit breaker event history.** When the breaker trips, recovers, and re-trips, the timeline is only in logs. A structured `CircuitBreakerEvent` record (timestamp, state_from, state_to, trigger, failure_count) in PostgreSQL enables post-incident analysis and SLA reporting.

</details>
