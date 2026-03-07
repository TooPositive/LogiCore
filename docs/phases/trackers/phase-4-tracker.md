# Phase 4 Tracker: Trust Layer — LLMOps, Observability & Evaluation

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-4-trust-layer.md`
**Depends on**: Phases 1-2

## Implementation Tasks

- [ ] `apps/api/src/telemetry/__init__.py`
- [ ] `apps/api/src/telemetry/langfuse_handler.py` — Langfuse callback handler for LangGraph
- [ ] `apps/api/src/telemetry/cost_tracker.py` — per-query cost calculation
- [ ] `apps/api/src/infrastructure/llm/cache.py` — Redis semantic cache
- [ ] `apps/api/src/api/v1/analytics.py` — GET /costs, /usage endpoints
- [ ] `apps/api/src/domain/telemetry.py` — TraceRecord, CostSummary, EvalScore models
- [ ] `tests/evaluation/test_rag_quality.py` — automated RAG eval
- [ ] `tests/evaluation/eval_dataset.json` — 50+ ground truth Q&A pairs
- [ ] `scripts/run_evaluation.py` — CLI eval runner
- [ ] `apps/web/src/app/analytics/page.tsx` — cost dashboard
- [ ] `apps/web/src/components/cost-chart.tsx` — token cost visualization

## Success Criteria

- [ ] Every LLM call appears in Langfuse with full trace
- [ ] Langfuse dashboard shows cost per query by agent
- [ ] Semantic cache returns cached response for >95% similarity queries
- [ ] Cache hit rate > 30% on repeated patterns
- [ ] Eval script runs 50+ Q&A pairs, reports scores
- [ ] CI blocks PRs that drop scores below 0.8
- [ ] `/analytics/costs` returns accurate FinOps data

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Cache similarity threshold | 0.95 cosine | | |
| Eval metrics | precision, faithfulness, relevancy | | |
| CI quality gate threshold | 0.8 | | |
| Cache backend | Redis vector search | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Test Results

| Test | Status | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Daily AI spend (before caching) | | EUR/day |
| Daily AI spend (after caching) | | EUR/day |
| Cache hit rate | | % |
| Avg cost per query (search) | | EUR |
| Avg cost per query (audit) | | EUR |
| Avg cost per query (fleet) | | EUR |
| Context precision score | | 0-1 |
| Faithfulness score | | 0-1 |
| Answer relevancy score | | 0-1 |
| Cache response latency | | ms (vs LLM latency) |
| Cost reduction % | | with vs without caching |
| Token budget: search queries | | avg input + output tokens |
| Token budget: audit workflow | | avg total tokens |
| Model routing savings | | EUR/day from routing simple→mini |

## Screenshots Captured

- [ ] Langfuse trace waterfall (multi-agent)
- [ ] Cost dashboard (daily/weekly)
- [ ] Cache hit rate over time
- [ ] Eval scores table
- [ ] Before/after cost comparison
- [ ] FinOps CTO spreadsheet (from Architect Perspective section)

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
