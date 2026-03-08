---
phase: 5
date: "2026-03-08"
selected: A
---

# Phase 5 Implementation Approaches

## Context

Phase 5 has three pillars: (1) Judge Bias Mitigation, (2) Drift Detection, (3) Prompt Caching Optimization. The analysis identified that Phase 4's mock judge + same-family generator/judge setup is the highest-risk gap. All approaches implement the spec; they differ in depth and ordering.

### What Already Exists (Phase 4)
- `tests/evaluation/llm_judge.py` — mock judge (word-overlap heuristics), 3 metrics
- `tests/evaluation/ground_truth.py` — 52 queries, 10 categories, 12 docs
- `tests/evaluation/metrics.py` — P@k, R@k, MRR (retrieval-level, not answer-level)
- `apps/api/src/domain/telemetry.py` — EvalScore, TraceRecord, CacheEntry, ModelRoute
- `apps/api/src/telemetry/cost_tracker.py` — FinOps with ModelPricing table
- `apps/api/src/telemetry/langfuse_handler.py` — non-blocking tracing + fallback

---

## Approach A: Full Spec — All 3 Pillars in Parallel

**Summary**: Build judge bias mitigation, drift detection, and prompt caching as three independent modules. Each gets its own test suite. Full spec implementation.

**Pros**:
- Complete Phase 5 spec coverage
- Each pillar is independently testable
- Prompt caching adds FinOps story (extends Phase 4 cost narrative)

**Cons**:
- Largest scope — prompt caching is architecturally less interesting than judge rigor
- Risk of thin benchmarks across all 3 (spread too wide)
- Prompt caching's "60% hit rate" claim conflicts with RBAC partitioning reality (analysis says 15-25%)

**Effort**: L (3-4 sessions)
**Risk**: Shallow depth on all three pillars — reviewer catches thin evidence

### Implementation Order
1. Judge bias (pairwise + position + verbosity + self-preference)
2. Drift detection (model registry + regression suite + alerting)
3. Prompt caching (static-first restructuring + cache hit tracking)

---

## Approach B: Judge Rigor Deep + Drift Detection, Defer Prompt Caching

**Summary**: Go deep on the "who watches the watchmen" story — judge bias mitigation and drift detection with thick benchmarks. Prompt caching becomes a lightweight appendix (structure + metrics tracking only, no optimization benchmark).

**Pros**:
- Deepest architect story: "your quality metrics are lying to you"
- Thick benchmarks on position bias, verbosity bias, self-preference, calibration
- Drift detection with model registry + regression suite is the CTO pain point
- Honest about prompt caching vs RBAC partitioning tension

**Cons**:
- Prompt caching gets less attention (structure + tracking, not full optimization)
- Slightly less FinOps content for Medium article

**Effort**: M-L (2-3 sessions)
**Risk**: Low — focused scope, deep evidence

### Implementation Order
1. Judge config (model family separation, bias settings)
2. Quality pipeline (pairwise comparison, position bias detection)
3. Human calibration baseline (50 golden set, Spearman correlation)
4. Drift detector (model registry, version tracking, regression suite, alerting)
5. Prompt optimizer (static-first structure, cache hit tracking — lightweight)

---

## Approach C: Judge Framework + Benchmarks Only

**Summary**: Build only the judge bias mitigation framework with deep benchmarks. Drift detection and prompt caching are stubbed with interfaces but not fully implemented. Architect story is 100% about judge reliability.

**Pros**:
- Maximum depth on the single most important story
- Can benchmark position bias rates, verbosity bias, self-preference across model families
- Simplest implementation, clearest narrative

**Cons**:
- Incomplete spec coverage (drift + caching are stubs)
- Misses the "silent model update" CTO scenario
- Less content material for LinkedIn/Medium

**Effort**: M (1-2 sessions)
**Risk**: Reviewer flags incomplete spec coverage. Missing drift detection leaves a gap in the Phase 4→5 cascade story.

---

## Recommendation

**Approach B** — Go deep on judge rigor + drift detection, lightweight prompt caching.

Reasoning:
1. The architect story is "your quality metrics are lying" — that requires THICK evidence on judge bias, not a surface pass across 3 topics.
2. Drift detection is the CTO pain point ("Azure silently updates, nobody notices for 7 days") — this must be robust.
3. Prompt caching's spec claim of 60% hit rate is unrealistic with RBAC partitioning. Better to be honest about the tension (15-25% realistic) and build the tracking infrastructure than to chase a misleading benchmark.
4. Phase 4's review already flagged "mock judge" as deferred risk — Phase 5 must close that gap convincingly.

The key deliverables:
- Pairwise scoring with position-swap agreement requirement
- Verbosity bias detection (penalize longer-is-better)
- Judge != generator FAMILY enforcement (not just model)
- 50-entry human calibration baseline with Spearman correlation
- Model version registry with automatic regression triggers
- Drift alerting with configurable thresholds (green/yellow/red)
- Prompt structure optimizer with cache hit tracking (infrastructure, not benchmark)
