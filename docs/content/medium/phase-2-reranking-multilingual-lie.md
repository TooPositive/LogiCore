---
title: "\"Multilingual\" Re-Ranking Is a Lie — We Benchmarked 6 Models to Prove It"
subtitle: "How a model card label almost degraded our Polish logistics search by 6.6%"
series: "LogiCore AI System — Phase 2/12"
phase: 2
date: 2026-03-08
status: draft
tags: ["RAG", "re-ranking", "cross-encoder", "multilingual", "embeddings", "retrieval", "AI architecture"]
---

# "Multilingual" Re-Ranking Is a Lie — We Benchmarked 6 Models to Prove It

## 1. The Crisis: Vector Similarity Is Lying to You

Anna, a logistics manager at LogiCore Transport, searches "what are the penalties for late PharmaCorp delivery?" The embedding model scores 5 documents as "similar." Three of them are about PharmaCorp. One is about delivery schedules. One is about penalty calculations for a completely different client. The actual penalty clause — buried in Section 8.3 of contract CTR-2024-001 — ranks fourth.

Position four means Anna never sees it. She calls legal. Legal pulls the contract manually. A 15-minute search that should have taken 15 seconds.

This is Phase 2 of a 12-phase AI system im building for a logistics company. Phase 1 proved that embeddings are mandatory and BM25 alone breaks on real human queries. Phase 2 asks: okay, embeddings work — but how do you make the RIGHT document rank first, not fourth? And how do you pick the right models when vendor labels are misleading?

Logistics is a brutal test for retrieval coz you get everything at once: Polish workers querying in their language, English contracts, alphanumeric cargo codes like CTR-2024-001, typos from warehouse workers on mobile, and regulatory documents where clause integrity matters more than keyword matching.

## 2. Why This Is Hard

Vector similarity measures distance in embedding space. Two documents can be "similar" (both about PharmaCorp contracts) without being "relevant" (only one has the penalty clause). Dense retrieval gets you into the neighborhood. It doesnt get you to the right house.

The naive fix: just add a cross-encoder re-ranker. It reads query + document together (not independently like bi-encoders) and scores actual relevance. Sounds simple. Pick one from HuggingFace, done.

Except the model choice is everything. And the labels on the model cards are unreliable.

## 3. What We Tried First (And What Broke)

Phase 1 benchmarked search modes on 26 queries across 7 categories. Hybrid (dense + BM25 with RRF fusion) scored 24/26. We recommended hybrid as the default.

Phase 2 doubled the query set to 52 across 10 categories. The conclusion reversed.

| Search Mode | MRR (26 queries) | MRR (52 queries) | Direction |
|---|---|---|---|
| Dense-only | 23/26 | **0.885** | Winner at scale |
| Hybrid (RRF) | 24/26 | 0.847 | **Loses at scale** |
| BM25-only | 16/26 | not re-tested | Still not viable |

Dense-only MRR 0.885 beats hybrid 0.847. BM25 adds noise when query diversity increases beyond exact-code lookups. The boundary: if more than ~25% of your queries are exact alphanumeric codes (like CTR-2024-001), add BM25. Otherwise, dense-only is cleaner.

The lesson is uncomfortable: benchmark conclusions are scale-dependent. The recommendation that was correct at 26 queries became wrong at 52. If you stop testing at your initial sample, you ship the wrong architecture.

## 4. The Architecture Decision: 6 Models, 4 Rejected

We benchmarked 6 cross-encoder re-ranking models on 2 production-quality Polish corpora:

- **Diverse corpus**: 57 documents across 8 types (contracts, safety protocols, HR policies, technical specs, incident reports, meeting notes, SOPs, vendor agreements), average 7,218 chars per doc
- **Homogeneous corpus**: 57 transport contracts (all same type), average 5,419 chars per doc

These arent the 800-char toy documents you see in tutorials. Production contracts run 5-9K characters. If your benchmark uses short docs, it wont predict production performance.

### The Results

| Model | Params | Diverse MRR | vs NoOp | Latency | Verdict |
|---|---|---|---|---|---|
| NoOp (no re-ranking) | — | 0.361 | baseline | 0ms | Baseline |
| TinyBERT | 14.5M | 0.268 | **-25.5%** | 28-72ms | NEVER USE |
| ms-marco-MiniLM | 33M | 0.350 | -3.0% | 74-105ms | NEVER USE |
| mmarco-mMiniLM ("multilingual") | 118M | 0.337 | **-6.6%** | 62-105ms | NEVER USE |
| BGE-reranker-base | 278M | 0.362 | +0.3% | 144-181ms | NEUTRAL |
| BGE-reranker-large | 560M | 0.446 | **+23.5%** | 468-500ms | Strong backup |
| **BGE-reranker-v2-m3** | 568M | **0.454** | **+25.8%** | 424-480ms | **BEST** |

4 of 6 models either hurt or add nothing. Only 2 actually improve retrieval.

### The "Multilingual" Lie

The most important finding isnt which model won. Its which model LIED.

`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` is trained on translated ms-marco data. Its model card says "multilingual." A CTO reading vendor documentation would see "multilingual cross-encoder" and deploy it for a Polish workforce without testing.

It would have degraded search quality by 6.6%.

"Multilingual" means the training data was translated from English to other languages via machine translation. It does NOT mean the model understands cross-lingual semantics. Translation of training data ≠ multilingual understanding. The model learned English retrieval patterns on translated text, not actual cross-lingual relevance.

BGE-m3 works coz its training objective is fundamentally different. The "m3" stands for multi-lingual, multi-functionality, multi-granularity — its explicitly designed to learn cross-lingual document relevance, not just replay English patterns in other languages.

### Per-Category Breakdown: Where Each Model Breaks

| Category | NoOp | TinyBERT | mmarco-multi | BGE-m3 |
|---|---|---|---|---|
| polish | 0.146 | **0.000** | 0.125 | 0.125 |
| typo | 0.500 | **0.000** | 0.375 | 0.375 |
| jargon | 0.208 | 0.167 | 0.167 | **0.750** |
| ranking | 0.000 | 0.000 | 0.000 | **0.250** |
| natural_language | 0.875 | 0.750 | 0.750 | **1.000** |
| negation | 0.000 | 0.000 | 0.000 | 0.111 |

TinyBERT scores 0.000 on Polish queries. Zero. It reads Polish as irrelevant text. mmarco-multi's "multilingual" training doesnt save it from the same failures — its just slightly less terrible. BGE-m3 is the only model that consistently improves or maintains quality across categories.

### The Real Decision Framework

The question was never "which re-ranker should we use?" It was "WHEN should we re-rank, and with WHAT?"

**Decision framework:**
- Corpus has multilingual content (Polish, English, mixed) → BGE-m3. No alternatives.
- Corpus is English-only, air-gapped, CPU-only → TinyBERT (28ms, 14.5M params). Accept the quality trade-off for data sovereignty.
- Corpus is English-only, cloud is fine → skip re-ranking entirely. Dense embeddings handle English well enough without the latency hit.
- Corpus has < 20 documents → skip re-ranking. Initial retrieval is already precise enough.

The architecture makes this a config toggle:

```python
# apps/api/src/rag/reranker.py

class LocalCrossEncoderReranker(BaseReranker):
    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        top_k: int = 5,
        confidence_threshold: float = 0.0,
    ):
        if CrossEncoder is None:
            raise RerankerError("sentence-transformers required")
        self._model = CrossEncoder(model_name)
        self._top_k = top_k
        self._threshold = confidence_threshold
```

Switching models: change one string. No code changes, no pipeline modifications. Same ABC, same interface, different model underneath.

## 5. The Evidence: HyDE and Embedding Models

### HyDE Hurts at Small Scale

HyDE (Hypothetical Document Embedding) generates a hypothetical answer to the query, then embeds THAT instead of the original query. The theory: a well-formed answer is semantically closer to the target document than a vague question.

We tested it on 4 categories (vague, exact_code, natural_language, jargon) with live Azure OpenAI gpt-5-mini:

| Category | Without HyDE | With HyDE | Delta |
|---|---|---|---|
| vague (R@5) | 0.430 | 0.340 | **-20.9%** |
| exact_code (MRR) | 0.806 | 0.604 | **-25.0%** |
| natural_language (MRR) | 0.833 | 0.633 | **-24.0%** |
| jargon (MRR) | 0.500 | 0.500 | 0% |

HyDE hurts across the board. At 12-doc corpus scale, the hypothetical answer's embedding is LESS specific than the original query. The corpus is small enough that direct queries already find the right document. The generated hypothesis adds semantic noise.

**Switching condition**: HyDE probably helps above 500+ semantically similar documents where direct queries cant distinguish between candidates. Below that, its latency cost (~800ms for generation + embedding) buys you nothing.

### Embedding Model: Small Still Wins

Confirmed at 52 queries (double Phase 1's test set):

| Model | Dimensions | MRR | Cost/1M tokens |
|---|---|---|---|
| text-embedding-3-small | 1536 | **0.885** | $0.02 |
| text-embedding-3-large | 3072 | 0.856 | $0.13 |

The expensive model is worse by 0.029 MRR at 6.5x the cost. Higher dimensions dont help when your corpus has 12 documents — theres not enough semantic overlap to justify the additional separation. Switch condition: corpus exceeds 1000+ semantically similar documents where higher dimensions actually help distinguish near-duplicates.

## 6. The Cost

Monthly cost modeling for a LogiCore-sized deployment (200 queries/day, 500 documents):

| Component | Cost/month | Notes |
|---|---|---|
| Embeddings (text-embedding-3-small) | ~€0.12 | 200 queries × 30 days × $0.02/1M tok |
| BGE-m3 re-ranking | €0 | Runs locally, no API cost |
| HyDE (if enabled) | ~€1.50 | 200 queries × gpt-5-mini generation |
| Total Phase 2 pipeline | ~€0.12/month | Without HyDE (recommended) |
| Total with HyDE | ~€1.62/month | Not recommended at this scale |

The cost of the WRONG model choice:
- Deploying mmarco-multi instead of BGE-m3: -6.6% MRR. At 200 queries/day, thats ~13 queries/day returning wrong results. 13 wrong answers × 15 min of manual lookup = **3.25 hours/day of wasted employee time**. At €25/hr loaded cost, thats **€81/day, ~€1,700/month** in lost productivity from choosing a model based on its label instead of benchmarking it.
- Deploying text-embedding-3-large instead of small: €0.12 → €0.78/month in embedding cost. Small delta in absolute terms but 6.5x multiplier, and it performs WORSE. Youre paying more for lower quality.

BGE-m3's biggest cost advantage: it runs fully local. Zero API calls, zero data leaves your infrastructure. For a Polish company under GDPR, thats not just a cost saving — its an architectural advantage over Cohere or any cloud re-ranker. The data residency question doesnt even come up.

## 7. What Breaks

### Negation: The Achilles Heel (0.458 MRR)

"Show me contracts WITHOUT temperature requirements." Dense embeddings match on "temperature" — they cant negate. The semantic representation of "with temperature" and "without temperature" are nearly identical in embedding space.

BM25 can handle keyword negation, but BM25 hurts overall MRR (0.847 vs 0.885 for dense-only). You cant add BM25 just for negation without degrading everything else.

This isnt a retrieval fix. Its an agent reasoning problem. Phase 3 adds multi-agent orchestration where an agent can retrieve documents, then apply logical filtering ("has temperature requirement" → exclude). The retrieval layer fetches candidates; the reasoning layer filters them.

### BGE-m3 Typo Regression (-0.125)

BGE-m3 makes typo handling slightly worse (0.500 → 0.375 MRR on typo category). Cross-encoders read character-level patterns and penalize misspellings that bi-encoders tolerate. "pharamcorp" vs "PharmaCorp" — the bi-encoder embeddings are close enough; the cross-encoder sees a mismatch.

For workforces with high typo rates (mobile devices, warehouse workers), consider a spell-correction pre-processing step before re-ranking. This turns a model trade-off into a pipeline design recommendation.

### Latency Scales with Document Length

BGE-m3 latency at 7K char avg docs: ~480ms. At 1K char docs: ~355ms. We only have 2 data points here — not enough to model the curve. Is it linear? Sublinear? What happens at 20K char documents?

A CTO doing capacity planning needs a latency-vs-doc-length curve, not a trend. Mapped to Phase R for expansion with 5+ doc-length brackets.

## 8. What Id Do Differently

**Start with production-length documents.** Phase 1's corpus averaged 800-1500 chars. Phase 2's production corpora average 5-9K chars. Benchmark results at one doc length dont predict the other. If I started with 5K char docs in Phase 1, the hybrid-vs-dense conclusion might not have reversed — or it might have reversed earlier, saving a cycle.

**Benchmark more multilingual cross-encoders earlier.** We started with 3 models (TinyBERT, ms-marco, BGE-m3), then expanded to 6 after realizing the comparison was too narrow. The mmarco-multi finding ("multilingual" ≠ multilingual) is the strongest insight in the phase, but we almost missed it by not including it in the initial sweep.

**Dont trust the Phase 1 conclusion at Phase 2 scale.** The hybrid recommendation was right at 26 queries. It was wrong at 52. Every time you significantly expand your test set, re-run the foundational benchmarks. Treat previous findings as hypotheses, not facts.

**Test HyDE on a larger corpus before including it.** We benchmarked HyDE on 12 documents where its obviously not going to help. The real test is 500+ docs with high semantic overlap. Including it in Phase 2 was technically correct (it was in the spec) but the negative result was predictable. An architect should have called the switching condition before running the benchmark.

## 9. Vendor Lock-In and Swap Costs

| Component | Current | Alternative | Swap Cost |
|---|---|---|---|
| Embedding model | Azure OpenAI text-embedding-3-small | Cohere embed-v3, Nomic | Re-embed corpus (~€0.15 for 500 docs). BaseEmbedder ABC + factory: implement 3 methods, add to registry. |
| Re-ranker | BGE-m3 (local) | Cohere Rerank v3 (cloud), BGE-large (local) | Config toggle: `RERANKER_MODEL=BAAI/bge-reranker-large`. CohereReranker already implemented, same BaseReranker ABC. |
| Chunking strategy | SemanticChunker | FixedSizeChunker, ParentChildChunker | Re-ingest corpus. Strategy is constructor parameter. |
| Query transformation | None (HyDE disabled) | HyDE, MultiQuery, QueryDecomposer | Pipeline config: set transformer in RetrievalPipelineConfig. No code changes. |

The architecture is explicitly designed for swapability. Every component implements an ABC. The factory pattern (`get_embedder("azure_openai")`) means adding a new provider is 3 methods + 1 registry entry. The pipeline config is a dataclass — each stage is optional and injectable.

```python
# apps/api/src/rag/retriever.py

@dataclass
class RetrievalPipelineConfig:
    reranker: BaseReranker | None = None
    query_router: object | None = None
    hyde_transformer: object | None = None
    sanitizer: object | None = None
    rerank_top_k: int = 20
```

Lock-in risk is minimal. The most coupled component is Azure OpenAI for embeddings, and swapping it requires a corpus re-embed (~€0.15 at current scale). Everything else is a config change.

## 10. Series Close

Phase 2 of 12 in the LogiCore series. we proved that model labels are unreliable, benchmark conclusions are scale-dependent, and the re-ranking model choice matters more than the re-ranking technique itself.

the pipeline now: sanitize query → route by complexity → transform (optional) → dense search → re-rank with BGE-m3 → return top-5. each stage is optional, injectable, swappable.

next up: Phase 3 — what happens when search works but the AI cant reason across documents. "show me the contract with the highest annual value" fails every search mode at 0/3. thats not a retrieval problem, thats a multi-agent orchestration problem with human-in-the-loop approval gates.

329 tests. 52 queries. 6 re-ranking models. 2 production corpora. the numbers dont lie, but the model cards do 😅
