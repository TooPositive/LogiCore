# Phase 4 Technical Recap: Trust Layer — LLMOps, Observability & Evaluation

## What This Phase Does (Business Context)

A logistics company runs AI across document search, invoice auditing, and fleet monitoring. Without observability, nobody knows what each query costs, whether quality is degrading, or whether the cache is leaking confidential data across clearance levels. Phase 4 makes AI costs visible, routes queries to the cheapest acceptable model, caches responses with RBAC-aware partitioning, and establishes a CI quality gate.

## Architecture Overview

```
                        Incoming Query
                             │
                    ┌────────▼────────┐
                    │  ModelRouter     │  Keyword override → COMPLEX
                    │  (GPT-5 nano)   │  LLM classify → SIMPLE/MEDIUM/COMPLEX
                    │                 │  Confidence < 0.7 → escalate
                    └────────┬────────┘
                             │ ModelRoute (model + reason)
                    ┌────────▼────────┐
                    │  SemanticCache   │  Partition: cl:N|dept:X|ent:Y
                    │  (RBAC-aware)    │  Hit → return cached (EUR 0.00)
                    │                 │  Miss → proceed to LLM
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  LLM Call        │  nano / mini / 5.2
                    │  (routed model)  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  LangfuseHandler │  trace_id, model, tokens, cost
                    │  + CostTracker   │  Langfuse fails → FallbackStore
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Analytics API   │  GET /costs → CostSummary
                    │  (FastAPI)       │  GET /quality → EvalScore
                    └─────────────────┘

  Evaluation Pipeline (CI):
    eval_dataset.json → llm_judge → EvalScore → passes_quality_gate()
                                                 exit 0 / exit 1
```

## Components Built

### 1. Domain Models: `apps/api/src/domain/telemetry.py`

**What it does**: 6 Pydantic v2 models that define the vocabulary of the Trust Layer — every other component speaks through these types.

**The pattern**: Rich domain models with embedded business logic. The models aren't just data bags — `EvalScore.passes_quality_gate()` encodes the CI gate rule, `CacheEntry.rbac_partition_key()` encodes the security partitioning, `CacheEntry.is_stale()` encodes staleness detection.

**Key code walkthrough**:

```python
# apps/api/src/domain/telemetry.py:88-125

class CacheEntry(BaseModel):
    cache_key: str
    query: str
    response: str
    embedding: list[float]
    clearance_level: int = Field(ge=1, le=4)      # 1=warehouse, 4=admin
    departments: list[str]
    entity_keys: list[str] = Field(default_factory=list)  # PharmaCorp, FreshFoods
    source_doc_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = Field(gt=0)

    def rbac_partition_key(self) -> str:
        # WHY sorted: ["hr", "finance"] and ["finance", "hr"] must produce
        # the same key, otherwise same user gets different partitions on
        # different requests depending on list order.
        sorted_depts = sorted(self.departments)
        sorted_entities = sorted(self.entity_keys)
        parts = [
            f"cl:{self.clearance_level}",
            f"dept:{','.join(sorted_depts)}",
            f"ent:{','.join(sorted_entities)}",
        ]
        return "|".join(parts)

    def is_stale(self, doc_updated_at: datetime) -> bool:
        # WHY simple comparison: if the source doc was touched after we
        # cached this entry, the cached answer might be wrong.
        # Conservative: even a metadata-only update triggers staleness.
        return doc_updated_at > self.created_at
```

**Why it matters**: Putting `rbac_partition_key()` on the model means every consumer (cache, tests, analytics) uses the same partitioning logic. If you put it in the cache class instead, you'd duplicate it for Redis Stack production cache vs in-memory dev cache.

**Alternatives considered**: Separate partition key utility function (chosen against because the partition depends on CacheEntry fields — co-location is cleaner). Hash-based partition key (chosen against because debugging needs readable keys like `cl:3|dept:finance|ent:PharmaCorp`, not hex blobs).

---

### 2. Semantic Cache: `apps/api/src/infrastructure/llm/cache.py`

**What it does**: RBAC-aware semantic cache that finds similar cached queries within the same security partition. In-memory implementation with identical interface to production Redis Stack.

**The pattern**: Namespace isolation via partition keys. The cache doesn't "check" RBAC — it physically separates entries into different namespaces. A clearance-1 query literally cannot reach a clearance-3 entry because they're in different dictionaries.

**Key code walkthrough**:

```python
# apps/api/src/infrastructure/llm/cache.py:46-63

def _partition_key(
    clearance_level: int,
    departments: list[str],
    entity_keys: list[str] | None = None,
) -> str:
    sorted_depts = sorted(departments)
    sorted_entities = sorted(entity_keys or [])
    parts = [
        f"cl:{clearance_level}",
        f"dept:{','.join(sorted_depts)}",
        f"ent:{','.join(sorted_entities)}",
    ]
    return "|".join(parts)
```

This is a module-level function, not a method, because both `get()` and `put()` need it and it has no state dependency.

```python
# apps/api/src/infrastructure/llm/cache.py:93-143

async def get(
    self,
    query: str,
    clearance_level: int,
    departments: list[str],
    embed_fn: EmbedFn,                              # injected dependency
    entity_keys: list[str] | None = None,
    doc_update_times: dict[str, datetime] | None = None,  # staleness check
) -> str | None:
    partition = _partition_key(clearance_level, departments, entity_keys)

    if partition not in self._partitions:
        return None  # different RBAC context = instant miss, no embedding needed

    query_embedding = await embed_fn(query)
    entries = self._partitions[partition]

    best_entry: CacheEntry | None = None
    best_similarity = 0.0

    for entry in entries.values():
        sim = _cosine_similarity(query_embedding, entry.embedding)
        if sim > best_similarity:
            best_similarity = sim
            best_entry = entry

    if best_entry is None or best_similarity < self.similarity_threshold:
        return None

    # WHY staleness check AFTER similarity: avoid unnecessary datetime
    # comparisons on entries that don't match anyway
    if doc_update_times and best_entry.source_doc_ids:
        for doc_id in best_entry.source_doc_ids:
            if doc_id in doc_update_times:
                if best_entry.is_stale(doc_update_times[doc_id]):
                    return None  # stale = treat as miss

    entry_key = best_entry.cache_key
    if entry_key in entries:
        entries.move_to_end(entry_key)  # LRU: move to "most recent" position

    return best_entry.response
```

**Why it matters**: Without entity partitioning, "PharmaCorp penalty rate?" (cached at 15%) would serve "FreshFoods penalty rate?" (actual 10%) at 0.96 cosine similarity. Finance applies the wrong rate. EUR 3,240 per incident.

**Alternatives considered**:
- Post-retrieval RBAC filter (rejected: a filter can be bypassed by bugs in filter logic; a partition boundary cannot be crossed by definition)
- Hash-based exact-match cache (lower hit rate ~15% vs ~25% with semantic matching, but zero false-match risk — this was Approach B in the approaches doc)
- No entity keys, just clearance + department (rejected: "PharmaCorp penalty" and "FreshFoods penalty" would land in same partition if same user has same clearance/dept for both clients)

---

### 3. Model Router: `apps/api/src/infrastructure/llm/router.py`

**What it does**: Routes each query to the cheapest model that produces an acceptable answer. Uses GPT-5 nano for classification with keyword overrides for financial terms.

**The pattern**: Two-tier classification with deterministic override. The keyword check runs BEFORE the LLM call (costs EUR 0.00, deterministic). The LLM classifier handles everything else. This is the "fast path + slow path" pattern — most expensive decisions are caught cheaply.

**Key code walkthrough**:

```python
# apps/api/src/infrastructure/llm/router.py:29-40

# WHY these specific keywords: they indicate queries where a wrong answer
# has EUR 486-3,240 cost. "rate" alone catches "what's the rate for X?"
# which requires cross-referencing base rate + amendments + surcharges.
OVERRIDE_KEYWORDS: list[str] = [
    "contract", "invoice", "rate", "penalty", "amendment",
    "surcharge", "annex", "audit", "compliance", "discrepancy",
]
```

```python
# apps/api/src/infrastructure/llm/router.py:129-180

async def classify(self, query: str) -> ModelRoute:
    # Step 1: Keyword override — free, deterministic, no LLM call
    if check_keyword_override(query, custom_keywords=self._keywords):
        matched = [kw for kw in self._keywords if kw.lower() in query.lower()]
        return ModelRoute(
            query=query,
            complexity=QueryComplexity.COMPLEX,
            selected_model=self._model_map[QueryComplexity.COMPLEX],
            confidence=1.0,
            routing_reason=f"keyword_override: {', '.join(matched)}",
            keyword_override=True,
        )

    # Step 2: LLM classification (nano, ~EUR 0.000025)
    prompt = CLASSIFIER_PROMPT.format(query=query)
    response = await self._llm.ainvoke(prompt)
    response_text = response.content if hasattr(response, "content") else str(response)
    complexity, confidence = _parse_classification(response_text)

    # Step 3: Low confidence → escalate one tier
    # WHY: if the router isn't sure, send to a more capable model.
    # Overcassification costs ~EUR 0.017 extra. Misclassification costs EUR 486-3,240.
    if confidence < self._confidence_threshold:
        original = complexity
        complexity = _ESCALATION[complexity]
        # ...
```

```python
# apps/api/src/infrastructure/llm/router.py:83-106

def _parse_classification(response: str) -> tuple[QueryComplexity, float]:
    response = response.strip().upper()
    match = re.match(r"(SIMPLE|MEDIUM|COMPLEX)\s*([\d.]+)?", response)
    if match:
        complexity_str = match.group(1)
        confidence_str = match.group(2)
        complexity = QueryComplexity(complexity_str)
        confidence = float(confidence_str) if confidence_str else 0.8
        confidence = max(0.0, min(1.0, confidence))
        return complexity, confidence

    # WHY default to COMPLEX: unparseable = unknown = assume worst case.
    # The system can waste money on overclassification but must never
    # save money by misclassifying a complex query as simple.
    logger.warning("Unparseable router response: %s, defaulting to COMPLEX", response)
    return QueryComplexity.COMPLEX, 0.0
```

**Why it matters**: Without routing, everything runs on GPT-5.2: EUR 42/day. With routing: EUR 2.87/day. 93% reduction. The router itself costs EUR 0.06/day (nano classification calls).

**Alternatives considered**:
- Static rule-based routing only (lower effort but misses nuanced complexity; keyword override IS the static layer, LLM handles the rest)
- No keyword override (rejected: financial misrouting costs EUR 486-3,240 per incident; keywords catch exactly those queries for free)
- Confidence threshold at 0.5 instead of 0.7 (rejected: too many borderline queries would stay at lower tier; 0.7 is conservative enough to catch ambiguity)

---

### 4. Langfuse Handler: `apps/api/src/telemetry/langfuse_handler.py`

**What it does**: Non-blocking observability handler that traces every LLM call to Langfuse, with fallback to a local store when Langfuse is unavailable.

**The pattern**: Graceful degradation with double try/except. The critical insight: telemetry failure must NEVER block the user's query. The outer try catches Langfuse failures → fallback store. The inner try catches fallback store failures → log and continue.

**Key code walkthrough**:

```python
# apps/api/src/telemetry/langfuse_handler.py:135-162

try:
    self._langfuse.trace(
        name=agent_name,
        id=trace_id,
        input=prompt,
        output=response,
        metadata={
            "run_id": run_id,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "cost_eur": str(cost),
            **(metadata or {}),
        },
    )
except Exception:
    # WHY bare Exception: Langfuse can throw anything (ConnectionError,
    # TimeoutError, HTTPError, etc.) and we want to catch ALL of them.
    logger.warning(
        "Langfuse unavailable for trace %s, writing to fallback",
        trace_id,
    )
    try:
        self._fallback.store_trace(trace)
    except Exception:
        # WHY double try/except: if even the fallback fails (disk full,
        # memory pressure), we still return the LLM result to the user.
        logger.error(
            "Both Langfuse and fallback store failed for trace %s",
            trace_id,
        )
```

**Reconciliation** backfills Langfuse from the fallback store after recovery:

```python
# apps/api/src/telemetry/langfuse_handler.py:45-73

def reconcile_fallback(
    langfuse_client: Any,
    fallback_store: InMemoryFallbackStore,
) -> int:
    pending = fallback_store.get_pending()
    reconciled = 0
    for trace in pending:
        langfuse_client.trace(
            name=trace.agent_name,
            id=trace.trace_id,
            metadata={...},
        )
        reconciled += 1
    fallback_store.drain()  # clear after successful backfill
    return reconciled
```

**Why it matters**: Langfuse is a compliance dependency — Phase 8's audit log references trace IDs. Lost traces = broken audit trail = EUR 10,000-100,000 regulatory exposure.

**Known gap**: `reconcile_fallback()` is not idempotent. If 3 of 5 traces are reconciled and then it crashes before `drain()`, re-running reconciles all 5 (3 duplicates). Mapped to Phase 7 for fix.

---

### 5. Cost Tracker: `apps/api/src/telemetry/cost_tracker.py`

**What it does**: Per-query cost calculation using exact Decimal arithmetic against a configurable model pricing table. Aggregation by agent, user, and time period.

**The pattern**: Strategy pattern for pricing. The `ModelPricing` objects and `pricing_table` dict are injected — swap the table for different providers (Azure vs Anthropic vs local) without changing calculation logic.

**Key code walkthrough**:

```python
# apps/api/src/telemetry/cost_tracker.py:29-45

# WHY Decimal, not float: EUR 0.000065 per query x 2,400 queries =
# EUR 0.156. With float: 0.000065 * 2400 = 0.15600000000000003.
# Small but compounds over months. Decimal prevents rounding drift.
MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-5-nano": ModelPricing(
        model_name="gpt-5-nano",
        input_per_1m=Decimal("0.05"),   # $0.05 / 1M input tokens
        output_per_1m=Decimal("0.40"),  # $0.40 / 1M output tokens
    ),
    "gpt-5-mini": ModelPricing(
        model_name="gpt-5-mini",
        input_per_1m=Decimal("0.25"),
        output_per_1m=Decimal("2.00"),
    ),
    "gpt-5.2": ModelPricing(
        model_name="gpt-5.2",
        input_per_1m=Decimal("1.75"),
        output_per_1m=Decimal("14.00"),
    ),
}
```

```python
# apps/api/src/telemetry/cost_tracker.py:48-87

def calculate_query_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pricing_table: dict[str, ModelPricing] | None = None,
    cache_hit: bool = False,
) -> Decimal:
    if cache_hit:
        return Decimal("0")  # WHY: cache hits consume 0 tokens = EUR 0.00

    if prompt_tokens == 0 and completion_tokens == 0:
        return Decimal("0")

    table = pricing_table or MODEL_PRICING
    if model not in table:
        raise ValueError(f"Unknown model: {model}")

    pricing = table[model]
    input_cost = (Decimal(prompt_tokens) / Decimal("1000000")) * pricing.input_per_1m
    output_cost = (Decimal(completion_tokens) / Decimal("1000000")) * pricing.output_per_1m
    return input_cost + output_cost
```

**Why Decimal matters**: The test `test_routing_economics_daily_cost` validates that routing saves 93%: routed daily cost EUR 2.87 vs unrouted EUR 42.00. With float arithmetic, accumulated rounding errors would make the assertion flaky.

---

### 6. Analytics API: `apps/api/src/api/v1/analytics.py`

**What it does**: Two FastAPI endpoints that serve FinOps data and quality scores.

**The pattern**: Factory function with dependency injection. `create_analytics_router(cost_tracker, eval_scores)` returns a configured `APIRouter`. No global state — the router is testable with mock dependencies.

**Key code walkthrough**:

```python
# apps/api/src/api/v1/analytics.py:60-66

def create_analytics_router(
    cost_tracker: CostTracker,
    eval_scores: EvalScore | None,  # None = no eval run yet → 404 on /quality
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
    # ... endpoint definitions close over cost_tracker and eval_scores
    return router
```

**Why factory function over class**: FastAPI routers are function-based. A class wrapper adds indirection without benefit. The factory pattern matches FastAPI's style and is used throughout the codebase (Phase 3's `create_audit_router()` uses the same pattern).

---

### 7. Evaluation Pipeline: `tests/evaluation/llm_judge.py` + `scripts/run_evaluation.py`

**What it does**: Mock LLM-as-Judge that scores RAG quality on 3 metrics (context precision, faithfulness, answer relevancy). CLI runner for CI with exit code 0/1.

**The pattern**: Deterministic test double with same interface as production. The mock judge uses word-overlap heuristics. Production judge (Phase 5) uses GPT-5-mini for claim-by-claim analysis. Both return `EvalScore`.

**Key code walkthrough**:

```python
# tests/evaluation/llm_judge.py:48-73

def score_faithfulness(question, context, answer) -> float:
    answer_words = set(answer.lower().split())
    context_words = set(context.lower().split())
    question_words = set(question.lower().split())

    # WHY include question_words: the answer echoing the question
    # ("What's the penalty?" → "The penalty is 2%") is faithful behavior,
    # not hallucination. Without this, "penalty" in the answer but not
    # in the context would lower the score.
    grounded_source = context_words | question_words
    grounded = answer_words & grounded_source
    grounded_ratio = len(grounded) / len(answer_words)
    return min(1.0, grounded_ratio * 1.2 + 0.15)
```

**Why mock judge is deliberate**: The mock scores (0.89/0.83/0.89) are pipeline validation metrics, not production quality. They prove: dataset loads → judge scores → quality gate blocks/passes → CLI exits 0/1. Real scoring needs Phase 5. The mock judge's value is in proving the pipeline mechanics work, not the absolute numbers.

## Key Decisions Explained

### Decision 1: RBAC Partition Key vs Post-Retrieval Filter

- **The choice**: Cache entries are physically separated into different partitions by `cl:N|dept:X|ent:Y`
- **The alternatives**: (a) Single cache namespace with RBAC filter on read, (b) Hash-based exact-match cache (no similarity, no false matches)
- **The reasoning**: A filter can have bugs. A partition boundary is structural — code that looks up clearance-1 entries literally cannot reach clearance-3 entries because they're in different data structures. This is the same principle as OS process isolation vs application-level access checks.
- **The trade-off**: Hit rate drops from 35% (unpartitioned) to 15-25% (partitioned). EUR 5-10/day less savings. One wrong cached response costs EUR 3,240.
- **When to revisit**: If cache hit rate drops below 10% (partitions too granular), consider coarser entity grouping (e.g., partition by client tier not individual client).
- **Interview version**: "We partition the cache by RBAC context — clearance level, department, and entity name. This means a clearance-1 user's query physically cannot reach a clearance-3 cache entry. It's not a filter that checks permissions; it's namespace isolation. We lose 10-20% hit rate but eliminate the entire class of cache-based data leakage."

### Decision 2: Keyword Override Before LLM Classification

- **The choice**: 10 financial keywords force COMPLEX routing, bypassing the LLM classifier entirely
- **The alternatives**: (a) Trust the LLM classifier for everything, (b) Rules-only routing with no LLM classifier
- **The reasoning**: Financial misrouting costs EUR 486-3,240 per incident. Keyword check costs EUR 0.00 (string match). The LLM classifier handles the 60% of queries where misclassification cost is near-zero.
- **The trade-off**: Some non-financial queries containing "rate" (e.g., "what's the exchange rate?") route to the expensive model unnecessarily. Overclassification waste: ~EUR 0.017/query. Misclassification damage: EUR 486-3,240/query.
- **When to revisit**: (a) When false-positive rate exceeds 30% (too many non-financial queries hitting keyword override), expand to a financial phrase list instead of single words. (b) When deploying for Polish-speaking users: add "faktura", "umowa", "kara", "stawka".
- **Interview version**: "The model router has a keyword override that catches financial terms before the LLM classifier even runs. It's insurance — deterministic, free, and catches the exact queries where a wrong model selection costs EUR 3,240. The LLM handles everything else where misclassification risk is near-zero."

### Decision 3: Non-Blocking Telemetry with Double Try/Except

- **The choice**: Langfuse failure → fallback store → log error → continue. The LLM result is never blocked.
- **The alternatives**: (a) Synchronous Langfuse calls (blocks user if Langfuse is down), (b) Fire-and-forget with no fallback (traces lost on outage), (c) Queue-based async (adds infrastructure complexity)
- **The reasoning**: Langfuse is a compliance dependency (Phase 8 audit logs reference trace IDs). But blocking the user because your observability tool is down is worse than losing traces.
- **The trade-off**: During outage, traces go to in-memory fallback store (lost on process restart). Production needs PostgreSQL-backed fallback.
- **When to revisit**: When deploying to production — swap InMemoryFallbackStore for asyncpg-backed store.
- **Interview version**: "We have a double try/except in the telemetry handler. Langfuse fails? Write to fallback store. Fallback fails too? Log the error and return the LLM result anyway. The user's query is never blocked by observability failure. We reconcile traces after recovery."

### Decision 4: Mock Judge for CI, Real Judge for Production

- **The choice**: Word-overlap heuristics for CI quality gate, deferring real LLM judge to Phase 5
- **The alternatives**: (a) Real LLM judge from day one, (b) No evaluation pipeline until Phase 5
- **The reasoning**: The evaluation pipeline has many moving parts (dataset loading, scoring, aggregation, gate logic, CLI integration). Building the pipeline with a mock judge validates all the mechanics. Phase 5 swaps the scoring function.
- **The trade-off**: Mock scores (0.89/0.83/0.89) are not production quality numbers. Position bias inflates real LLM scores by ~4 points. If true faithfulness is 0.79, the mock says 0.83 (passes gate) while reality fails.
- **When to revisit**: Phase 5 — calibrate mock vs real LLM judge gap on the same 50 Q&A pairs.
- **Interview version**: "We built the full evaluation pipeline in Phase 4 with a mock judge — word overlap heuristics that validate the pipeline mechanics work end-to-end. The mock scores aren't production quality; they're pipeline validation. Phase 5 swaps in a real LLM judge and quantifies position bias."

### Decision 5: Decimal Arithmetic for Cost Tracking

- **The choice**: `Decimal` throughout the cost calculation pipeline, not `float`
- **The alternatives**: Float arithmetic (simpler, faster, standard)
- **The reasoning**: EUR 0.000065 per query x 2,400 queries/day x 30 days = EUR 4.68/month. Float: `0.000065 * 72000 = 4.680000000000001`. Decimal: exactly `4.68`. Small per-query, compounds over months.
- **The trade-off**: Slightly more verbose code (`Decimal("0.05")` vs `0.05`). Marginal performance difference (irrelevant — this runs once per query, not in a tight loop).
- **When to revisit**: Never for cost tracking. This is the standard pattern for financial calculations.
- **Interview version**: "We use Decimal for all cost calculations. Float rounding accumulates over thousands of queries — at scale, the monthly summary would be off by cents to euros. For a FinOps dashboard that a CFO reads, that's unacceptable."

## Patterns & Principles Used

### 1. Namespace Isolation (Cache Partitioning)

**What**: Separate data into independent namespaces that cannot interact.
**Where**: `apps/api/src/infrastructure/llm/cache.py:46-63` — `_partition_key()` function.
**Why**: Prevents cross-clearance and cross-client data leakage without access control checks. The partition boundary is structural, not logical.
**When you WOULDN'T use it**: When all users have the same access level (no RBAC) — partitioning adds overhead without security benefit.

### 2. Graceful Degradation (Non-Blocking Telemetry)

**What**: System continues functioning when a non-critical dependency fails.
**Where**: `apps/api/src/telemetry/langfuse_handler.py:135-162` — double try/except.
**Why**: Langfuse outage should degrade observability, not block user queries.
**When you WOULDN'T use it**: When the dependency IS the critical path (e.g., you wouldn't gracefully degrade the database lookup for a database query tool).

### 3. Two-Tier Classification (Keyword Override + LLM)

**What**: Deterministic fast path for known cases, probabilistic slow path for everything else.
**Where**: `apps/api/src/infrastructure/llm/router.py:129-148` — keyword check before LLM call.
**Why**: Financial keywords have asymmetric misclassification costs (EUR 3,240 vs EUR 0.017). Deterministic check catches high-cost cases for free.
**When you WOULDN'T use it**: When misclassification cost is uniform across categories — the two tiers add complexity without benefit.

### 4. Factory Function with Dependency Injection (Analytics API)

**What**: Function that returns a configured FastAPI router with injected dependencies.
**Where**: `apps/api/src/api/v1/analytics.py:60-116` — `create_analytics_router()`.
**Why**: Testable without global state. Tests inject mock CostTracker; production injects real one.
**When you WOULDN'T use it**: For simple endpoints with no dependencies — adds indirection.

### 5. Rich Domain Models with Business Logic

**What**: Pydantic models that embed business rules (quality gate, staleness, partitioning).
**Where**: `apps/api/src/domain/telemetry.py` — `EvalScore.passes_quality_gate()`, `CacheEntry.is_stale()`, `CacheEntry.rbac_partition_key()`.
**Why**: Business rules live with the data they operate on. Every consumer uses the same logic.
**When you WOULDN'T use it**: When the model is purely a data transport (no business rules to embed).

### 6. Deterministic Test Doubles (Hash-Based Embedder)

**What**: Consistent fake embeddings from SHA-256 hash for reproducible tests.
**Where**: `tests/unit/test_semantic_cache.py:17-28` and `tests/red_team/test_phase4_trust_layer.py:26-35`.
**Why**: Same input always produces same embedding. Tests are deterministic without live Azure OpenAI. Established in Phase 1, reused in Phase 4.
**When you WOULDN'T use it**: When testing embedding QUALITY (Phase 2 live benchmarks need real embeddings).

## Benchmark Results & What They Mean

| Metric | Value | What It Means |
|---|---|---|
| Unrouted daily cost | EUR 42.00 | Baseline: everything on GPT-5.2 at 2,400 queries/day |
| Routed + cached daily cost | EUR 2.87 | 93% reduction. Router costs EUR 0.06/day to run. |
| Cache hit rate (pre-partition) | 35% | Theoretical max without RBAC partitioning |
| Cache hit rate (effective) | 15-25% | After RBAC + entity partitioning. Security tax. |
| Cost per search query | EUR 0.0015 | GPT-5 mini, 2800 in + 400 out tokens |
| Cost per audit query | EUR 0.031 | GPT-5.2, 8200 in + 1200 out tokens |
| Cost per simple query | EUR 0.000065 | GPT-5 nano, 500 in + 100 out tokens |
| Mock judge: precision | 0.89 | Pipeline validation, not production quality |
| Mock judge: faithfulness | 0.83 | Closest to 0.8 gate — correctly identifies hardest metric |
| Mock judge: relevancy | 0.89 | Pipeline validation |

**Boundary found**: The keyword override list is English-only. Polish queries with "faktura" (invoice) or "kara" (penalty) bypass the override. Mapped to Phase 6.

## Test Strategy

**Organization**: 166 new tests across 5 suites:
- `tests/unit/` (135): Domain models, cost tracker, Langfuse handler, model router, semantic cache, analytics API
- `tests/evaluation/` (13): Dataset validation, LLM-as-Judge scoring, pipeline integration
- `tests/red_team/` (24): 8 attack categories proving what the system refuses to do
- `tests/e2e/` (4): Full app flow through FastAPI TestClient

**What the tests prove**:
- RBAC cache bypass is structurally impossible (5 clearance-level tests + 3 red team)
- Cross-client data never leaks (3 entity isolation tests + 3 red team)
- Stale cached data is never served (7 staleness/invalidation tests)
- Financial queries always route to GPT-5.2 (10 parametrized keyword tests + 5 red team)
- Langfuse outage never blocks user queries (4 fallback + non-blocking tests)
- Cost calculations are exact (8 Decimal arithmetic tests)
- Evaluation pipeline correctly gates (13 judge + pipeline tests)

**Mocking strategy**: Hash-based deterministic embedder (SHA-256 → 10-dim vector). MagicMock for Langfuse client (can be configured to raise exceptions). AsyncMock for LLM classifier responses. No live services needed for unit tests.

**What ISN'T tested**:
- Real Redis Stack vector similarity (in-memory only) → integration test needed
- Real Langfuse API calls → integration test needed
- Real LLM judge scoring → Phase 5
- Multilingual keyword override → Phase 6
- Reconciliation idempotency → Phase 7
- LRU fairness under skewed partition access → Phase 12

## File Map

| File | Purpose | Key Patterns | Lines |
|------|---------|-------------|-------|
| `apps/api/src/domain/telemetry.py` | Domain models (6 types) | Rich domain models, embedded business logic | ~142 |
| `apps/api/src/telemetry/__init__.py` | Package init | — | 1 |
| `apps/api/src/telemetry/langfuse_handler.py` | Tracing + fallback | Graceful degradation, double try/except | ~201 |
| `apps/api/src/telemetry/cost_tracker.py` | FinOps calculations | Strategy pattern (pricing table), Decimal | ~209 |
| `apps/api/src/infrastructure/llm/router.py` | Query routing | Two-tier classification, keyword override | ~185 |
| `apps/api/src/infrastructure/llm/cache.py` | RBAC-aware cache | Namespace isolation, LRU eviction | ~246 |
| `apps/api/src/api/v1/analytics.py` | FinOps API endpoints | Factory function, dependency injection | ~117 |
| `tests/evaluation/llm_judge.py` | Mock LLM-as-Judge | Deterministic test double | ~131 |
| `tests/evaluation/eval_dataset.json` | 50 Q&A ground truth | 5 categories, >=5 per category | ~50 entries |
| `scripts/run_evaluation.py` | CI eval runner | Exit code 0/1 for quality gate | ~96 |
| `tests/unit/test_telemetry_models.py` | Domain model tests | Validation, partition key, staleness | 27 tests |
| `tests/unit/test_cost_tracker.py` | Cost calculation tests | Decimal arithmetic, routing economics | 25 tests |
| `tests/unit/test_langfuse_handler.py` | Tracing tests | Fallback, non-blocking, reconciliation | 13 tests |
| `tests/unit/test_model_router.py` | Routing tests | Keyword override (10 parametrized), escalation | 27 tests |
| `tests/unit/test_semantic_cache.py` | Cache tests | RBAC, entity, staleness, LRU | 24 tests |
| `tests/unit/test_analytics_api.py` | API endpoint tests | Period validation, 404, costs response | 9 tests |
| `tests/red_team/test_phase4_trust_layer.py` | Security tests | 8 attack categories | 24 tests |
| `tests/evaluation/test_rag_quality.py` | Eval pipeline tests | Dataset validation, judge scoring | 13 tests |
| `tests/e2e/test_analytics_e2e.py` | Full app flow tests | TestClient, router registration | 4 tests |

## Interview Talking Points

1. **Cache RBAC bypass**: "We partition the semantic cache by clearance level, department, and entity name. A clearance-1 query physically cannot reach clearance-3 data — it's namespace isolation, not access control filtering. The trade-off is hit rate drops from 35% to 15-25%, but one wrong cached response costs EUR 3,240 and a GDPR violation."

2. **Model routing economics**: "We route queries to the cheapest acceptable model: nano for lookups, mini for search, 5.2 for financial analysis. That's EUR 2.87/day vs EUR 42/day — 93% reduction. The router runs on nano at EUR 0.000025 per classification. Financial keywords bypass the classifier entirely because misrouting a penalty query costs EUR 486-3,240."

3. **Non-blocking observability**: "The telemetry handler has a double try/except: Langfuse fails → fallback store, fallback fails → log and continue. The user's query result is never blocked by an observability outage. Langfuse is a compliance dependency (audit logs reference trace IDs), so we reconcile the fallback store after recovery."

4. **Why mock judge is deliberate**: "Phase 4 builds the evaluation pipeline with a mock judge that validates mechanics: dataset loads, scoring works, quality gate blocks/passes, CLI exits correctly. Phase 5 swaps in a real LLM judge and quantifies position bias (~4 points). Building pipeline mechanics first, calibrating second — same as building the test harness before writing real tests."

5. **Decimal for financial calculations**: "We use Decimal arithmetic throughout cost tracking. Float 0.000065 * 72,000 = 4.680000000000001. Decimal gives exactly 4.68. Small per query, compounds over months. If the CFO's dashboard shows a rounding error, trust in the whole system drops."

6. **Entity-aware cache prevents cross-client leakage**: "'PharmaCorp penalty rate' and 'FreshFoods penalty rate' score 0.96 cosine similarity. Without entity partitioning, the cache serves PharmaCorp's 15% penalty when someone asked about FreshFoods' 10%. Different entity keys = different partitions = structurally impossible to mix up."

7. **Safe fallback everywhere**: "Unparseable LLM router response defaults to COMPLEX (expensive but safe). Low confidence escalates one tier. Keyword override bypasses the LLM entirely. The system can waste money on overclassification but can never save money by misclassifying."

## What I'd Explain Differently Next Time

**The cache partition key is the easiest thing to explain wrong.** I'd lead with the attack scenario first: "A clearance-1 user asks the same question that a clearance-3 user just asked. Without partitioning, the cache serves confidential data. With partitioning, they're in separate namespaces." The partition key code is trivial — the WHY is the entire point.

**Model routing should be explained as Kahneman's System 1/System 2.** Simple queries get fast, cheap answers (System 1 = nano). Complex queries get slow, expensive reasoning (System 2 = GPT-5.2). Everyone immediately gets it. The keyword override is the "amygdala hijack" — when you see a financial keyword, skip classification and go straight to the expensive model.

**The double try/except in the Langfuse handler looks like defensive over-engineering until you explain Langfuse as a compliance dependency.** Phase 8's audit log stores trace IDs. Lost traces = broken audit trail = regulatory exposure. Then the double try/except becomes obvious — you can't lose traces AND you can't block users.

**The mock judge confusion**: People assume 0.89 precision means the RAG is 89% accurate. It means the pipeline mechanics work. The absolute numbers are meaningless until Phase 5 calibrates with a real LLM judge. This needs to be said upfront, not as a footnote.
