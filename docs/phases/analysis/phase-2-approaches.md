---
phase: 2
date: "2026-03-07"
selected: "A"
---

# Phase 2 Implementation Approaches

## Approach A: Full-Stack Retrieval (All Components)

**Summary**: Implement everything in the spec — semantic chunking, parent-child chunking, cross-encoder re-ranking (Cohere + local fallback), HyDE query transform, query router (GPT-5 nano), embedding model benchmark (4 models), circuit breaker, confidence thresholds. The complete retrieval engineering stack.

**Pros**:
- Delivers the full architect story: "we tested everything, here's what works and what doesn't"
- Query router + HyDE demonstrate cost-aware pipeline design (EUR 564/month savings from routing alone)
- Parent-child chunking sets up Phase 3 (agents need complete clause context)
- Circuit breaker + fallback proves resilience thinking (Phase 7 builds on this)
- Maximum content surface area for LinkedIn/Medium posts

**Cons**:
- Largest scope (~12 dev-days per analysis)
- HyDE + query router add complexity that may not be justified at 12-doc corpus scale
- Risk of shallow benchmarks across too many components (thin n-sizes)
- More attack surface to secure (HyDE prompt injection, parent-child RBAC, Cohere data exfiltration)

**Effort**: L — ~12 dev-days
**Risk**: Scope creep. Thin benchmarks that don't hold up to CTO scrutiny.

## Approach B: Core Quality + Honest Benchmarks (Recommended)

**Summary**: Focus on the three highest-ROI components: (1) semantic chunking with parent-child, (2) cross-encoder re-ranking with circuit breaker, (3) expanded embedding benchmark. Defer HyDE and query router to Phase 4/later. Deep benchmarks on fewer components — 50+ queries, before/after on each component, honest about what doesn't help.

**Pros**:
- Deep evidence on fewer claims — CTO-credible benchmarks (50+ queries, not thin n=5)
- Semantic chunking + re-ranking deliver 80% of the value (precision@5 0.62 -> 0.85+)
- Simpler attack surface (no HyDE injection risk, no router manipulation)
- Parent-child RBAC is properly designed and tested (P0 security)
- Circuit breaker on re-ranker proves resilience thinking without over-engineering
- Leaves HyDE as a clear Phase 4 "query understanding" story — better content separation

**Cons**:
- No HyDE demonstration (vague queries stay weaker)
- No query routing cost optimization (all queries go through same pipeline)
- Fewer "wow" components for content — but deeper evidence on each

**Effort**: M — ~8 dev-days
**Risk**: Lower. Main risk is parent-child RBAC complexity.

## Approach C: Benchmark-First, Build What's Proven

**Summary**: Start with pure benchmarks — expand the test query set to 50+, measure current Phase 1 retrieval exhaustively, THEN build only what the benchmarks prove is needed. If semantic chunking doesn't improve precision on 50 queries, don't build it. If re-ranking adds <10% precision, skip it. Let the data decide.

**Pros**:
- Most intellectually honest — "we only built what the data justified"
- Avoids building components that might not help at current corpus scale
- Strongest architect framing: "here's what we tested, here's why we didn't build X"
- Least code, most analysis

**Cons**:
- May end up building very little if benchmarks don't show improvement on 12 docs
- Risk of "analysis paralysis" — Phase 2 becomes a benchmarking exercise with no deliverables
- Hard to demonstrate re-ranking value on a 12-doc corpus (limited candidate pool)
- Less impressive portfolio piece — "we tested and decided not to build" is a harder sell

**Effort**: S-M — ~5-8 dev-days (depends on what benchmarks justify)
**Risk**: Inconclusive benchmarks at small corpus scale. Phase 2 delivers analysis without infrastructure.

## Recommendation

**Approach B (Core Quality + Honest Benchmarks).**

Rationale:
1. **Depth over breadth.** Phase 1 proved that honest benchmarks with architect framing are what CTOs respect. 26 queries across 7 categories was credible. Spreading thin across 6 components with n=5 each is not.
2. **Semantic chunking + re-ranking deliver 80% of value.** The analysis shows re-ranking alone is worth EUR 37,200/year in avoided retrieval errors. HyDE adds value only for the 20% of queries that are vague — defer it.
3. **Security-first.** Parent-child RBAC is a P0 gap. Building it properly with deep testing takes priority over adding HyDE.
4. **Content separation.** HyDE + query routing is a natural "query understanding" story for Phase 4 content. Cramming it into Phase 2 dilutes both stories.
5. **Approach C is too risky at 12 docs.** Benchmarks on a 12-doc corpus may show marginal improvement, leading to "we didn't build anything" — valid architecturally but weak for portfolio.

Defer to Phase 4/later: HyDE, query router, multi-query expansion, query decomposition.

## Selected: Approach A (Full-Stack Retrieval)

User chose full scope with these constraints:
- **Step by step**: one tracker task at a time, commit after each, update tracker with benchmarks before moving to next
- **Quality > speed**: deep benchmarks on each component, don't rush to check boxes
- **Architecture constraint**: all retrieval components configurable via config/parameters, not hardcoded to logistics. Chunking strategy, re-ranking model, embedding model, query router thresholds — all from config. Corpus and benchmark queries are domain-specific, but the retrieval pipeline works for any domain with different config.
- **Resumable**: stop at natural boundaries (after a task group), update all docs, commit. Resume with `/next-phase`.
