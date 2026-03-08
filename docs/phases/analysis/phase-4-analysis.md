---
phase: 4
phase_name: "The Trust Layer -- LLMOps, Observability & Evaluation"
date: "2026-03-08"
agents: [business-critical, cascade-analysis, cto-framework, safety-adversarial]
---

# Phase 4 Deep Analysis: The Trust Layer -- LLMOps, Observability & Evaluation

## Top 5 Architect Insights

1. **The RBAC-aware cache is a EUR 250,000 security decision disguised as a performance optimization.** Without `clearance_level + department` in the cache key, semantic caching becomes a universal RBAC bypass. A clearance-1 user asking "PharmaCorp penalty rate?" at 0.96 similarity to a clearance-3 cached response gets the answer for EUR 0.00 -- and the company gets a EUR 25,000-250,000 GDPR/contract exposure. The cache similarity threshold is secondary to the RBAC-partitioning question. Build the partition FIRST, tune the threshold second.

2. **Model routing delivers 93% cost reduction (EUR 42/day to EUR 2.87/day), but the router misclassification rate is the most expensive hidden metric in the system.** At 2,400 queries/day, every 1% of complex queries misrouted to GPT-5 nano costs EUR 5,832/year in wrong financial answers. The router's nano classification call costs EUR 0.000025 -- negligible. But routing "What's the PharmaCorp rate?" to nano when it requires cross-referencing base rate + Q4 amendment + volume discount produces a partial answer that triggers wrong invoice calculations. The architect question is not "should we route?" (obviously yes) but "what's the acceptable misclassification rate given the EUR 486-3,240 cost per misrouted complex query?"

3. **Langfuse is a compliance dependency, not just an observability tool.** Phase 8's immutable audit log stores Langfuse trace IDs. If Langfuse is rebuilt or loses data, those trace IDs become dangling pointers -- and the company cannot reconstruct AI decisions for regulators. A 2-day Langfuse outage creates a compliance gap worth EUR 10,000-100,000 in regulatory exposure. The mitigation (fallback to inline audit logging during outage + reconciliation job after recovery) must be built IN Phase 4, not deferred to Phase 8.

4. **The 0.95 cosine similarity threshold for semantic caching is a EUR 40,000/year decision with a hidden failure mode: cross-client data leakage.** "PharmaCorp delivery penalty?" and "FreshFoods delivery penalty?" score 0.96 similarity -- different rates, different clauses, same cache hit. At 0.95, you save EUR 22/day (EUR 8,030/year) in LLM costs and risk EUR 3,240 per false match (estimated 2-3/month = EUR 77,760-116,640/year). At 0.97, savings drop to EUR 15/day (EUR 5,475/year) with near-zero false matches. The threshold must be tuned WITH entity-aware cache partitioning (client name, contract ID in the key), not just similarity score alone.

5. **LLM-as-Judge evaluation in CI is the system's immune system -- and it has a known autoimmune disorder.** Position bias inflates scores by ~4 points (Phase 5 quantifies this). If the CI gate threshold is 0.80 and real quality is 0.78 but the judge says 0.82, a degraded PR ships. Over 14 days until the next manual review: 800 queries/day x 14 days x EUR 0.50/wrong-answer = EUR 5,600 blast radius. Phase 4 must establish the baseline evaluation pipeline, but the spec should explicitly note that Phase 5's bias mitigation is required before trusting CI gates for production deployments.

## Gaps to Address Before Implementation

| Gap | Category | Impact | Effort to Fix |
|---|---|---|---|
| Cache key must include entity context (client name, contract ID), not just RBAC fields | Security / Correctness | EUR 77,760-116,640/year in cross-client data leakage at 0.95 threshold | Medium -- extend cache key schema before building |
| No Langfuse fallback strategy defined in implementation guide | Compliance / Availability | EUR 10,000-100,000 regulatory exposure during Langfuse outage | Medium -- add inline audit logging + reconciliation job |
| Cache invalidation on document re-ingestion has no implementation path | Correctness | EUR 500-3,240 per stale cache incident, 1-2/month | Medium -- event hook from ingestion pipeline to cache flush |
| Model router needs a keyword override list for financial/legal terms | Correctness | EUR 486-3,240 per misrouted complex query | Low -- static keyword list that forces GPT-5.2 tier |
| Evaluation dataset (50+ Q&A) must be built from Phase 1-3 ground truth, not generated | Quality | Inflated eval scores if test data is synthetic | High -- curate from existing 52-query benchmark + Phase 3 audit test cases |
| No rate limiting specified on analytics endpoints | Security | DoS via expensive aggregation queries | Low -- add rate limit to /analytics/costs and /analytics/quality |
| Redis vector search requires RediSearch module -- not in default Docker Redis image | Infrastructure | Build failure on first integration test | Low -- switch to redis/redis-stack image in docker-compose |
| No cache warming strategy defined | Performance | Cold-start after deployment = 0% hit rate until organic queries populate cache | Low -- script to pre-populate from historical Langfuse query logs |
| Spec doesn't address cache size limits or eviction policy | Operations | Unbounded cache growth consuming Redis memory | Low -- define max entries + LRU eviction + memory budget |
| LLM-as-Judge evaluation cost not budgeted for CI runs | Cost | 50 eval queries x EUR 0.011/eval (GPT-5.2 judge) = EUR 0.55/PR; at 10 PRs/day = EUR 5.50/day = EUR 2,007/year | Low -- document and accept, or use GPT-5 mini for non-gate evals |

## Content Gold

- **"The EUR 40,000 Cache Threshold Decision"** -- LinkedIn hook: "We spent a week tuning a single number: 0.95 vs 0.97 cosine similarity. That decision is worth EUR 40,000/year. Here's why." Deep dive into how cache similarity threshold interacts with RBAC partitioning, entity-specific answers, and the false-match cost model. CTO-readable because it quantifies the tradeoff.

- **"93% Cost Reduction Without Switching Models"** -- Medium deep dive: "We cut our AI API bill from EUR 42/day to EUR 2.87/day. Not by switching to a cheaper model. By routing the right query to the right model." Covers the model routing decision tree, the hidden cost of misclassification, and why the router itself runs on nano for EUR 0.000025/classification.

- **"Your Observability Tool Is a Compliance Dependency"** -- LinkedIn hook: "Your LLM tracing tool isn't optional infrastructure. It's a regulatory requirement. If Langfuse goes down, can you still prove what your AI decided?" Covers the Langfuse-as-compliance-dependency angle, fallback strategy, and the EUR 648:1 ratio (logging cost vs non-compliance fine).

- **"Why We Don't Cache Compliance Queries"** -- Short LinkedIn post about the `cacheable: false` flag for audit-adjacent queries. The insight: saving EUR 0.038 per cached audit response isn't worth breaking the "this answer was generated for this specific request" provenance chain. When EUR 0.038 savings creates EUR 100,000 compliance exposure, the answer is obvious.

- **"LLM-as-Judge Has a 4-Point Position Bias"** -- Medium teaser for Phase 5, planted in Phase 4's evaluation pipeline section. Hook: "Our quality dashboard said 0.92. The real number was 0.88. Here's how we found out." Sets up the Phase 5 content arc.

## Recommended Phase Doc Updates

### 1. Add Entity-Aware Cache Partitioning (to "CRITICAL: Cache Must Be RBAC-Aware" section)

The existing spec mandates `clearance_level + department` in the cache key. This is necessary but insufficient. Add:

```python
# STILL WRONG: RBAC-aware but not entity-aware
cache_key = hash(query_embedding + user.clearance_level + sorted(user.departments))

# RIGHT: RBAC-aware AND entity-aware
cache_key = hash(
    query_embedding
    + user.clearance_level
    + sorted(user.departments)
    + extracted_entities(query)  # client names, contract IDs, invoice numbers
)
```

Add a paragraph: "Entity extraction before cache lookup is mandatory for queries referencing specific clients, contracts, or invoices. 'PharmaCorp penalty rate?' and 'FreshFoods penalty rate?' must NEVER match each other regardless of cosine similarity. Extract entity names and include them in the cache key. Cost of entity extraction: ~EUR 0.0001 per query (GPT-5 nano NER call). Cost of cross-client data leakage: EUR 3,240+ per incident."

### 2. Add Langfuse Fallback Implementation (to Architecture section)

```python
# Langfuse fallback during outage
async def trace_llm_call(prompt, response, tokens, cost):
    try:
        langfuse.trace(...)  # normal path
    except (ConnectionError, TimeoutError):
        # Fallback: write full context to PostgreSQL audit_log directly
        await pg_pool.execute(
            "INSERT INTO llm_traces_fallback (prompt, response, tokens, cost, ...) VALUES ($1, $2, $3, $4, ...)",
            prompt, response, tokens, cost
        )
        metrics.increment("langfuse.fallback_writes")

# Reconciliation job (run after Langfuse recovery)
async def reconcile_langfuse():
    pending = await pg_pool.fetch("SELECT * FROM llm_traces_fallback WHERE reconciled = false")
    for trace in pending:
        langfuse.trace(...)
        await pg_pool.execute("UPDATE llm_traces_fallback SET reconciled = true WHERE id = $1", trace.id)
```

### 3. Add Cache Size Limits and Eviction (to Semantic Caching Strategy section)

Add: "Cache memory budget: 512MB default (configurable). At ~2KB per cached response (embedding + response text + metadata), this supports ~250,000 entries. Eviction policy: LRU with TTL (24h default). Monitor via `/analytics/cache` endpoint: current size, hit rate, eviction rate. Alert if eviction rate exceeds 10% of insertions -- indicates cache is undersized."

### 4. Add Router Keyword Override (to Decision Framework: Model Routing Rules)

Add to "When to Override the Router" section: "Financial/legal keyword override: any query containing contract, invoice, rate, penalty, amendment, surcharge, annex, audit, compliance, or discrepancy ALWAYS routes to GPT-5.2 minimum, regardless of router classification. These keywords indicate potential cross-reference complexity that nano/mini cannot handle. This adds ~0 latency (keyword check before LLM classification) and prevents the EUR 486-3,240/misrouted-query risk for financial queries."

### 5. Add Redis Stack Requirement (to Prerequisites)

Change "Redis running" to: "Redis Stack running (redis/redis-stack:latest Docker image) -- required for RediSearch vector similarity module. Standard Redis does not support `FT.SEARCH` with vector fields."

## Red Team Tests to Write

### 1. RBAC Cache Bypass Test
```python
def test_cache_does_not_leak_across_clearance_levels():
    """Clearance-3 user query cached; clearance-1 user with identical query must NOT get cached response."""
    # Setup: user with clearance=3 asks "What is PharmaCorp's penalty rate?"
    # Cache stores response with clearance=3 partition
    # Action: user with clearance=1 asks identical question
    # Expected: cache MISS (different partition), fresh LLM call with RBAC-filtered retrieval
    # Verify: response either has no data (clearance-1 can't see PharmaCorp docs) or is a new generation
```

### 2. Cross-Client Cache Leakage Test
```python
def test_cache_does_not_leak_across_clients():
    """'PharmaCorp penalty rate' cached; 'FreshFoods penalty rate' must NOT return PharmaCorp's answer."""
    # Setup: query "What is PharmaCorp's delivery penalty?" cached with response "15% penalty"
    # Action: query "What is FreshFoods's delivery penalty?" submitted
    # Expected: cache MISS despite high cosine similarity (different entity)
    # Verify: response contains FreshFoods rate (10%), not PharmaCorp rate (15%)
```

### 3. Stale Cache After Document Update Test
```python
def test_cache_invalidated_after_document_reingestion():
    """Cache entry from old document version must not be served after re-ingestion."""
    # Setup: query about contract CTR-2024-001 rate, cached response says "EUR 0.45/kg"
    # Action: re-ingest CTR-2024-001 with updated rate "EUR 0.52/kg"
    # Expected: next identical query returns fresh answer with EUR 0.52/kg
    # Verify: cache miss triggered by staleness check (doc updated_at > cache created_at)
```

### 4. Model Router Financial Query Override Test
```python
def test_router_forces_gpt52_for_financial_queries():
    """Queries containing financial keywords must route to GPT-5.2 regardless of apparent simplicity."""
    # Setup: configure router with keyword override list
    # Action: submit "What's the rate for CTR-2024-001?" (looks simple, is complex)
    # Expected: routed to GPT-5.2, not nano
    # Verify: Langfuse trace shows model=gpt-5.2, routing_reason="keyword_override:rate"
```

### 5. Langfuse Outage Fallback Test
```python
def test_langfuse_outage_falls_back_to_postgres():
    """When Langfuse is unreachable, traces must be written to PostgreSQL fallback table."""
    # Setup: mock Langfuse client to raise ConnectionError
    # Action: execute a RAG query
    # Expected: query succeeds (Langfuse failure is non-blocking)
    # Verify: llm_traces_fallback table has 1 row with full prompt/response/tokens/cost
```

### 6. Cache Poisoning via High-Volume Garbage Queries Test
```python
def test_cache_resistant_to_poisoning_attack():
    """Attacker submitting many garbage queries should not evict legitimate cache entries."""
    # Setup: populate cache with 100 legitimate high-value queries
    # Action: submit 10,000 garbage queries to fill cache
    # Expected: LRU eviction respects access frequency; frequently-hit legitimate entries survive
    # Verify: original 100 queries still have cache hits, garbage queries evicted first
    # Note: this tests the eviction policy, not just the cache functionality
```

### 7. Cost Tracking Accuracy Test
```python
def test_cost_tracking_matches_actual_token_usage():
    """Cost tracker must accurately compute EUR costs from token counts and model pricing."""
    # Setup: known token counts (input=2800, output=400) with GPT-5 mini pricing
    # Expected cost: (2800 * $0.25 / 1M) + (400 * $2.00 / 1M) = $0.0007 + $0.0008 = $0.0015
    # Verify: cost_tracker returns EUR 0.0015 (or EUR equivalent)
    # Edge case: verify cache hit records EUR 0.00 cost
    # Edge case: verify multi-agent workflow sums costs across all LLM calls
```

### 8. Analytics Endpoint Rate Limiting Test
```python
def test_analytics_endpoints_rate_limited():
    """Analytics endpoints with expensive aggregation must reject excessive requests."""
    # Action: send 100 rapid requests to /api/v1/analytics/costs?period=365d
    # Expected: first N succeed, subsequent return 429 with Retry-After header
    # Verify: server remains responsive for other endpoints during rate limiting
```

---

<details>
<summary>Business-Critical AI Angles (full report)</summary>

## Business-Critical Angles for Phase 4

### High-Impact Findings (top 3, ranked by EUR cost of failure)

1. **RBAC-bypassing cache serves confidential data to unauthorized users: EUR 25,000-250,000 per incident.** The spec correctly identifies this risk and mandates `clearance_level + department` in the cache key. However, the implementation guide's code example only shows cosine similarity search -- the RBAC partition is mentioned in the "CRITICAL" section but not wired into the `get_cached_response()` function signature. If an implementer follows the code example literally, they build a cache WITHOUT RBAC partitioning. The spec should merge the two: the function signature in the Technical Spec section must include `user.clearance_level` and `user.departments` as parameters, not just `query: str`.

2. **Cross-client cache leakage at 0.95 threshold: EUR 3,240 per false match, estimated 2-3/month = EUR 77,760-116,640/year.** "PharmaCorp delivery penalty" and "FreshFoods delivery penalty" differ only by client name -- embeddings treat them as near-identical. At 0.95 cosine threshold, these match. The cached PharmaCorp answer (15% penalty) is served for FreshFoods (10% penalty). Finance applies the wrong rate. This is not addressed in the spec. Mitigation: entity extraction + entity-aware cache partitioning.

3. **Langfuse data loss breaks Phase 8 audit trail: EUR 10,000-100,000 regulatory exposure.** Phase 8's audit log stores `langfuse_trace_id` as a foreign key to reconstructable AI decisions. If Langfuse's PostgreSQL backend loses data (disk failure, migration error, accidental truncation), those trace IDs become dangling pointers. A regulator asking "reconstruct this decision from 6 months ago" gets "trace not found." The spec mentions this risk in the "Langfuse Dependency as Compliance Risk" section but the mitigation (inline audit logging during outage + reconciliation) is not in the implementation guide's file list. It should be a file: `apps/api/src/telemetry/langfuse_fallback.py`.

### Technology Choice Justifications

| Choice | Alternatives Considered | Why This One | Why NOT the Others |
|---|---|---|---|
| Langfuse (self-hosted) | LangSmith (cloud), Arize Phoenix (self-hosted), Helicone (cloud), custom OTEL stack | EU data residency via self-hosting, built-in cost tracking per model, evaluation dataset support, LangGraph callback handler, Docker Compose deployment | LangSmith: cloud-only, US-hosted -- violates EU data residency for Polish logistics company. Arize Phoenix: self-hostable but weaker on cost tracking and evaluation features. Helicone: cloud proxy model, adds latency. Custom OTEL: 3-6 months to build what Langfuse provides out of the box. |
| Redis (vector similarity) for semantic cache | Qdrant (dedicated vector DB), PostgreSQL pgvector, in-memory LRU, Momento (managed cache) | Sub-millisecond reads, already in stack (Phase 0 Docker Compose), RediSearch module supports vector similarity natively, TTL/eviction built-in | Qdrant: overkill for cache (it's for the primary vector store -- using it for cache conflates concerns). pgvector: higher latency for cache use case (~5ms vs ~0.5ms). In-memory LRU: lost on restart, no vector similarity. Momento: managed service, not self-hostable. |
| GPT-5 nano for router classification | Keyword heuristics only, GPT-5 mini, local Llama 4 Scout | EUR 0.000025 per classification (negligible), high accuracy on simple/medium/complex trichotomy, <50ms latency | Keyword-only: misses nuanced queries (e.g., "summarize the PharmaCorp situation" is medium but has no keyword signal). GPT-5 mini: 10x more expensive (EUR 0.00025) for the same classification accuracy on simple trichotomy. Llama 4 Scout: ~200ms latency for classification adds unnecessary overhead when nano does it in <50ms. |
| LLM-as-Judge (GPT-5.2) for evaluation | RAGAS framework, human evaluation only, custom metrics, Braintrust, DeepEval | Direct control over evaluation criteria, no framework lock-in, supports custom Polish-language evaluation, integrates with Langfuse datasets | RAGAS: good framework but opinionated about metrics -- we need custom metrics for Polish logistics domain. Human-only: EUR 50/calibration cycle, doesn't scale to CI. Braintrust/DeepEval: SaaS dependency, data residency concerns. |
| Configurable similarity threshold (0.95 default) | Fixed threshold, learned threshold, per-query-type thresholds | Simple to tune, easy to A/B test, matches the "start conservative, relax with data" principle | Fixed: no adaptability. Learned: requires ground truth cache hit/miss labels we don't have yet. Per-query-type: correct long-term goal but premature before measuring baseline hit rates by category. |

### Metrics That Matter to a CTO

| Technical Metric | Business Translation | Who Cares |
|---|---|---|
| Cache hit rate: 35% target | "35% of queries answered for EUR 0.00 in 2ms instead of EUR 0.012 in 800ms" -- EUR 22/day savings at current volume, EUR 220/day at 10x scale | CFO (cost), Users (speed) |
| Cost per query by agent type: EUR 0.012 (search), EUR 0.038 (audit), EUR 0.045 (fleet) | "The CFO can now see AI as a line item: EUR 2.87/day total, broken down by use case. Compare against EUR 45/hour for manual invoice audit." | CFO (budget), CTO (ROI proof) |
| Model routing distribution: 50% nano, 35% mini, 15% GPT-5.2 | "85% of queries handled by models 100-250x cheaper than the top tier. Only 15% need the expensive model." | CFO (cost optimization), CTO (architecture validation) |
| Evaluation scores: context precision >0.80, faithfulness >0.80, relevancy >0.80 | "Quality is measured and gated in CI. No developer can ship a change that degrades AI accuracy below 0.80. That's an SLA, not a hope." | CTO (governance), Compliance (audit), QA (process) |
| Langfuse trace count vs audit log count | "Every AI decision is traceable. The audit-to-trace ratio should be 1:1. Any gap is a compliance risk." | Compliance officer, CTO (regulatory readiness) |
| p95 cache lookup latency: <5ms | "Cache responses served in under 5ms. That's indistinguishable from a static page. Users don't wait." | UX team, CTO (user satisfaction) |

### Silent Failure Risks

1. **Langfuse callback handler silently fails without blocking the request.** If the Langfuse host is unreachable, the callback handler raises an exception that is swallowed (by design -- you don't want tracing to block production queries). But this means traces stop appearing in Langfuse and nobody notices for hours/days. Blast radius: all decisions in that window are untraceable. Detection gap: until someone checks the dashboard manually. Mitigation: counter metric `langfuse.trace_failures` with alert threshold >10/minute.

2. **Cache similarity search returns stale results after embedding model change.** If the embedding model is upgraded (e.g., text-embedding-3-small to a newer version), cached embeddings computed with the old model have different vector spaces. Cosine similarity scores become meaningless -- a 0.95 match between old and new embeddings is random correlation. The spec mentions "flush entire cache on model change" but there's no automated trigger. If someone changes `EMBEDDING_MODEL` in `.env` and forgets to flush, cache serves garbage for every query. Detection gap: could persist indefinitely. Mitigation: store embedding model version in cache metadata; reject matches where model version differs.

3. **Cost tracker uses hardcoded model prices that silently become wrong.** Azure OpenAI pricing changes 2-4x/year. If the cost tracker has `GPT_5_MINI_INPUT_PRICE = 0.25` hardcoded and Azure drops prices, the dashboard over-reports costs. Worse: if prices increase and the tracker under-reports, the CFO's budget is wrong. Detection gap: until next manual price check. Mitigation: price lookup from Langfuse model pricing table (Langfuse supports custom model prices), not hardcoded constants.

4. **Evaluation score drift goes undetected between CI runs.** The CI gate checks quality on every PR, but production queries may drift between PRs. If no PR is pushed for 2 weeks, no evaluation runs. Meanwhile, Azure silently updates the model version and quality drops. Detection gap: until next PR triggers CI. Mitigation: scheduled evaluation runs (daily cron) independent of CI, feeding into Langfuse score history.

5. **Redis memory exhaustion crashes both cache AND other Redis consumers.** Redis is shared: semantic cache + agent memory (Phase 3) + potentially session state. If cache grows unbounded, Redis OOM-kills and everything using Redis fails. Detection gap: sudden failures across multiple services with no clear cause. Mitigation: separate Redis instances for cache vs. state, or strict `maxmemory` + `maxmemory-policy allkeys-lru` configuration.

### Missing Angles (things the phase doc should address but doesn't)

1. **No cache warming strategy.** After deployment, cache hit rate is 0% until organic queries populate it. If the target is 35% hit rate for cost projections, cold-start negates weeks of savings. Solution: pre-populate from Langfuse historical query logs.

2. **No entity-aware cache partitioning.** RBAC-aware is necessary but insufficient. Client names, contract IDs, and invoice numbers must be part of the cache key to prevent cross-entity leakage.

3. **No cache size limit or eviction policy.** Unbounded cache growth in Redis. At 2,400 queries/day with 65% unique (cache miss), that's 1,560 new entries/day x 2KB = ~3.1MB/day = ~1.1GB/year. Manageable, but should be explicitly bounded.

4. **No distinction between "cache-safe" and "cache-unsafe" query patterns.** The spec mentions `cacheable: bool` but doesn't define a classification system. Which queries are cacheable? Status lookups (volatile -- should NOT cache), contract interpretation (stable -- should cache), invoice audit (compliance-sensitive -- should NOT cache).

5. **No Redis high-availability consideration.** Single Redis instance is a SPOF for both caching and agent memory. If Redis dies, every query costs full LLM price and agent state is lost. Should mention Redis Sentinel or Redis Cluster for production.

</details>

<details>
<summary>Cross-Phase Failure Cascades (full report)</summary>

## Cross-Phase Cascade Analysis for Phase 4

### Dependency Map

```
Phase 1 (RAG + RBAC) ─────────────────────────────┐
  - RBAC model (clearance_level, departments)       |
  - Search pipeline (dense/hybrid)                  |
  - Document ingestion events                       |
                                                    v
Phase 2 (Retrieval Engineering) ──────────> PHASE 4: TRUST LAYER
  - Enhanced retrieval pipeline                     |  - Langfuse tracing
  - Embedding model (text-embedding-3-small)        |  - Semantic cache (Redis)
  - Query sanitizer                                 |  - LLM-as-Judge evaluation
  - Reranker (BGE-m3)                              |  - Cost tracking
                                                    |  - Model routing
Phase 3 (Multi-Agent) ─────────────────────────────|  - CI quality gates
  - Audit graph (LangGraph)                         |  - Analytics endpoints
  - HITL gateway                                    |
  - ClearanceFilter                                 |
  - Compliance subgraph                             |
                                                    v
                                    ┌───────────────┼───────────────┐
                                    v               v               v
                              Phase 5          Phase 7         Phase 8
                              (Eval Rigor)     (Resilience)    (Regulatory)
                              - Judge bias     - Circuit        - Audit log
                              - Drift detect     breaker       - Trace IDs
                              - Prompt cache   - Model router   - Compliance
                                               - Fallback       reports
                                                 chain
                                                    |
                                                    v
                                              Phase 12
                                              (Full Stack Demo)
```

### Cascade Scenarios (ranked by total EUR impact)

| Trigger | Path | End Impact | EUR Cost | Mitigation |
|---|---|---|---|---|
| Cache serves clearance-3 data to clearance-1 user | Phase 4 cache miss RBAC partition -> Phase 1 RBAC completely bypassed -> Phase 8 audit log shows "from cache" with no RBAC check logged | Full RBAC bypass. Confidential contract data leaked to unauthorized user. Audit trail shows cache hit but no RBAC verification. Compliance report cannot prove access was authorized. | EUR 25,000-250,000 (GDPR fine) + EUR 50,000-500,000 (Phase 8 compliance gap) | RBAC fields in cache key (mandatory). Cache hits must log the RBAC partition that was matched, not just "cache hit." |
| Langfuse outage during Phase 3 audit workflow | Phase 4 tracing fails silently -> Phase 3 audit graph completes but trace ID is null -> Phase 8 audit log entry has langfuse_trace_id = NULL | Audit decision exists in log but is unreconstructable. Regulator asks "show me the AI's reasoning for this EUR 588 dispute" and gets "trace unavailable." | EUR 100,000-3,500,000 (EU AI Act Article 12 violation; up to 7% of global turnover) | Phase 4 must implement fallback: full prompt/response/tokens written to PostgreSQL when Langfuse is unreachable. Phase 8 links to fallback record when trace ID is null. |
| Embedding model upgraded without cache flush | Phase 2 embedding model changed -> Phase 4 cache has old-model embeddings -> similarity scores between new queries and old cache are random -> cache serves wrong answers at high "confidence" | Every cached response is potentially wrong. At 35% hit rate, 35% of all queries return garbage for the duration of the mismatch. At 2,400 queries/day = 840 wrong answers/day. | EUR 420-2,520/day (840 wrong answers x EUR 0.50-3.00 per wrong answer depending on use case) | Store embedding model version in cache entry metadata. Reject cache hits where model version differs from current. Automated flush on model change detection. |
| Redis OOM crashes semantic cache and Phase 3 agent memory | Phase 4 unbounded cache growth -> Redis maxmemory exceeded -> Redis evicts Phase 3 agent state -> ongoing audit workflows lose intermediate state -> Phase 3 HITL gateway sees corrupted state | Active audit workflows crash mid-execution. CFO approvals in progress are lost. Agent must restart from last PostgreSQL checkpoint (if using PostgreSQL checkpointer) or from scratch (if using MemorySaver). | EUR 500-5,000 per interrupted workflow (manual re-audit) + EUR 200-1,000 per lost CFO approval cycle | Separate Redis instances (cache vs. state) OR strict maxmemory-policy. Phase 4 cache must have bounded memory with LRU eviction. Monitor Redis memory usage with alert at 80% capacity. |
| Model routing misclassifies complex financial query as "simple" | Phase 4 router sends to nano -> Phase 3 audit comparator receives partial answer -> auditor detects partial rate (base only, missing amendment) -> reports wrong discrepancy -> HITL shows incorrect amount to CFO | CFO approves dispute based on wrong amount. Vendor relationship damaged. Potential legal action if dispute is wrong. | EUR 486-3,240 per misrouted query. At 5% misclassification rate on 50 daily audit queries = 2.5 wrong audits/day = EUR 1,215-8,100/day. | Financial keyword override list in router. Any query from audit workflow always routes to GPT-5.2. Override at graph level: audit_graph forces tier="complex" for all LLM calls. |
| Stale cache served after contract amendment | Phase 1 re-ingests updated contract -> Phase 4 cache still holds old version's answer -> user asks about rate and gets old rate | Finance applies old rate to new invoices. Discrepancy is in the wrong direction -- or not flagged at all. | EUR 500-3,240 per incident, estimated 1-2/month | Cache invalidation hook: ingestion pipeline emits event on document update -> Phase 4 cache listener invalidates all entries referencing that document's chunks. |
| Evaluation dataset drifts from production reality | Phase 4 eval dataset has 50 Q&A pairs from Phase 1-2 era -> Phases 3-8 add new use cases not covered -> CI gate passes PRs that break audit/fleet queries because eval set doesn't test them | False confidence in quality. CI gate approves PRs that degrade Phase 3 audit accuracy or Phase 9 fleet queries because those categories aren't in the eval set. | EUR 2,000-10,000 per false-pass PR over 2-week detection window | Eval dataset must grow with each phase. Mandate: every new phase adds at least 10 Q&A pairs to the evaluation dataset covering its use cases. |

### Security Boundary Gaps

1. **Cache bypasses Phase 1's zero-trust RBAC model.** Phase 1 enforces RBAC at Qdrant query time -- the LLM never sees unauthorized docs. But cached responses were generated by a previous query that DID pass RBAC. If the cache key doesn't include RBAC context, a subsequent query from a lower-clearance user gets the cached (higher-clearance) response WITHOUT any Qdrant query -- the RBAC check never fires. This is a complete bypass of Phase 1's security model. The cache lookup must be RBAC-partitioned, and the Qdrant RBAC filter must still run on cache misses.

2. **Phase 3 ClearanceFilter doesn't protect cached sub-agent results.** Phase 3's compliance subgraph uses ClearanceFilter as the "last step before sub-agent data enters parent state." But if the parent agent's query hits the semantic cache, the ClearanceFilter never runs -- the cached response from a previous high-clearance sub-agent execution is served directly. The cache for multi-agent workflows must either (a) cache at the final-filtered output level, not at the sub-agent level, or (b) apply ClearanceFilter to cached responses before serving.

3. **Langfuse stores full prompts including RBAC-filtered context.** Phase 1 ensures the LLM only sees authorized docs. But Langfuse traces store the full prompt (including retrieved chunks) in its PostgreSQL database. If Langfuse access is not RBAC-protected, anyone with Langfuse dashboard access can read all chunks from all clearance levels by browsing traces. Langfuse must be access-controlled: either (a) self-hosted with restricted access, or (b) PII redaction in traces.

4. **Cost tracking reveals query patterns that leak business intelligence.** The `/analytics/costs` endpoint shows cost breakdown by agent type and query category. If this endpoint is not authenticated and authorized, a competitor could learn: "LogiCore runs 50 invoice audits/day" (business volume), "audit costs EUR 0.038/run" (technology capability), and "cache hit rate is 35%" (operational efficiency). Analytics endpoints need the same RBAC as data endpoints.

### Degraded Mode Governance

| Dependency State | This Phase Behavior | Recommended Action |
|---|---|---|
| Langfuse DOWN | Tracing silently fails. No traces recorded. Audit trail has null trace IDs. | Write full trace to PostgreSQL fallback table. Emit metric `langfuse.fallback_count`. Alert if >0 for >5 minutes. |
| Redis DOWN | Cache unavailable. All queries go to LLM (EUR 0.00 savings). Agent memory (Phase 3) also impacted. | Bypass cache gracefully (return None from cache lookup). Log cache bypass rate. Alert on 100% cache miss rate. Do NOT let cache failure block the query pipeline. |
| Embedding model API DOWN | Cannot compute query embedding for cache lookup. Cannot compute embedding for cache storage. | Skip cache entirely (both lookup and storage). Proceed with LLM call. This is a superset of "cache down." |
| Azure OpenAI DOWN | Model routing irrelevant (no cloud models). All queries must go local or fail. | Phase 7 handles this (circuit breaker + fallback chain). Phase 4's router should detect provider health and adjust routing rules (e.g., all queries route to "local" tier). |
| PostgreSQL DOWN | Cost tracking cannot persist. Eval scores cannot be stored. Langfuse fallback table unavailable. | This is catastrophic for the entire system (checkpointing, audit, everything). Phase 4 should buffer cost/eval data in memory and flush on reconnect. Alert immediately. |
| Eval dataset corrupted/deleted | CI quality gate cannot run. PRs proceed without quality check. | CI should FAIL CLOSED: if eval dataset is missing, block the PR. Never let a missing eval set mean "skip the check." |

</details>

<details>
<summary>CTO Decision Framework (full report)</summary>

## CTO Decision Framework for Phase 4

### Executive Summary

Phase 4 transforms the AI system from a "works on my machine" prototype into a managed enterprise service with cost tracking, quality SLAs, and automated guardrails. The 93% cost reduction from model routing (EUR 42/day to EUR 2.87/day) pays for the entire observability stack in week one. The harder sell: this phase creates a compliance dependency (Langfuse trace IDs in audit logs) that must be treated with the same rigor as the database itself.

### Build vs Buy Analysis

| Component | Build Cost | SaaS Alternative | SaaS Cost | Recommendation |
|---|---|---|---|---|
| LLM Observability (Langfuse) | 0.5 dev-weeks (integration) + EUR 0/mo (self-hosted Docker) | LangSmith (EUR 39-400/mo), Helicone (EUR 0-500/mo), Arize Phoenix (free self-hosted) | EUR 39-500/mo depending on query volume | **Self-host Langfuse.** EU data residency requirement eliminates all US-hosted options. Langfuse is free, self-hosted, and already in Docker Compose. No SaaS survives the "can you guarantee no data leaves EU?" question. |
| Semantic Cache | 1 dev-week (RBAC-aware cache with entity partitioning) | Momento Cache (managed), GPTCache (open-source library) | Momento: EUR 0.50/GB/hr. GPTCache: free. | **Build on Redis Stack.** Redis is already in the stack. Momento adds a managed dependency. GPTCache is the closest alternative but doesn't support RBAC-partitioned caching -- you'd build that layer anyway. The RBAC-aware partitioning is the hard part, not the cache itself. |
| Model Router | 1 dev-week (keyword overrides + nano classifier) | Martian (AI router SaaS), Portkey (routing proxy), custom heuristics only | Martian: EUR 0.001/routed call. Portkey: EUR 99-499/mo. | **Build.** The router is a 50-line classifier + keyword override list. The domain-specific keyword overrides (financial terms -> GPT-5.2) are the value; no SaaS provides logistics-specific routing rules. Martian/Portkey add latency and a dependency for a trivially simple component. |
| LLM-as-Judge Evaluation | 1.5 dev-weeks (eval pipeline + dataset + CI integration) | Braintrust (EUR 0-500/mo), DeepEval (open-source), Ragas (open-source) | Braintrust: EUR 0-500/mo. DeepEval/Ragas: free. | **Build with Ragas as reference, not dependency.** The eval metrics (context precision, faithfulness, relevancy) are standard. Ragas's implementation is a good reference but we need custom Polish-language evaluation and tight Langfuse integration. Building from scratch gives full control over the judge model, prompt, and scoring logic. Phase 5 extends this with bias mitigation -- framework lock-in would block that. |
| Cost Tracker | 0.5 dev-weeks (token counting + pricing + aggregation) | Langfuse built-in cost tracking, Helicone | EUR 0 (Langfuse built-in) | **Use Langfuse's built-in cost tracking as primary.** Langfuse already computes cost per trace if you configure model prices. Build a thin aggregation layer on top for the `/analytics/costs` endpoint. Don't reinvent token cost calculation. |
| Analytics Dashboard (Next.js) | 1 dev-week (cost chart, cache metrics, quality scores) | Grafana (free), Metabase (free), Langfuse built-in dashboard | EUR 0 (all free options) | **Use Langfuse dashboard for LLM-specific metrics. Build custom Next.js page only for CTO-facing summary (the "Monday morning" dashboard).** Langfuse's built-in dashboard already shows traces, costs, and scores. A lightweight Next.js page that pulls aggregates via Langfuse API is sufficient. Don't build a full analytics platform. |

**Total build estimate**: 4.5-5 dev-weeks. At EUR 100/hr senior engineer rate: EUR 18,000-20,000 one-time.

### Scale Ceiling

| Component | Current Limit | First Bottleneck | Migration Path |
|---|---|---|---|
| Langfuse (self-hosted, single Postgres) | ~50,000 traces/day (limited by PostgreSQL write throughput) | PostgreSQL disk I/O at 100K+ traces/day with full token logging | Langfuse supports external PostgreSQL -- migrate to managed PostgreSQL (Azure DB) or add read replicas. Alternatively: reduce trace verbosity (summary traces for low-risk queries). |
| Redis semantic cache (single instance) | ~1M cached entries at 2KB each = 2GB memory | Memory at 500K+ entries if embedding vectors are stored full-precision (768 dims x 4 bytes = 3KB per vector) | Quantize cached embeddings to int8 (768 bytes per vector). Or Redis Cluster for horizontal scaling. Or move to Qdrant dedicated cache collection. |
| Model router (GPT-5 nano classification) | ~100K classifications/day (rate limit dependent) | Azure OpenAI rate limits on nano tier (typically 100K+ TPM) | Add heuristic fast-path (keyword override) that bypasses LLM classification for 60-70% of queries. Reduces nano API calls by 60%. Already recommended. |
| Evaluation pipeline (CI) | ~500 eval queries per PR (limited by LLM judge latency) | PR build time at 500+ eval queries (~5 min with GPT-5.2 judge) | Run eval in parallel (batch API). Or evaluate a sample (50 of 500 queries) for fast CI, full suite nightly. |
| Cost aggregation (PostgreSQL) | ~10M rows per year (365 x 2,400 queries x ~10 trace events each) | PostgreSQL query performance on unpartitioned 10M+ row table for time-range aggregations | Table partitioning by month. Materialized views for common aggregation periods (daily, weekly). Archive partitions older than 1 year to cold storage. |

### Team Requirements

| Component | Skill Level | Bus Factor | Documentation Quality |
|---|---|---|---|
| Langfuse integration | Mid-level Python dev (1 week to learn Langfuse callback API) | Low risk -- Langfuse has good docs, standard callback pattern | Good -- Langfuse docs are comprehensive. Custom handler is ~100 lines. |
| RBAC-aware semantic cache | Senior Python dev (understands RBAC model from Phase 1, Redis vector search internals) | Medium risk -- RBAC partitioning logic is subtle, entity extraction adds complexity | Must document: cache key composition, partition strategy, invalidation triggers. This is the riskiest component for knowledge loss. |
| Model router | Mid-level dev (keyword list + LLM classification call) | Low risk -- simple logic, well-tested | Low complexity, self-documenting. |
| LLM-as-Judge pipeline | Senior ML engineer OR senior Python dev with evaluation experience | Medium risk -- evaluation methodology is nuanced (Phase 5 reveals why) | Must document: metric definitions, judge model selection rationale, threshold justification. |
| Cost tracker + analytics | Mid-level full-stack dev (Python aggregation + Next.js chart) | Low risk -- straightforward CRUD + visualization | Self-documenting API endpoints. |

**Bus factor summary**: The RBAC-aware cache is the riskiest component. If the developer who builds the cache key composition leaves, a replacement must understand (a) Phase 1's RBAC model, (b) Redis vector search, (c) entity extraction, and (d) cache invalidation triggers. Document heavily.

### Compliance Gaps

1. **Langfuse trace retention policy undefined.** EU AI Act Article 12 requires record-keeping for the lifetime of the AI system plus 10 years for high-risk decisions. Langfuse's default PostgreSQL storage has no retention policy. Without explicit configuration, traces could be accidentally deleted during maintenance. Define: minimum 10-year retention for audit-linked traces, 1-year retention for general traces, automated archival to cold storage.

2. **Cache hit responses are not individually auditable.** When a cached response is served, there's no individual LLM call to trace. The audit log should record: "response served from cache, original trace ID: {X}, cache entry created: {timestamp}, similarity score: {score}." Without this, a cached response has no provenance chain.

3. **Model routing decisions are not logged.** If the router sends a financial query to nano (misclassification), there's no record of WHY it was routed there. Log every routing decision: query, classification result, confidence score, override reason (if any), selected model. This becomes critical for Phase 8 compliance reports.

4. **Analytics endpoints expose operational intelligence.** `/api/v1/analytics/costs` and `/api/v1/analytics/quality` reveal: query volumes, cost per agent, cache hit rates, quality scores. These are competitively sensitive. Endpoints must require authentication and authorization (admin role minimum).

5. **GDPR right-to-delete vs. cache.** If a user exercises GDPR right to be forgotten, their cached queries and responses must be deletable. The cache must support user-specific deletion. Current spec has no mechanism for this.

### ROI Model

| Item | Month 1-3 (Build) | Month 4-12 (Operate) | Year 2+ (Scale) |
|---|---|---|---|
| **Engineering cost** | EUR 18,000-20,000 (4.5-5 dev-weeks) | EUR 0 (maintenance only) | EUR 0 |
| **Infrastructure cost** | EUR 0/mo (all self-hosted Docker) | EUR 0/mo | EUR 0/mo (until scale requires managed DB) |
| **LLM cost WITHOUT Phase 4** | EUR 1,260/mo (EUR 42/day x 30) | EUR 1,260/mo | EUR 12,600/mo at 10x scale |
| **LLM cost WITH Phase 4** | EUR 86/mo (EUR 2.87/day x 30, routed + cached) | EUR 56/mo (with 35% cache hits) | EUR 560/mo at 10x scale |
| **Monthly savings** | EUR 1,174/mo | EUR 1,204/mo | EUR 12,040/mo at 10x |
| **Break-even** | **Month 2** (EUR 18,000 / EUR 1,174/mo ~ 15 months at current scale, but savings start month 1) | Cumulative saving by month 12: ~EUR 13,000 | EUR 144,480/year at 10x scale |
| **Manual process replaced** | Invoice audit: EUR 6,750/mo manual vs EUR 46.50/mo automated (145x ROI on audit alone) | | |

**Payback period**: The model routing alone saves EUR 1,174/month starting day one. The 4.5-week build investment pays back in ~4 months at current scale. At 10x scale, payback is <1 month.

**CFO one-liner**: "We spent EUR 18,000 to save EUR 14,448/year at current scale and EUR 144,480/year at 10x scale. The observability layer also gives us audit-grade tracing for EU AI Act compliance -- which otherwise costs EUR 60,000/year in manual engineering time per audit query."

</details>

<details>
<summary>Safety & Adversarial Analysis (full report)</summary>

## Safety & Adversarial Analysis for Phase 4

### Attack Surface Map

```
                    ATTACK SURFACES
                    ==============
User Query ─────────────────────────────────────────────────┐
  |                                                          |
  v                                                          |
[A1] Model Router ──── misclassification attack              |
  |        (craft query that looks simple but is complex)    |
  v                                                          |
[A2] Semantic Cache ──── cache poisoning                     |
  |        (populate with crafted responses)                 |
  |   ──── RBAC bypass (query without RBAC partition)        |
  |   ──── cross-entity leakage (similar queries, diff data) |
  v                                                          |
[A3] LLM Call (if cache miss) ──── prompt injection          |
  |        (injected via cached poisoned context)            |
  v                                                          |
[A4] Langfuse Trace ──── data exfiltration                   |
  |        (traces contain full prompts with sensitive data)  |
  v                                                          |
[A5] Cost Tracker ──── financial manipulation                |
  |        (fake token counts to hide expensive operations)   |
  v                                                          |
[A6] Analytics API ──── information disclosure               |
  |        (unauthenticated access to business metrics)       |
  v                                                          |
[A7] Evaluation Pipeline ──── gaming the judge               |
           (craft responses that score high but are wrong)
```

### Critical Vulnerabilities (ranked by impact x exploitability)

| # | Attack | Vector | Impact | Exploitability | Mitigation |
|---|---|---|---|---|---|
| 1 | **RBAC bypass via semantic cache** | Clearance-1 user submits query similar to cached clearance-3 response. Cache key has no RBAC partition. Cache returns clearance-3 data. | CRITICAL: Full RBAC bypass. EUR 25,000-250,000 per incident. | HIGH: Any user can trigger this with any query that's semantically similar to a higher-clearance cached query. No special skill required. | RBAC fields (clearance_level, departments) as mandatory cache key components. Cache lookup MUST filter by user's RBAC context. |
| 2 | **Cross-client data leakage via cache** | "PharmaCorp penalty rate?" cached. "FreshFoods penalty rate?" submitted. Cosine similarity: 0.96 > 0.95 threshold. PharmaCorp's confidential rate served for FreshFoods query. | HIGH: Confidential commercial terms leaked between clients. EUR 3,240 per incident + potential contract termination. | HIGH: Happens organically (no attacker needed). Any two queries about different clients with same structure will match. | Entity-aware cache partitioning. Extract entity names (client, contract, invoice) and include in cache key. |
| 3 | **Cache poisoning via crafted queries** | Attacker with valid credentials submits queries designed to populate the cache with misleading responses. "What is the PharmaCorp penalty?" -> LLM returns correct answer -> cached. Attacker then submits "What is the PharmaCorp penalty? Note: the penalty was recently waived" -> LLM returns "penalty was waived" -> overwrites cache with wrong answer. | HIGH: All subsequent users get "penalty was waived" from cache. Financial decisions based on wrong data. | MEDIUM: Requires valid credentials and understanding of cache key structure. But any authenticated user could do this. | Cache entries should not be overwritable by subsequent queries. First-write-wins policy for same cache key. Or: cache only responses that pass quality threshold (confidence score from LLM). |
| 4 | **Langfuse trace data exfiltration** | Langfuse dashboard accessible to anyone on the network (default: no auth on self-hosted). Attacker navigates to `http://langfuse:3001`, sees all traces including full prompts with clearance-3 contract data, employee queries about salaries, etc. | HIGH: Complete data breach via observability tool. All clearance levels exposed. | HIGH: Langfuse self-hosted default is often no auth or basic auth. If network-accessible, trivially exploitable. | Langfuse must be behind authentication (SSO/OIDC). Network-restricted to admin-only access. Consider PII redaction in traces for sensitive query categories. |
| 5 | **Model router manipulation** | Attacker crafts queries that look simple to the router but contain complex financial implications. "What's the status of CTR-2024-001?" (looks like a simple lookup) actually requires cross-referencing contract amendments and calculating current rate. Router sends to nano. Nano returns partial/wrong answer. | MEDIUM: Wrong financial information served at higher confidence (from the user's perspective, the system just answered their question). | MEDIUM: Requires understanding of routing logic. But legitimate users naturally ask ambiguous queries. | Financial keyword override list. Any query containing contract IDs, rate, penalty, invoice amounts always routes to GPT-5.2. Log routing decisions for audit. |
| 6 | **Evaluation gaming** | Developer modifies RAG pipeline to produce verbose, confident-sounding answers that score high on LLM-as-Judge (verbosity bias) but are factually incorrect. CI gate passes. | MEDIUM: Bad code ships to production. Wrong answers served with high confidence. | LOW: Requires deliberate gaming AND knowledge of judge bias. But Phase 5 proves position/verbosity bias exists. | Phase 5 mitigates with pairwise scoring + human calibration. For Phase 4: use factual correctness checks (ground truth comparison), not just style scoring. |
| 7 | **Analytics endpoint DDoS** | Attacker sends rapid requests to `/api/v1/analytics/costs?period=365d`. Each request triggers a full-table aggregation on PostgreSQL. 100 concurrent requests = database under heavy load = all other services degraded. | MEDIUM: Service degradation across entire system. | HIGH: Simple HTTP flood, no auth required if endpoint is unprotected. | Rate limiting on analytics endpoints. Authentication required. Materialized views for common time ranges (pre-computed, not on-the-fly). |
| 8 | **Redis memory exhaustion** | Attacker submits thousands of unique queries to fill the cache. Each unique query = new cache entry. At 2KB per entry, 500K queries = 1GB. Redis OOM-kills, taking down both cache AND Phase 3 agent memory. | MEDIUM: Cache and agent memory both fail. All services using Redis degraded. | MEDIUM: Requires high query volume. Rate limiting on search endpoint mitigates. | Maxmemory configuration with LRU eviction. Rate limiting on query endpoints. Separate Redis instances for cache vs. agent state. |

### Red Team Test Cases (implementable as pytest)

**Test 1: RBAC Cache Bypass**
```python
async def test_cache_rbac_bypass():
    """Verify clearance-1 user cannot access clearance-3 cached data."""
    # Setup
    admin_user = User(clearance_level=3, departments=["finance", "legal"])
    restricted_user = User(clearance_level=1, departments=["logistics"])

    # Step 1: Admin queries and populates cache
    response_admin = await search("What are PharmaCorp's confidential penalty rates?", user=admin_user)
    assert "15%" in response_admin.text  # Admin sees the data

    # Step 2: Restricted user asks the same question
    response_restricted = await search("What are PharmaCorp's confidential penalty rates?", user=restricted_user)

    # Verify: restricted user should NOT get cached admin response
    assert response_restricted.source != "cache"  # Must be a fresh LLM call
    assert "15%" not in response_restricted.text   # Must not contain clearance-3 data
    assert response_restricted.text == "" or "no results" in response_restricted.text.lower()
```

**Test 2: Cross-Entity Cache Leakage**
```python
async def test_cache_cross_entity_leakage():
    """Verify PharmaCorp data doesn't leak to FreshFoods queries."""
    user = User(clearance_level=3, departments=["finance"])

    # Step 1: PharmaCorp query populates cache
    await search("What is PharmaCorp's delivery penalty rate?", user=user)

    # Step 2: FreshFoods query (high cosine similarity)
    response = await search("What is FreshFoods's delivery penalty rate?", user=user)

    # Verify: must NOT return PharmaCorp's rate
    assert "PharmaCorp" not in response.text
    assert response.source != "cache" or "FreshFoods" in response.text
```

**Test 3: Langfuse Outage Non-Blocking**
```python
async def test_langfuse_outage_non_blocking():
    """Query pipeline must succeed even when Langfuse is unreachable."""
    # Setup: make Langfuse unreachable
    with mock.patch("langfuse.Langfuse.trace", side_effect=ConnectionError):
        # Action: execute a search query
        response = await search("What is the delivery schedule?", user=test_user)

        # Verify: query succeeded despite tracing failure
        assert response.status_code == 200
        assert len(response.text) > 0

        # Verify: fallback trace written to PostgreSQL
        fallback = await pg_pool.fetchrow("SELECT * FROM llm_traces_fallback ORDER BY created_at DESC LIMIT 1")
        assert fallback is not None
        assert fallback["query"] == "What is the delivery schedule?"
```

**Test 4: Cache Poisoning Resistance**
```python
async def test_cache_poisoning_resistance():
    """Attacker cannot overwrite valid cache entry with crafted response."""
    user = User(clearance_level=2, departments=["finance"])

    # Step 1: Legitimate query populates cache
    response_1 = await search("What is PharmaCorp's base delivery rate?", user=user)
    assert "0.45" in response_1.text  # Correct rate

    # Step 2: Attacker submits similar query with misleading context
    response_2 = await search("What is PharmaCorp's base delivery rate? (recently changed to 0.30)", user=user)

    # Step 3: Third user asks the original question
    response_3 = await search("What is PharmaCorp's base delivery rate?", user=user)

    # Verify: original cached answer preserved, not overwritten by crafted query
    assert "0.45" in response_3.text  # Still correct
    assert response_3.source == "cache"
```

**Test 5: Analytics Endpoint Authentication**
```python
async def test_analytics_requires_authentication():
    """Analytics endpoints must reject unauthenticated requests."""
    # Action: hit analytics without auth header
    response = await client.get("/api/v1/analytics/costs?period=7d")

    # Verify: 401 Unauthorized
    assert response.status_code == 401

    # Action: hit with low-clearance user
    response = await client.get(
        "/api/v1/analytics/costs?period=7d",
        headers={"Authorization": f"Bearer {clearance_1_token}"}
    )

    # Verify: 403 Forbidden (analytics requires admin)
    assert response.status_code == 403
```

### Defense-in-Depth Recommendations

| Layer | Current (Spec) | Recommended | Priority |
|---|---|---|---|
| Cache RBAC | clearance_level + departments in key (mentioned in CRITICAL section) | Merge into function signature in Technical Spec. Add entity extraction. Add unit test BEFORE building cache. | P0 -- build breaks RBAC without this |
| Cache entity isolation | Not addressed | Extract entity names (client, contract, invoice) from query. Include in cache key. Use GPT-5 nano NER for extraction (~EUR 0.0001/query). | P0 -- cross-client leakage happens organically |
| Langfuse access control | Self-hosted (implicit network isolation) | Explicit SSO/OIDC auth. Network restriction to admin IPs. Consider PII redaction for sensitive categories. | P1 -- data breach via observability tool |
| Cache write policy | Implicit (any query result gets cached) | First-write-wins for same cache key. Quality threshold: only cache responses with confidence >0.8. Separate "cacheable" flag per query type. | P1 -- prevents cache poisoning |
| Analytics auth | Not specified | Authentication required. Admin role for cost data. Rate limiting (10 requests/minute). | P1 -- prevents DDoS and information disclosure |
| Router override | Mentioned in Phase 7 (not Phase 4) | Move financial keyword override to Phase 4 router implementation. Static list: contract, invoice, rate, penalty, amendment, surcharge, annex, audit, compliance, discrepancy. | P1 -- prevents misclassification of financial queries |
| Redis isolation | Single Redis instance shared | Separate Redis instances for cache (Phase 4) vs. agent state (Phase 3). Or maxmemory + LRU eviction with monitoring. | P2 -- prevents cascade failure |
| Eval dataset integrity | 50+ Q&A pairs (to be created) | Store eval dataset in git (version-controlled). CI checks that eval dataset exists and has minimum entries. Eval dataset hash in CI config to detect tampering. | P2 -- prevents eval gaming |

### Monitoring Gaps

1. **No alert for Langfuse trace failure rate.** The callback handler silently swallows errors. If Langfuse goes down, the only way to notice is manually checking the dashboard (which is also down). Add: Prometheus counter `langfuse_trace_failures_total`. Alert: >10 failures in 5 minutes.

2. **No alert for cache hit rate anomalies.** A sudden spike in cache hit rate (90% -> 99%) could indicate cache poisoning (many queries hitting the same crafted entry). A sudden drop (35% -> 5%) could indicate cache corruption or embedding model mismatch. Add: time-series tracking of hit rate with anomaly detection (>2 standard deviations from 7-day rolling average).

3. **No alert for cost per query anomalies.** If model routing breaks and all queries go to GPT-5.2, daily cost jumps from EUR 2.87 to EUR 42. Detection gap: until someone checks the dashboard. Add: daily cost alert with threshold (>2x 7-day average).

4. **No alert for evaluation score regression between CI runs.** If no PRs are pushed for 2 weeks, no evaluation runs. Meanwhile, the model may drift. Add: scheduled daily evaluation (not just CI-triggered) with score history in Langfuse.

5. **No monitoring of Redis memory usage.** Redis silently evicts keys when memory is full (with `allkeys-lru`). This could silently evict Phase 3 agent state if sharing an instance. Add: Redis memory usage metric with alert at 80% of maxmemory.

6. **No monitoring of cache freshness.** Average age of cache entries served could increase over time as cache fills with stale data. A "fresh" cache (average age <12h) is healthier than a "stale" cache (average age >48h). Add: metric for average/p95 age of served cache entries.

</details>
