# ADR-005: Cross-Encoder Re-Ranking with Circuit Breaker

## Status
Accepted

## Context
Phase 1's hybrid search achieves 24/26 queries (92.3%) but precision@5 is 0.62 — meaning 38% of the top-5 results are wrong. Vector similarity returns "mathematically similar" results that aren't actually relevant. A shipping terms clause scores 0.91 while the actual penalty clause scores 0.88 — the user gets confident but wrong information.

In Phase 3's invoice audit, wrong retrieval means wrong rate extraction: 2.5% false negative rate at 1,000 invoices/month = EUR 40,800/year in unrecovered overcharges. Re-ranking closing precision@5 from 0.62 to 0.89 cuts that to under 0.5%.

## Decision
**Cohere Rerank v3 as primary, local cross-encoder as fallback, with circuit breaker pattern.**

| Component | Role | Cost |
|-----------|------|------|
| **CohereReranker** (primary) | Cloud cross-encoder re-ranking via Cohere API | EUR 0.001/query (~EUR 100/month at 100K queries) |
| **LocalCrossEncoderReranker** (fallback) | `cross-encoder/ms-marco-MiniLM-L-12-v2` for air-gapped mode or API outage | Free (local inference, ~15-20% lower quality) |
| **CircuitBreakerReranker** (wrapper) | 3 consecutive Cohere failures -> trip circuit -> fall to local cross-encoder. 60s recovery timeout, half-open probe. | N/A (pattern, not service) |
| **NoOpReranker** (baseline) | Pass-through for benchmark comparison | Free |

All rerankers implement `BaseReranker` ABC. Composable — `CircuitBreakerReranker` wraps any primary/fallback pair.

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| Jina Reranker v2 | Comparable quality but smaller ecosystem. Less documentation, fewer enterprise deployments. |
| Voyage Reranker | Limited language support — German is critical for LogiCore's workforce. |
| Local cross-encoder only | 15-20% lower quality on domain-specific queries. Acceptable for air-gapped deployments, not for cloud-available deployments where Cohere's quality justifies EUR 100/month. |
| No re-ranking | 38% wrong results in top-5. Not acceptable for financial decisions. |
| Qdrant's built-in re-ranking | Qdrant doesn't have cross-encoder re-ranking — only vector similarity re-scoring. |

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

## Confidence Threshold
Results below `confidence_threshold` (default 0.0) are filtered out. If all results are below threshold, return empty list. This prevents the system from returning irrelevant results for out-of-domain queries (e.g., "HNSW index parameters" against a logistics corpus).

## Data Residency Note
CohereReranker sends document chunks to Cohere's API for scoring. For GDPR compliance, confirm Cohere's DPA and EU data residency. For air-gapped deployments, use `LocalCrossEncoderReranker` exclusively — tag collections as "no-external-rerank" in metadata.

## Consequences
- Cohere dependency for cloud deployments (EUR 100/month, mitigated by circuit breaker + local fallback)
- `sentence-transformers` is an optional dependency (guarded import) — cloud-only deployments don't need it installed
- Re-ranking adds 50-150ms per query (Cohere) or 100-300ms (local cross-encoder)
- ROI: EUR 100/month cost vs EUR 3,100/month saved from avoided retrieval errors (31x)
- All reranker parameters are configurable — model name, threshold, circuit breaker timeouts
