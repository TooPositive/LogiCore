# ADR-005: Cross-Encoder Re-Ranking — Architecture Proven, NOT Enabled at 12-Doc Scale

## Status
Accepted (architecture); **NOT RECOMMENDED for current corpus** (benchmarked)

## Context
Phase 2 live benchmarks (52 queries, 12 docs, Azure OpenAI text-embedding-3-small) show dense-only MRR=0.885. The baseline is already strong — the correct document is at rank 1 for 88.5% of queries. Re-ranking addresses a different problem: when initial retrieval returns false positives in top positions. At 12 documents, this doesn't happen often enough for re-ranking to help.

**Benchmark result (52 queries, local cross-encoder):**
- NoOp (no re-ranking): MRR=0.885
- Local cross-encoder: MRR=0.538 (**-39.2% — re-ranking HURTS**)
- Only category helped: exact_code (MRR +0.240)
- Categories destroyed: German (1.000→0.000), typo (1.000→0.000), synonym (1.000→0.500)
- Root cause: MS MARCO English-only model can't score German/typo queries; short documents (~200 chars) give the cross-encoder insufficient signal to distinguish relevant from irrelevant.

## Decision
**Architecture: built and tested. Enablement: deferred until corpus reaches switching conditions.**

| Component | Role | Status |
|-----------|------|--------|
| **CohereReranker** (primary) | Cloud cross-encoder via Cohere API | Implemented, not benchmarked (no API key). Use multilingual model when enabled. |
| **LocalCrossEncoderReranker** | `cross-encoder/ms-marco-MiniLM-L-12-v2` | Implemented, **benchmarked: HURTS by -39.2% MRR at 12-doc scale.** |
| **CircuitBreakerReranker** | 3 failures → trip → fallback. 60s recovery. | Implemented, 42 tests including all state transitions. |
| **NoOpReranker** | Pass-through baseline | Implemented, used as benchmark control. |

All rerankers implement `BaseReranker` ABC. Composable — `CircuitBreakerReranker` wraps any primary/fallback pair.

## Why Re-Ranking Hurts at Small Scale

| Root Cause | Impact | Fix |
|------------|--------|-----|
| Initial MRR already 0.885 | Re-ranking reshuffles correct rankings | Only enable when precision@1 < 0.80 |
| MS MARCO is English-only | German queries (MRR 1.000→0.000) and typos (1.000→0.000) destroyed | Use multilingual cross-encoder (Cohere, multilingual MiniLM) |
| Short documents (~200 chars) | Cross-encoder can't distinguish relevance from noise | Enable when documents >1000 chars with multiple chunks per doc |
| 12 documents total | Every document is "close enough" in embedding space | Enable when corpus >500 docs and false positives appear in top-5 |

## Switching Conditions

| Condition | Threshold | Why |
|-----------|-----------|-----|
| Corpus size | >500 documents | More documents = more false positives in top-k |
| Document length | >1000 chars average | Cross-encoder needs sufficient text to score accurately |
| Initial precision@1 | <0.80 | Re-ranking only helps when initial ranking is wrong |
| Cross-encoder model | Multilingual (not MS MARCO English) | German queries are critical for LogiCore workforce |
| Cost justification | EUR 100/month (Cohere) only when retrieval errors cause >EUR 100/month in wrong decisions | Don't pay for re-ranking that makes results worse |

**When ALL conditions are met, re-run the 52-query benchmark. If MRR improves by >5%, enable.**

## Circuit Breaker States

```
CLOSED (normal) ─── Cohere failure ──> failure_count++
    │                                      │
    │                                 count >= 3?
    │                                      │
    │                                      ▼
    │                              OPEN (using fallback)
    │                                      │
    │                                 60s timeout
    │                                      │
    │                                      ▼
    │                              HALF_OPEN (probe)
    │                                      │
    │                              success? ─── yes ──> CLOSED
    │                                 │
    │                                 no ──> OPEN (restart timer)
    └──────── success ──> reset failure_count
```

## Alternatives Considered

| Alternative | Why Not (Updated with Benchmark Data) |
|-------------|-------|
| Cohere Rerank v3 (multilingual) | Best candidate for future enablement — multilingual model should handle German. Not benchmarked yet (no API key). Architecture ready. |
| Jina Reranker v2 | Comparable quality but smaller ecosystem. Less documentation. |
| Local cross-encoder only | **Benchmarked: HURTS by -39.2% MRR.** MS MARCO English model can't score German/typo queries. Not viable as standalone for multilingual corpus. |
| No re-ranking (current) | **CORRECT decision at 12-doc scale.** MRR=0.885 without re-ranking. Re-evaluate at switching conditions. |
| Qdrant's built-in re-ranking | Qdrant doesn't have cross-encoder re-ranking — only vector similarity re-scoring. |

## Confidence Threshold
Results below `confidence_threshold` (default 0.0) are filtered out. If all results are below threshold, return empty list. This prevents the system from returning irrelevant results for out-of-domain queries (e.g., "HNSW index parameters" against a logistics corpus).

## Data Residency Note
CohereReranker sends document chunks to Cohere's API for scoring. For GDPR compliance, confirm Cohere's DPA and EU data residency. For air-gapped deployments, use `LocalCrossEncoderReranker` exclusively — tag collections as "no-external-rerank" in metadata.

## Consequences
- **Architecture is production-ready** — 4 reranker implementations, circuit breaker pattern, all composable
- **Enablement is deferred** — benchmarked on 52 queries, re-ranking hurts at current scale
- `sentence-transformers` is an optional dependency (guarded import)
- Re-ranking adds 232ms per query (local cross-encoder, measured)
- All reranker parameters are configurable — model name, threshold, circuit breaker timeouts
- Switch condition is quantified: re-run benchmark when corpus >500 docs AND precision@1 <0.80
