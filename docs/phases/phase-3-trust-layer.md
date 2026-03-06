# Phase 3: "The Trust Layer" — LLMOps, Observability & Evaluation

## Business Problem

The RAG works. The agents work. But the CFO asks: "How much does each AI query cost?" The CTO asks: "How do we know it's not hallucinating?" The compliance officer asks: "Can you prove the accuracy hasn't degraded since last month?"

Without observability, AI is a black box. Black boxes don't get deployed in enterprises.

**CTO pain**: "We can't manage what we can't measure. Give me dashboards, SLAs, and automated quality gates — or this stays a POC forever."

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
