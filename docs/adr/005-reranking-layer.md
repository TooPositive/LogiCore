# ADR-005: Cross-Encoder Re-Ranking — Model Selection and Enablement Conditions

## Status
Accepted. **BGE-reranker-v2-m3 is the recommended production reranker.** TinyBERT for air-gapped English-only deployments only.

## Context
Phase 2 benchmarked **6 cross-encoder reranking models** across 2 production-quality Polish logistics corpora (52 queries, Azure OpenAI text-embedding-3-small):

| Model | Params | Homogeneous (57 contracts, avg 5.4K chars) | Diverse (57 docs, 8 types, avg 7.2K chars) | Latency | Verdict |
|---|---|---|---|---|---|
| NoOp (baseline) | — | MRR 0.415 | MRR 0.361 | 0ms | Baseline |
| TinyBERT (2-layer) | 14.5M | MRR 0.308 (**-25.8%**) | MRR 0.268 (**-25.5%**) | 28-72ms | NEVER USE |
| ms-marco-L12 (12-layer) | 33M | MRR 0.351 (**-15.4%**) | MRR 0.350 (-3.0%) | 74-105ms | NEVER USE |
| mmarco-mMiniLM (multilingual) | 118M | MRR 0.333 (**-19.8%**) | MRR 0.337 (**-6.6%**) | 62-105ms | NEVER USE |
| BGE-reranker-base | 278M | MRR 0.457 (+10.1%) | MRR 0.362 (+0.3%) | 144-181ms | NEUTRAL |
| BGE-reranker-large | 560M | MRR 0.456 (+9.9%) | MRR **0.446 (+23.5%)** | 468-500ms | STRONG 2nd |
| **BGE-reranker-v2-m3** | 568M | MRR **0.459 (+10.6%)** | MRR **0.454 (+25.8%)** | 424-480ms | **BEST** |

**Architect findings**:
1. **Only 2 of 6 models meaningfully improve retrieval**: BGE-m3 (+25.8%) and BGE-large (+23.5%) on diverse corpus.
2. **"Multilingual" training ≠ multilingual effectiveness.** mmarco-mMiniLM was trained on translated ms-marco data, yet HURTS by -6.6%. The label "multilingual" is misleading — it means the training data was translated, not that the model understands cross-lingual semantics.
3. **BGE-m3's dedicated m3 objective** (multi-lingual, multi-functionality, multi-granularity) is what makes the difference. It's purpose-built for cross-lingual retrieval, not retrofitted.
4. **BGE-base (278M) is neutral on diverse** (+0.3%) — it helps on jargon/multi_hop but hurts exact_code/Polish/synonym/typo. Wastes 144ms of compute for near-zero benefit.
5. **BGE-large (560M) is a viable backup** — similar MRR to m3 but slightly worse on exact_code and negation. Choose m3 unless you need BGE-large's stronger ranking (+0.312 vs +0.250) or multi_hop (+0.188 vs +0.021).

## Decision
**BGE-reranker-v2-m3 is the default reranker.** TinyBERT is the air-gapped fallback for English-only deployments.

| Component | Role | Status |
|---|---|---|
| **LocalCrossEncoderReranker (BGE-m3)** | `BAAI/bge-reranker-v2-m3` — multilingual, 568M | **+25.8% MRR on diverse corpus.** Default for all deployments with Polish queries. |
| **LocalCrossEncoderReranker (TinyBERT)** | `cross-encoder/ms-marco-TinyBERT-L-2-v2` — 14.5M | Air-gapped/on-prem only. English-only. Fastest (45ms). Phase 6 candidate. |
| **LocalCrossEncoderReranker (ms-marco)** | `cross-encoder/ms-marco-MiniLM-L-12-v2` — 33M | **Deprecated.** Worse than TinyBERT (slower, same English-only failures). No use case. |
| **CohereReranker** | Cloud cross-encoder via Cohere API | Implemented, not benchmarked. Cloud alternative to BGE-m3 when latency budget is tight. |
| **CircuitBreakerReranker** | 3 failures → trip → NoOp fallback. 60s recovery. | Production-ready, 42 tests. |
| **NoOpReranker** | Pass-through baseline | Fallback when circuit breaker trips. |

All rerankers implement `BaseReranker` ABC. Composable — `CircuitBreakerReranker` wraps any primary/fallback pair.

## Why English-Only Models Fail

| Category | NoOp | TinyBERT | ms-marco | BGE-m3 | Why |
|---|---|---|---|---|---|
| polish | 0.146 | **0.000** | 0.050 | 0.125 | English models score Polish as irrelevant |
| typo | 0.500 | **0.000** | **0.000** | 0.375 | "pharamcorp" ≠ "PharmaCorp" for English tokenizer |
| synonym | 0.750 | **0.250** | **0.500** | 0.750 | "letting go staff" ≠ "termination" |
| natural_language | 0.875 | **0.750** | 1.000 | 1.000 | TinyBERT too small for semantic nuance |

**For a Polish company, English-only models are disqualifying.** A reranker that breaks Polish queries and all typo tolerance is worse than no reranker at all.

## Why BGE-m3 Works (Per-Category on Diverse Corpus)

| Category | NoOp | BGE-m3 | Delta | Why |
|---|---|---|---|---|
| jargon | 0.208 | 0.750 | **+0.542** | Cross-encoder understands domain terminology in context |
| ranking | 0.000 | 0.250 | **+0.250** | Better at comparative relevance scoring |
| natural_language | 0.875 | 1.000 | **+0.125** | Filters out topically adjacent noise |
| negation | 0.000 | 0.111 | **+0.111** | Cross-encoder understands "without"/"non-" |
| exact_code | 0.417 | 0.500 | +0.083 | Pushes exact matches above noise |
| multi_hop | 0.312 | 0.333 | +0.021 | Marginal multi-doc relevance improvement |
| synonym | 0.750 | 0.750 | 0.000 | Neutral — embeddings already handle synonyms |
| polish | 0.146 | 0.125 | -0.021 | Marginal loss on Polish language queries |
| vague | 0.125 | 0.097 | -0.028 | Slight loss on broad queries |
| typo | 0.500 | 0.375 | **-0.125** | Typo handling worsened — cross-encoder penalizes misspellings |

**7 of 10 categories improved or neutral.** Total: 0.361 → 0.454 MRR (+25.8%). Biggest wins: jargon (+0.542), ranking (+0.250). The typo regression (-0.125) is a trade-off — BGE-m3's contextual scoring penalizes misspellings that bi-encoders tolerate.

## TinyBERT: The Air-Gapped Story (Phase 6)

TinyBERT is the smallest viable cross-encoder reranker:
- **14.5M params** — runs on CPU, no GPU needed
- **45ms latency** — 14x faster than BGE-m3
- **On-premise** — no data leaves the network boundary
- **Use case**: English-only corpus behind air-gap (Phase 6), healthcare/defense contexts where data sovereignty trumps quality

The trade-off is explicit: TinyBERT gives you **data sovereignty at the cost of -26% MRR on multilingual queries**. For an English-only corpus, the quality gap narrows (same English categories perform comparably to ms-marco). For LogiCore's Polish workforce, BGE-m3 is mandatory.

**Architecture**: Same `LocalCrossEncoderReranker` class, different `model_name` — toggled via config: `RERANKER_MODEL=cross-encoder/ms-marco-TinyBERT-L-2-v2` vs `RERANKER_MODEL=BAAI/bge-reranker-v2-m3`.

## Enablement Conditions

| Condition | Threshold | Why |
|---|---|---|
| Document length | >800 chars avg | Short docs (<200 chars) give cross-encoders insufficient signal |
| Cross-encoder model | BGE-m3 (multilingual) for Polish; TinyBERT for English-only air-gapped | Language match is non-negotiable |
| Latency budget | ~620ms at 7K avg docs | BGE-m3 latency scales with doc length; TinyBERT ~45ms |
| Corpus size | >20 docs | Below 20 docs, initial retrieval is already precise enough |

## Benchmark Methodology

- **Corpora**:
  - Homogeneous: 12 original + 45 LLM-generated Polish transport contracts (all same type), avg 5,419 chars
  - Diverse: 12 original + 45 LLM-generated Polish logistics docs across 8 types (safety, HR, tech, incidents, meetings, SOPs, compliance, vendor), avg 7,218 chars
  - All generated via Azure OpenAI gpt-5-mini with detailed per-doc prompts
- **Queries**: 52 ground truth across 10 categories
- **Retrieval**: Dense-only (text-embedding-3-small), top-20 candidates, re-ranked to top-5
- **Reproducible**: `scripts/generate_corpus.py` + `scripts/generate_homogeneous_corpus.py` + `scripts/benchmark_reranking_v2.py --no-ollama`

## Circuit Breaker States

```
CLOSED (normal) ─── failure ──> failure_count++
    │                               │
    │                          count >= 3?
    │                               │
    │                               ▼
    │                       OPEN (using NoOp fallback)
    │                               │
    │                          60s timeout
    │                               │
    │                               ▼
    │                       HALF_OPEN (probe)
    │                               │
    │                       success? ─── yes ──> CLOSED
    │                          │
    │                          no ──> OPEN (restart timer)
    └──────── success ──> reset failure_count
```

## Alternatives Considered

| Alternative | Verdict | Evidence |
|---|---|---|
| TinyBERT (14.5M) | **Air-gapped only.** Fastest (28ms), smallest, but English-only → -25.5% MRR on diverse corpus. | Benchmark: 0.268 MRR on diverse, 0.308 on homogeneous |
| ms-marco-L12 (33M) | **Deprecated.** Slower than TinyBERT, same English-only failures. No use case over TinyBERT. | Benchmark: 0.350 MRR diverse, 0.351 homogeneous |
| mmarco-mMiniLM (118M) | **Rejected despite "multilingual" label.** Trained on translated ms-marco but still HURTS (-6.6%). Proves that multilingual training data ≠ multilingual understanding. | Benchmark: 0.337 MRR diverse, 0.333 homogeneous |
| BGE-base (278M) | **Neutral.** +0.3% MRR on diverse — not worth 144ms compute. Helps jargon but hurts exact_code/Polish. | Benchmark: 0.362 MRR diverse, 0.457 homogeneous |
| BGE-large (560M) | **Strong backup.** +23.5% MRR on diverse. Better at ranking/multi_hop, slightly worse than m3 on exact_code/negation. | Benchmark: 0.446 MRR diverse, 0.456 homogeneous |
| BGE-m3 (568M) | **Selected.** Best overall. +25.8% MRR on diverse. Purpose-built multilingual (m3 = multi-lingual, multi-functionality, multi-granularity). | Benchmark: 0.454 MRR diverse, 0.459 homogeneous |
| Cohere Rerank v3 | Not benchmarked. Cloud alternative — expected similar to BGE-m3 (multilingual). Adds cloud dependency. | Architecture ready. |
| No re-ranking | Wrong for production corpora with >20 diverse docs. Baseline MRR drops to ~0.36-0.42 with production-length docs. | Benchmark: NoOp is 26% behind BGE-m3 on diverse corpus |

## Data Residency Note
BGE-m3 runs **fully local** — no data leaves the infrastructure. This is architecturally superior to Cohere for GDPR compliance. For air-gapped deployments (Phase 6), switch to TinyBERT via config toggle.

## Consequences
- BGE-m3 adds ~620ms per query at 7K avg doc length (scales with document size; 355ms at 1K docs)
- `sentence-transformers` is a required dependency when re-ranking is enabled
- Model is 568M params — needs ~2GB disk, ~1GB RAM during inference
- Circuit breaker protects against model loading failures
- Same abstraction pattern as embedding provider: `RERANKER_MODEL` config toggle
- TinyBERT benchmarked and documented for Phase 6 air-gapped deployment
