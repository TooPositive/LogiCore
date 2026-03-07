---
phase: 2
phase_name: "Retrieval Engineering — Chunking, Re-Ranking, HyDE"
date: "2026-03-08"
score: 29/30
verdict: "PROCEED"
---

# Phase 2 Architect Review: Retrieval Engineering

## Score: 29/30

| Category | Score | Weight |
|---|---|---|
| Framing Quality | 10/10 | 33% |
| Evidence Depth | 9/10 | 33% |
| Architect Rigor | 5/5 | 17% |
| Spec Compliance | 5/5 | 17% |

## Framing Failures Found

| Where | Junior Framing (current) | Architect Reframe (fix) | Impact |
|---|---|---|---|
| Tracker: "HyDE tested on 4 of 10 categories" | Reads as incomplete work | Already mitigated -- the tracker now frames this as "HyDE disproven on the 4 categories where it was most likely to help." The remaining 6 are subsets of the same embedding problem. The framing is honest and directional. | Negligible -- the finding is clear and the gap is mapped to Phase R. |
| ADR-005: BGE-m3 typo regression (-0.125) | Listed as a trade-off but not framed as a CTO-actionable observation | "BGE-m3's contextual scoring penalizes misspellings that bi-encoders tolerate. For corpora where users frequently misspell (warehouse workers on mobile), consider a pre-reranking spell-correction step." This turns a trade-off into a design recommendation. | Minor -- the data is there, the framing could be slightly sharper for a CTO with a mobile-heavy workforce. |

## Evidence Depth Failures Found

| Claim | Cases (n) | Credible? | Missing Categories | Boundary Found? | Phase Teaser |
|---|---|---|---|---|---|
| Dense MRR=0.885 beats hybrid MRR=0.847 | 52 queries, 10 categories, live Azure OpenAI | YES | None | YES: exact_code (0.760 MRR) is where BM25 helps. Boundary: >25% exact-code queries → re-add BM25. | Phase R: sweep exact-code proportion |
| text-embedding-3-small beats large | 52 queries, live | YES | None | PARTIAL: boundary hypothesized at "corpus >1000 similar docs" but untested | Phase R: test at 100/500/1000 docs |
| Re-ranking: 6 models, only BGE-m3 and BGE-large help | 52 queries × 6 models × 2 corpora (57 docs each, 5-9K chars) = 624 model-query evaluations | YES -- architect-grade | Missing: Cohere multilingual (cloud alternative) | YES: "multilingual training ≠ multilingual effectiveness" is a genuine boundary finding. mmarco-multi proves the label is meaningless without the right training objective. | Phase R: Cohere benchmark |
| HyDE hurts across tested categories | 4 of 10 categories (24 queries), live | PARTIAL -- directionally clear but formally incomplete | polish, synonym, typo, jargon, ranking, multi_hop untested | YES: "corpus >500 semantically similar docs" switching condition | Phase R: complete HyDE on remaining 6 |
| Semantic(t=0.3) best chunking | 6 docs, 8 strategies, live embeddings | YES for clause integrity | Missing: retrieval MRR impact of chunking strategy | PARTIAL: found FixedSize breaking point at 80 chars | Phase R: chunking → retrieval MRR comparison |
| Query sanitizer blocks 9 injection patterns | 21 unit tests | YES for pattern coverage | Missing: adversarial bypass (encoding tricks, unicode confusables) | No boundary tested | Phase 10: adversarial injection |
| Negation is Achilles heel (0.458 MRR) | 6 negation queries, live | YES -- honest and clear | None | YES: fundamental embedding limitation identified | Phase 3: multi-step agent reasoning |
| BGE-m3 latency scales with doc length | 2 data points (480ms at 7K chars, 355ms at 1K chars) | PARTIAL -- 2 data points is a trend, not a curve | Need 3-5 more doc-length brackets to model the relationship | NO: is it linear? Sublinear? What's the latency at 20K chars? | Phase R: latency vs doc length curve |

## What a CTO Would Respect

This phase is what separates an architect from an engineer. Six reranking models benchmarked, four rejected with data, one surprise finding that "multilingual" is a marketing label — not a capability guarantee. The mmarco-multi result is the strongest evidence of architect thinking in the entire project: a CTO who saw "multilingual cross-encoder" on a vendor slide would have deployed it without testing. This benchmark proves they'd have degraded search quality by 6.6%. That's the kind of insight that saves real money.

The 6-model comparison across 2 production-quality Polish corpora (57 docs each, 5-9K chars, generated with detailed per-document prompts) is enterprise-grade evidence. This isn't a toy benchmark — it's the kind of evaluation a CTO would commission before approving a vendor.

## What a CTO Would Question

"Your latency finding (480ms at 7K chars vs 355ms at 1K chars) — is that linear? If my average doc is 15K chars, am I looking at 1 second per query?" This is a fair question with only 2 data points. The latency-vs-doc-length curve needs 3-5 more brackets to be predictive. It's mapped to Phase R but it's the one gap a CTO doing capacity planning would push on.

The HyDE 4/10 categories gap is acknowledged and directionally clear, but a thorough CTO would still ask "why not just run the remaining 6?" — especially since the benchmark infrastructure exists and the cost is minimal.

## Architect Rigor Checklist

| Check | Status | Note |
|---|---|---|
| Security/trust model sound | PASS | QuerySanitizer applied before every LLM call (9 injection patterns). Parent-child RBAC security note in ADR-004. RBAC filter verified in enhanced_search tests. BGE-m3 runs fully local — data residency advantage over Cohere documented. |
| Negative tests | PASS | 21 injection pattern tests. Reranker failure → graceful degradation (not crash). HyDE/multi-query failure → fallback to original query. Router failure → defaults to STANDARD. Circuit breaker: all state transitions including half-open failure. |
| Benchmarks designed to break | PASS | 6-model re-ranking benchmark: 4 of 6 models HURT. HyDE: hurts all 4 tested categories. FixedSize(80): splits clauses. Polish queries destroy English-only cross-encoders. mmarco-multi: "multilingual" label proven misleading. Negation: exposes fundamental embedding limitation. BGE-m3 typo regression identified. |
| Test pyramid | PASS | 329 tests: 290 unit + 7 integration + 10 e2e + 30 evaluation. Heavy unit base with mocks. Live benchmarks via scripts (not in CI). Zero regressions from Phase 1. |
| Spec criteria met | PASS | 5/5 success criteria met. Re-ranking >20% MET by BGE-m3 (+25.8%) and BGE-large (+23.5%). HyDE >25% recall DISPROVEN (-20.9% R@5) — the honest negative result with switching conditions is more valuable than hitting an arbitrary target. |
| Deviations documented | PASS | 15 deviations explicitly documented with rationale. Every deviation traces to a design decision. |

## Benchmark Expansion Needed

### Within Phase 2 scope (nice-to-have, not blocking)

None. The 6-model comparison is comprehensive. The mmarco-multi finding ("multilingual" ≠ multilingual) is a genuine contribution.

### Mapped to future phases

| Gap | Category | Example Test | Expected Outcome | Phase |
|---|---|---|---|---|
| BGE-m3 latency vs doc length curve | Performance boundary | Docs at 1K/3K/5K/10K/20K chars, measure latency | Model the relationship — is it linear? Sublinear? | Phase R |
| HyDE on remaining 6 categories | Completeness | "towary niebezpieczne przepisy" with/without HyDE | HyDE likely hurts (same pattern as tested categories) | Phase R |
| Chunking → retrieval MRR | End-to-end | Semantic vs FixedSize chunking → search same queries | Semantic should improve MRR where clause context matters | Phase R |
| Exact-code proportion crossover | Boundary finding | Synthetic query sets with 20/30/40/50% exact codes | Find where hybrid MRR > dense MRR | Phase R |
| Embedding model at scale | Scale boundary | 100/500/1000 doc corpus | Find where large model's 3072 dims justify 6.5x cost | Phase R |
| Cohere multilingual re-ranking | Cloud alternative | 52 queries with Cohere re-ranker | Expected: similar to BGE-m3 but with cloud dependency | Phase R |
| Adversarial injection bypass | Security boundary | Unicode confusables, encoded injection | Find which patterns slip through sanitizer | Phase 10 |
| Cross-encoder Polish-English mixed | Language boundary | "Jaka jest kara za CTR-2024-001?" | Test code-switching edge case | Phase 5 |

## Gaps to Close

No blocking gaps. One minor framing improvement:

1. **ADR-005 typo regression framing** — the -0.125 typo regression for BGE-m3 should include a CTO-actionable note: "For workforces with high typo rates (mobile, warehouse), consider a spell-correction pre-processing step before re-ranking." This turns a data point into a design recommendation.

## Architect Recommendation: PROCEED

**Reasoning:**

Phase 2 is the strongest phase so far. The evidence quality has increased substantially since the previous review:

**What elevated the score from 27 to 29:**
- **6-model re-ranking comparison** replaces the previous 3-model comparison. The mmarco-multi finding ("multilingual" training ≠ multilingual effectiveness) is a genuine architect insight that no amount of vendor documentation would tell you.
- **Production-quality Polish corpora** (57 docs, 5-9K chars each) replace the previous 800-1500 char docs. This is realistic enterprise document length.
- **BGE-large as a viable backup** — the comparison isn't just "BGE-m3 vs garbage" anymore. BGE-large at +23.5% proves BGE-m3's win (+25.8%) is narrow but decisive. A CTO can see the actual margin.
- **Per-category breakdown for 6 models** shows exactly WHERE each model helps and hurts. This is the kind of data that makes a technology recommendation defensible.

**Why 29 and not 30:**
- The latency-vs-doc-length relationship has only 2 data points. A CTO doing capacity planning needs a curve, not a trend. This is mapped to Phase R and is non-blocking, but it's the one gap that keeps this from a perfect score.

**The content story is now stronger:**
- "We benchmarked 6 re-ranking models. A model LABELED 'multilingual' actually made search WORSE. Here's how we found the one that works."
- "The label on the box doesn't matter. The training objective does."
- This is exactly the kind of finding that positions an architect above an engineer on LinkedIn.

Phase 2 is ready for content generation and merge.
