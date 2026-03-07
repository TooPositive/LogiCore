# Phase 4: "The Trust Layer" — LLMOps, Observability & Evaluation

## Business Problem

The RAG works. The agents work. But the CFO asks: "How much does each AI query cost?" The CTO asks: "How do we know it's not hallucinating?" The compliance officer asks: "Can you prove the accuracy hasn't degraded since last month?"

Without observability, AI is a black box. Black boxes don't get deployed in enterprises.

**CTO pain**: "We can't manage what we can't measure. Give me dashboards, SLAs, and automated quality gates — or this stays a POC forever."

## Real-World Scenario: LogiCore Transport

**Feature: AI Cost & Quality Dashboard**

CFO Martin Lang opens the analytics dashboard on Monday morning. He sees:

- **Daily AI spend**: €47 (down from €68 last week — semantic caching kicked in)
- **Queries yesterday**: 1,847
- **Average cost per query**: €0.025
- **Cache hit rate**: 35% → saving €18/day
- **Quality scores**: Context Precision 0.92, Faithfulness 0.89, Answer Relevancy 0.91

He clicks into the cost breakdown: the invoice audit workflow costs €0.038 per run (4 LLM calls). The document search costs €0.012 per query. The fleet anomaly response costs €0.045 per alert.

**Semantic caching in action**: Anna Schmidt asks "What's the penalty for late delivery to PharmaCorp?" at 9 AM. Cost: €0.012, latency: 800ms. Her colleague Stefan asks the same question at 9:15 AM. Redis finds a 97% similar cached query → returns the cached answer in 2ms. Cost: €0.00.

**Quality gate in CI/CD**: A developer pushes a PR that changes the RAG retrieval logic. CI runs the quality suite against 50 test queries. Context Precision drops from 0.92 to 0.78. PR blocked. The developer sees: "Quality gate failed: context_precision 0.78 < threshold 0.80."

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Langfuse observability | Dashboard: cost per query, per agent, per day | AI becomes a managed line item, not a mystery expense |
| Semantic caching (Redis) | Same question twice → instant answer, zero cost | 35% cost reduction without any quality loss |
| LLM-as-Judge scoring | Quality scores on a dashboard: 0.92 precision | Prove to auditors that AI accuracy is tracked and maintained |
| CI quality gates | PRs blocked when AI quality drops | Bad code can't silently break AI accuracy |
| Cost per query tracking | "Invoice audit: €0.038 per run" | CFO can calculate ROI vs manual process (€45/hour clerk) |

## Architecture

```
Every LLM Call → Langfuse Callback Handler
  → Trace: { prompt, response, model, tokens, latency, cost }
    → Dashboard: cost/query, TTFT, error rate, cache hit rate

Semantic Cache Layer:
  User Query → Redis (vector similarity check)
    → Cache HIT: return cached response (0 LLM cost)
    → Cache MISS: proceed to LLM → store response in Redis

Evaluation Pipeline (CI/CD):
  Test Dataset → RAG Pipeline → LLM-as-Judge
    → Scores: Context Precision, Faithfulness, Answer Relevancy
    → Gate: PR blocked if scores drop below threshold
```

**Key design decisions**:
- Langfuse self-hosted (not LangSmith) — EU data residency, full control
- Semantic caching in Redis with configurable similarity threshold
- Automated evaluation on every PR — not just manual testing
- Cost tracking per query, per agent, per user — real FinOps

## Implementation Guide

### Prerequisites
- Phases 1-2 complete
- Langfuse running (`docker compose up langfuse`)
- Redis running
- Test dataset of 50+ question-answer pairs

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/telemetry/__init__.py` | Package init |
| `apps/api/src/telemetry/langfuse_handler.py` | Langfuse callback handler for LangGraph |
| `apps/api/src/telemetry/cost_tracker.py` | Per-query cost calculation and aggregation |
| `apps/api/src/infrastructure/llm/cache.py` | Redis semantic cache (embed query → check similarity → serve or miss) |
| `apps/api/src/api/v1/analytics.py` | GET /api/v1/analytics/costs, /usage endpoints |
| `apps/api/src/domain/telemetry.py` | TraceRecord, CostSummary, EvalScore models |
| `tests/evaluation/test_rag_quality.py` | Automated RAG evaluation (context precision, faithfulness) |
| `tests/evaluation/eval_dataset.json` | Ground truth Q&A pairs for evaluation |
| `scripts/run_evaluation.py` | CLI script to run eval suite and report scores |
| `apps/web/src/app/analytics/page.tsx` | Cost dashboard page |
| `apps/web/src/components/cost-chart.tsx` | Token cost visualization component |

### Technical Spec

**API Endpoints**:

```
GET /api/v1/analytics/costs?period=7d
  Response: { "total_cost": float, "queries": int, "avg_cost_per_query": float, "cache_hit_rate": float, "by_agent": {...} }

GET /api/v1/analytics/quality
  Response: { "context_precision": float, "faithfulness": float, "answer_relevancy": float, "last_eval": datetime }
```

**Semantic Cache**:
```python
# Query embedding → Redis vector similarity search
# Threshold: 0.95 cosine similarity = cache hit
async def get_cached_response(query: str) -> str | None:
    query_embedding = await embed(query)
    result = await redis.ft.search(
        index="cache_idx",
        query=f"*=>[KNN 1 @embedding $vec AS score]",
        query_params={"vec": query_embedding},
    )
    if result.docs and float(result.docs[0].score) > 0.95:
        return result.docs[0].response
    return None
```

**Evaluation Metrics**:
```python
# Run on every PR via CI
metrics = {
    "context_precision": 0.0,   # Are retrieved chunks relevant?
    "faithfulness": 0.0,        # Does the answer stick to the context?
    "answer_relevancy": 0.0,    # Does the answer address the question?
}
# Threshold: all metrics must be > 0.8 to pass CI gate
```

### Success Criteria
- [ ] Every LLM call appears in Langfuse with full trace (prompt, tokens, latency, cost)
- [ ] Langfuse dashboard shows cost per query breakdown by agent
- [ ] Semantic cache returns cached response for near-identical queries (>95% similarity)
- [ ] Cache hit rate > 30% on repeated query patterns
- [ ] Evaluation script runs against 50+ Q&A pairs, reports precision/faithfulness scores
- [ ] CI pipeline blocks PRs that drop evaluation scores below 0.8
- [ ] `/analytics/costs` endpoint returns accurate FinOps data

## Cost of Getting It Wrong

Semantic caching saves EUR 22/day. Serving one wrong cached answer costs EUR 3,240.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Cache bypasses RBAC** | Katrin (clearance 3) asks about termination → cached. Max (clearance 1) asks similar → 0.96 similarity → cache hit → Max sees clearance-3 answer | EUR 25,000-250,000 (RBAC violation identical to Phase 1) | HIGH if cache key doesn't include clearance |
| **Stale cache after amendment** | Contract updated, cache not invalidated (new doc ID, not new version). Finance acts on cached old rate. | EUR 500-3,240 per incident | 1-2/month |
| **Cache serves wrong client's data** | "PharmaCorp penalty" returns cached "FreshFoods penalty" at 0.95 similarity. Different rate, different clause. | EUR 486-3,240 per incident | 2-3/month at 0.95 threshold |
| **Inflated quality score** | LLM-as-Judge says 0.92. Position bias inflates by 4 points. Real: 0.88. Below CI threshold. Bad PR ships. | EUR 2,000-10,000 in accumulated wrong decisions | 1-2/year |
| **Langfuse outage** | Langfuse crashes during incident. Decisions logged without trace IDs. Compliance gap. | EUR 10,000-100,000 (regulatory exposure) | 2-4 days/year |

**The CTO line**: "The cache similarity threshold is a EUR 40,000/year decision. At 0.95, you save EUR 22/day in LLM costs and risk EUR 3,240 per false match. At 0.97, you save EUR 15/day with near-zero false matches."

### CRITICAL: Cache Must Be RBAC-Aware

The semantic cache MUST include clearance_level and department in the cache key. Without this, the cache is a universal RBAC bypass.

```python
# ❌ WRONG: Cache key based on query similarity only
cache_key = hash(query_embedding)

# ✅ RIGHT: Cache key includes RBAC context
cache_key = hash(query_embedding + user.clearance_level + sorted(user.departments))
```

**Rule**: Any query that passes through RBAC-filtered retrieval must either:
1. Include RBAC context in the cache key, OR
2. Be excluded from caching entirely (`cacheable: false`)

### Langfuse Dependency as Compliance Risk

Phase 8's audit trail links to Langfuse trace IDs. If Langfuse is down or rebuilt, those links break. Mitigation:

1. During Langfuse outage: write full prompt/response/tokens to audit log directly (not just trace ID)
2. After recovery: reconciliation job backfills Langfuse and verifies all audit entries have valid trace links
3. Compliance reports flag time windows where Langfuse was unavailable

## Architect Perspective: Cost Architecture / FinOps Deep Dive

This is the section that turns Phase 4 from "we added observability" into "we built a FinOps practice for AI." This is what a CTO asks for before approving the project budget.

### Token Budget Planning (per use case)

| Use Case | Avg Input Tokens | Avg Output Tokens | Model | Cost/Query | Daily Volume | Daily Cost |
|---|---|---|---|---|---|---|
| Document search (RAG) | 2,800 | 400 | GPT-5 mini | €0.0015 | 800 | €1.20 |
| Invoice audit (multi-agent) | 8,200 | 1,200 | GPT-5.2 | €0.031 | 50 | €1.55 |
| Fleet anomaly response | 4,500 | 600 | GPT-5 mini | €0.002 | 30 | €0.06 |
| Simple status lookups | 500 | 100 | GPT-5 nano | €0.00007 | 900 | €0.06 |
| **Semantic cache hits (free)** | 0 | 0 | cache | €0.00 | ~620 | €0.00 |
| **Total** | | | | | **~2,400** | **€2.87/day** |

Without model routing (everything on GPT-5.2): €42/day. With routing + caching: €2.87/day. **93% reduction.**

### Model Routing Economics

| Query Complexity | % of Traffic | Best Model | Cost/Query | Alternative (all GPT-5.2) | Would Cost |
|---|---|---|---|---|---|
| Simple (status, lookup) | 50% | GPT-5 nano ($0.05/$0.40 per 1M) | €0.00007 | GPT-5.2 | €0.018 |
| Medium (summary, extraction) | 35% | GPT-5 mini ($0.25/$2.00 per 1M) | €0.0015 | GPT-5.2 | €0.018 |
| Complex (legal analysis, multi-hop) | 15% | GPT-5.2 ($1.75/$14.00 per 1M) | €0.018 | GPT-5.2 | €0.018 |
| Air-gapped fallback | varies | Llama 4 Scout (local) | €0.00 | GPT-5.2 | €0.018 |

**Key insight**: 50% of queries are simple lookups that don't need GPT-5.2. Routing them to nano saves €21/day at current volume. At 10x scale (24K queries/day), that's €210/day = €76K/year. The 2026 model landscape makes routing even more impactful — the gap between nano and frontier pricing is 100x.

### Infrastructure Cost Comparison

| Component | Managed (Azure/Cloud) | Self-Hosted (Docker) | Break-Even |
|---|---|---|---|
| LLM Inference | €0.012-0.030/query | €0.00/query (after hardware) | ~500 queries/day |
| Qdrant | €99/mo (Qdrant Cloud) | €0/mo (Docker) | Immediate |
| PostgreSQL | €50/mo (Azure DB) | €0/mo (Docker) | Immediate |
| Redis | €30/mo (Azure Cache) | €0/mo (Docker) | Immediate |
| Langfuse | €59/mo (Langfuse Cloud) | €0/mo (Docker) | Immediate |
| GPU Server (air-gapped) | N/A | ~€1,250/mo amortized | N/A |
| **Total (cloud)** | **~€650/mo + LLM usage** | | |
| **Total (self-hosted)** | | **~€1,250/mo (GPU) + €0 infra** | **~2,000 queries/day** |

### Break-Even Analysis: Cloud vs Air-Gapped

```
Cloud cost:    €650/mo infra + (queries × €0.015 avg)
Self-hosted:   €1,250/mo (GPU server amortized over 3 years)

Break-even:    €1,250 - €650 = €600 / €0.015 = 40,000 queries/month
               = ~1,300 queries/day

Below 1,300 queries/day: cloud is cheaper.
Above 1,300 queries/day: self-hosted pays for itself.
LogiCore Transport today: ~2,400 queries/day → self-hosted saves €290/month.
At 10x scale: self-hosted saves €5,350/month.
```

### The CTO Spreadsheet

What to present to the CFO:

| Line Item | Monthly | Annual | Notes |
|---|---|---|---|
| Cloud LLM (routed, 2026 pricing) | €86 | €1,032 | 93% less than unrouted GPT-5.2 |
| Infrastructure (self-hosted) | €0 | €0 | All in Docker Compose |
| GPU server (if air-gapped) | €1,250 | €15,000 | Amortized 3-year lease |
| Engineering (this project) | — | — | One-time build cost |
| **Total (cloud mode)** | **€86** | **€1,032** | |
| **Total (air-gapped mode)** | **€1,250** | **€15,000** | Zero per-query cost |

**ROI**: Manual invoice audit costs €45/hour × 3 hours × 50 audits/month = €6,750/month. Automated: €1.55/day × 30 = €46.50/month. **ROI: 145x on invoice audit alone.**

## Decision Framework: Model Routing Rules

Routing is the single highest-leverage FinOps decision. The goal: route every query to the **cheapest model that produces an acceptable answer**.

### Decision Tree

```
Incoming query
  │
  ├── Is this a lookup, classification, or yes/no? (<500 tokens, no reasoning)
  │     └── GPT-5 nano ($0.05/$0.40 per 1M tokens)
  │
  ├── Is this a summary, RAG answer generation, or data extraction? (medium complexity)
  │     └── GPT-5 mini ($0.25/$2.00 per 1M tokens)
  │
  ├── Is this multi-hop reasoning, legal analysis, or complex synthesis?
  │     └── GPT-5.2 ($1.75/$14.00 per 1M tokens)
  │
  └── Is the environment air-gapped or is cloud unavailable?
        └── Llama 4 Scout (local, $0.00)
```

### Classification Implementation

The router itself uses GPT-5 nano — a 50-token classification call costs ~$0.000025. Negligible overhead.

```python
# Classifier prompt (run on GPT-5 nano)
"Classify this query as SIMPLE, MEDIUM, or COMPLEX. Reply with one word only."
```

### Cost Savings: Routing vs Always-GPT-5.2

| Scenario | Daily Cost (2,400 queries) | Monthly | Annual |
|---|---|---|---|
| Everything on GPT-5.2 (no routing) | €42.00 | €1,260 | €15,120 |
| Routed (nano + mini + 5.2) | €2.87 | €86 | €1,032 |
| Routed + semantic caching (35% hit rate) | €1.87 | €56 | €672 |
| **Savings (routing + caching vs unrouted)** | **€40.13/day** | **€1,204** | **€14,448** |

At 10x scale (24K queries/day), routing + caching saves **€144K/year** vs naive GPT-5.2 usage.

### When to Override the Router

- **User explicitly requests high-quality mode** → force GPT-5.2
- **Compliance-critical output** (legal, financial reporting) → GPT-5.2 minimum, consider Claude Opus 4.6
- **Router confidence < 0.7** → escalate one tier up (nano → mini, mini → 5.2)

### Semantic Caching Strategy

#### When NOT to Cache

Not all responses should be cached. Serving stale or inappropriate cached content is worse than the cost of a fresh LLM call.

- **Volatile data**: queries about real-time status (shipment tracking, live inventory counts) — data changes minute-by-minute
- **Personalized responses**: answers that depend on the user's RBAC role, permissions, or personal context — cached response from an admin shouldn't be served to a viewer
- **Compliance-sensitive queries**: audit trails require provenance per-query; serving a cached response breaks the "this answer was generated for this specific request" chain
- **Time-sensitive**: "What's the deadline for X?" — deadlines change, cached answers become dangerous
- **Write-adjacent queries**: "Update the status of shipment X" — these trigger side effects, caching the response doesn't make sense

**Implementation**: tag queries with `cacheable: bool` in the router. Default to `true`, explicitly set `false` for the above categories.

#### Cache Invalidation Strategy

Stale cache is silent technical debt. Define explicit invalidation triggers.

| Trigger | Action | TTL |
|---|---|---|
| Document re-ingested (new version uploaded) | Invalidate all cache entries whose source chunks came from that document | Immediate |
| Embedding model changed | Flush entire cache (similarity scores no longer comparable) | Immediate |
| Scheduled TTL expiry | All cache entries expire after configurable window | Default: 24 hours |
| Quality score drift detected | Invalidate cache entries from the affected time window | On drift alert |
| Manual flush (ops) | Full or partial cache clear via admin endpoint | On demand |

**Staleness detection**: when serving a cached response, check if any source document has been re-ingested since the cache entry was created. If yes, treat as cache miss and regenerate.

```python
async def get_cached_response(query: str, source_doc_ids: list[str]) -> str | None:
    cached = await redis_similarity_search(query, threshold=0.95)
    if cached and not await docs_updated_since(source_doc_ids, cached.created_at):
        return cached.response
    return None  # cache miss — stale or not found
```

## LinkedIn Post Template

### Hook
"If you can't trace exactly WHY your LLM gave a specific answer, you have a liability, not a product."

### Body
We reduced our AI API costs by 40% last week. Not by switching models. Not by prompt engineering. By adding two things every enterprise AI system needs:

1. Semantic Caching (Redis): Same question twice = served from cache in milliseconds. Zero LLM cost. Our cache hit rate: 35%.

2. LLM-as-Judge Evaluation: Every PR runs automated quality checks. Context Precision, Faithfulness, Answer Relevancy — scored against a ground truth dataset. Drops below 0.8? PR blocked.

The Langfuse dashboard is the real hero. Every query traced: which chunks were retrieved, which model version answered, how many tokens, exact cost in euros. The CFO can finally see AI as a line item, not a mystery.

Stop treating LLMs like magic. Start treating them like enterprise microservices with SLAs.

### Visual
Langfuse dashboard screenshot: trace waterfall showing RAG → LLM → response with per-step timing and cost. Sidebar showing cache hit rate.

### CTA
"What's your current LLM observability setup? Are you tracking cost per query, or still flying blind?"

## Key Metrics to Screenshot
- Langfuse trace waterfall (multi-agent execution)
- Cost dashboard: daily/weekly spend, cost per query, by-agent breakdown
- Cache hit rate over time (Redis)
- Evaluation scores table: precision, faithfulness, relevancy
- Before/after cost comparison (with and without semantic caching)
