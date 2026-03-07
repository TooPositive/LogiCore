# Phase 2: "Retrieval Engineering" — Chunking, Re-Ranking, HyDE & Embedding Evaluation

## Business Problem

Phase 1 built a working RAG pipeline. It passes the demo. But in production, retrieval quality is the bottleneck — not the LLM. A logistics contract has 47 pages of clauses. Naive fixed-size chunking slices a termination clause across two chunks. Vector similarity returns "mathematically similar" results that aren't actually relevant. Users ask vague questions and get nothing useful back.

**CTO pain**: "The AI found 'similar' documents, but they weren't the right documents. We need retrieval we can trust for legal decisions."

## Real-World Scenario: LogiCore Transport

**Feature: Search Quality Toggle (Before/After)**

Logistics manager Anna Schmidt asks: "What happens if we deliver PharmaCorp cargo late?"

**Without Phase 2** (naive fixed-size chunking): The 47-page PharmaCorp contract was chunked at 512-token boundaries. The termination clause spans two chunks — chunk 23 has "In the event of late delivery" and chunk 24 has "a penalty of 15% of shipment value applies." The AI retrieves chunk 23 but not 24. Answer: "Late delivery may result in penalties." Useless.

**With Phase 2** (semantic chunking + re-ranking): The contract is chunked by clause. The full penalty section stays together in one chunk. Re-ranker scores this chunk 0.94 against the query (vs 0.61 for a vaguely similar shipping terms clause). Answer: "Late delivery to PharmaCorp incurs a 15% penalty on shipment value per CTR-2024-001, Section 8.3. For a typical 7,200 kg shipment at €0.45/kg, that's a €486 penalty."

**HyDE in action**: Driver Hans Muller asks the vague question "what should I know about the Zurich delivery?" — there's no document titled "Zurich delivery." HyDE generates a hypothetical answer ("The Zurich delivery involves pharmaceutical cargo requiring 2-8°C cold chain...") and embeds THAT. The hypothetical answer's embedding is much closer to the actual Swiss Customs Regulation Summary and Cold Chain Compliance Guide than the original vague question would be.

**The "aha" moment**: Side-by-side comparison. Same question, dramatically different answer quality. Precision@5 jumps from 0.62 to 0.89.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Semantic chunking | Complete contract clauses in search results, not cut-off fragments | AI gives the full answer, not half of it |
| Re-ranking (cross-encoder) | The most relevant result is actually #1, not buried at #4 | Users trust the first answer — it better be right |
| HyDE (Hypothetical Document Embedding) | Vague questions ("what about Zurich?") return precise docs | Employees don't need to know exact terminology to find answers |
| Embedding model benchmark | Invisible — just better search quality | Data-driven model choice, not "we used the default" |
| Parent-child chunking | AI shows the specific clause but has full section as context | Answers are precise but never miss surrounding context |

## Architecture

```
User Query
  → Query Transformer
  │   ├── HyDE: generate hypothetical answer → embed that instead
  │   ├── Multi-Query: expand into 3-5 reformulations
  │   └── Query Decomposition: split multi-hop questions
  → Hybrid Search (BM25 + best embedding model)
  │   └── Embedding Model: winner from benchmark (phase deliverable)
  → Re-Ranker (cross-encoder)
  │   ├── Cloud: Cohere Rerank v3
  │   └── Air-gapped: cross-encoder/ms-marco-MiniLM-L-12-v2
  → RBAC Filter (from Phase 1)
  → Context Assembly (top-k after re-ranking)
  → LLM (GPT-5 mini for standard RAG / GPT-5.2 for multi-hop reasoning)
```

**Key design decisions**:
- Chunking is not one-size-fits-all: semantic chunking by contract clause with parent-child hierarchy
- Re-ranking is the single biggest quality improvement — cross-encoder scores actual query-document relevance, not just embedding similarity
- HyDE works because embedding a well-formed answer is closer to the target document than embedding a vague question
- Embedding model choice is data-driven, not default — benchmark against actual corpus

## Implementation Guide

### Prerequisites
- Phase 1 complete (basic RAG pipeline operational)
- Test dataset: 50+ query-answer pairs with ground truth relevant chunks
- Mock contracts with known clause structure

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/rag/chunking.py` | Multiple chunking strategies: fixed-size, semantic, parent-child |
| `apps/api/src/rag/reranker.py` | Cross-encoder re-ranking (Cohere + local model) |
| `apps/api/src/rag/query_transform.py` | HyDE, multi-query expansion, query decomposition |
| `apps/api/src/rag/embeddings.py` | **Modify** — support multiple embedding models, benchmark harness |
| `apps/api/src/rag/retriever.py` | **Modify** — integrate re-ranking + query transform into pipeline |
| `scripts/benchmark_chunking.py` | Compare chunking strategies against test queries |
| `scripts/benchmark_embeddings.py` | Compare 4 embedding models on corpus |
| `scripts/benchmark_retrieval.py` | End-to-end retrieval quality (precision@k, recall@k, MRR) |
| `tests/evaluation/test_retrieval_quality.py` | Automated retrieval quality gate |
| `docs/adr/004-chunking-strategy.md` | ADR: semantic chunking over fixed-size |
| `docs/adr/005-reranking-layer.md` | ADR: cross-encoder re-ranking |
| `docs/adr/006-embedding-model-choice.md` | ADR: embedding model benchmark results |

### Technical Spec

**Chunking Strategies**:
```python
class ChunkingStrategy(Protocol):
    def chunk(self, document: str, metadata: dict) -> list[Chunk]: ...

class FixedSizeChunker:
    """Baseline: 512 tokens, 50 token overlap."""

class SemanticChunker:
    """Split by semantic similarity breakpoints between sentences."""

class ParentChildChunker:
    """Contract-aware: chunk by clause/section.
    Parent = full section, Child = individual clause.
    Retrieve child, return parent for context."""
```

**Re-Ranking**:
```python
async def rerank(query: str, documents: list[str], top_k: int = 5) -> list[RankedResult]:
    """Score each document against query using cross-encoder.
    Returns documents sorted by relevance score, not vector similarity."""
    # Cloud: Cohere Rerank v3
    # Air-gapped: sentence-transformers cross-encoder
```

**HyDE (Hypothetical Document Embedding)**:
```python
async def hyde_transform(query: str) -> str:
    """Generate a hypothetical answer, embed THAT instead of the raw query.
    Bridges the gap between question-space and answer-space embeddings."""
    # GPT-5 mini — good enough for hypothesis generation, 7x cheaper than GPT-5.2
    hypothetical = await llm.generate(
        model="gpt-5-mini",
        prompt=f"Write a short passage that would answer: {query}"
    )
    return hypothetical  # embed this, search with this vector
```

**Embedding Model Benchmark**:
```python
MODELS_TO_EVALUATE = [
    "text-embedding-3-small",   # 1536 dims, Azure
    "text-embedding-3-large",   # 3072 dims, Azure
    "cohere-embed-v4",          # 1024 dims, Cohere
    "nomic-embed-text-v1.5",    # 768 dims, open-source (air-gappable)
]
# Metrics: precision@5, recall@10, MRR, latency, cost per 1K embeddings
```

## Decision Framework: Retrieval Strategy Selection

### Decision Tree: Query Complexity → Retrieval Strategy

```
Incoming Query
│
├── Is the query a simple keyword/ID lookup? ("ISO-9001", "CTR-2024-001")
│   → BM25-heavy hybrid search (alpha=0.2), NO HyDE, NO re-ranking
│   → Cost: ~€0.0001 (embedding only)
│   → Latency: ~50ms
│
├── Is the query a standard natural language question? ("What are PharmaCorp penalties?")
│   → Hybrid search (alpha=0.6), NO HyDE, YES re-ranking (top 20→5)
│   → Cost: ~€0.001 (embedding + Cohere re-rank)
│   → Latency: ~200ms
│
├── Is the query vague/exploratory? ("what should I know about Zurich?")
│   → HyDE transform THEN hybrid search, YES re-ranking
│   → Cost: ~€0.004 (GPT-5 mini HyDE + embedding + re-rank)
│   → Latency: ~500ms
│
└── Is the query multi-hop? ("Compare penalties across all Q4 contracts")
    → Query decomposition into sub-queries, parallel retrieval, re-ranking, GPT-5.2 synthesis
    → Cost: ~€0.025 (multiple retrievals + GPT-5.2 reasoning)
    → Latency: ~1.5s
```

**How the router decides**: GPT-5 nano classifies query complexity in ~20ms for €0.00002. The classification is a 4-way label: `keyword | standard | vague | multi-hop`. Log classifications in Langfuse and review weekly — if >5% of "standard" queries get poor results, your classifier boundary needs tuning.

### When to Re-Rank (and When NOT to)

Re-ranking passes the top-N candidates through a cross-encoder that scores actual query-document relevance (not just embedding similarity). It's the single biggest quality improvement — but not always worth the cost.

**USE re-ranking when**:
- Legal/financial documents where precision matters more than speed
- Top-5 results from hybrid search have scores clustered between 0.55-0.75 (hard to distinguish)
- Query is natural language (semantic), not a keyword/ID lookup
- Your benchmark shows >15% precision@5 improvement with re-ranking (Phase 2 target: >20%)

**SKIP re-ranking when**:
- Query is an exact ID/keyword lookup (BM25 already nails it)
- Top-1 hybrid search score is >0.90 (clearly the right document)
- Latency budget is <100ms (re-ranking adds 50-150ms)
- Corpus is small (<500 documents) — hybrid search is usually sufficient
- Cost sensitivity is extreme (Cohere re-rank: ~€0.001/query, adds up at 100K queries/month = €100/mo)

**Cost curve**: Re-ranking adds ~€0.001/query but improves precision@5 by 20-30% in benchmarks. At 10K queries/month that's €10/mo for substantially better answers. At 1M queries/month, consider a local cross-encoder (`cross-encoder/ms-marco-MiniLM-L-12-v2` on GPU) to eliminate the per-query cost.

### When to Use HyDE (and When NOT to)

HyDE generates a hypothetical answer and embeds that instead of the raw query. It bridges the question-space vs answer-space embedding gap.

**USE HyDE when**:
- Queries are vague or exploratory ("what should I know about...?")
- Users don't know the exact terminology (new employees, cross-department queries)
- Your benchmark shows >20% recall improvement on vague queries (Phase 2 target: >25%)
- The extra LLM call latency (~200-300ms with GPT-5 mini) is acceptable

**SKIP HyDE when**:
- Query contains exact identifiers (contract IDs, ISO codes) — HyDE adds noise
- Query is already well-formed and specific ("What is the penalty rate in CTR-2024-001 Section 8.3?")
- Latency budget is tight (<200ms) — HyDE adds a full LLM round-trip
- Cost is critical — each HyDE call costs ~€0.003 (GPT-5 mini). At 50K vague queries/month = €150/mo
- Your corpus has strong keyword coverage (BM25 handles most queries well)

**Rule of thumb**: Run HyDE on the 20% of queries that are vague. Skip it on the 80% that are specific. The query router (GPT-5 nano, €0.00002/classification) makes this decision.

### Success Criteria
- [ ] 3 chunking strategies implemented with benchmark script
- [ ] Semantic chunking shows >15% precision improvement over fixed-size on contract queries
- [ ] Re-ranking improves precision@5 by >20% over raw hybrid search
- [ ] HyDE improves recall on vague queries ("what's our termination policy?") by >25%
- [ ] Embedding model benchmark completed, winner documented in ADR
- [ ] End-to-end retrieval quality gate: precision@5 > 0.85, MRR > 0.80
- [ ] All benchmarks reproducible via scripts

## Cost of Getting It Wrong

Precision@5 of 0.62 vs 0.89 is not a benchmark number — it's a financial number.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Re-ranker promotes wrong clause** | Cross-encoder scores shipping terms 0.91, actual penalty clause 0.88. User gets confident but wrong answer. | EUR 486-3,240/incident (wrong penalty calculation acted upon) | 1/month |
| **Chunking splits critical clause** | Termination clause split across chunks. AI answers "penalties may apply" instead of "15% penalty, EUR 486 per shipment." | EUR 486/incident (vague answer → wrong negotiation) | 3-5/month without semantic chunking |
| **Re-ranker down, silent fallback** | Cohere API returns errors. System falls back to raw hybrid (0.62 precision). 38% of top-5 results are wrong. | System-wide: 38% wrong at ~800 queries/day = 304 wrong answers/day | Until detected |
| **Embedding model silent update** | Provider updates embedding model. Old vectors return different neighbors. Quality degrades for weeks. | EUR 500/week accumulated | 1-2/year |

**Reframe**: "Every 1% drop in precision@5 costs approximately EUR 500/month in wrong business decisions acted upon. Re-ranking isn't a search optimization — it's a financial safety net."

### The PharmaCorp Penalty Cascade

Without Phase 2: naive chunking returns half the penalty clause. Anna tells the driver "there may be penalties." Driver doesn't prioritize. Delivery is late. 15% penalty on 7,200 kg at EUR 0.45/kg = **EUR 486**.

With Phase 2: exact clause, exact number. Anna tells the driver "EUR 486 penalty if late." Driver prioritizes.

The difference between "may be penalties" and "EUR 486" is the difference between a vague warning and an actionable business decision.

### Re-Ranker Failure Mode

What happens when the re-ranker is unavailable?

| State | Precision@5 | Business Impact |
|---|---|---|
| Re-ranker active | 0.89 | 11% wrong results — acceptable with HITL |
| Re-ranker down (raw hybrid) | 0.62 | 38% wrong results — financial decisions unreliable |
| Re-ranker + HyDE active | 0.93+ | 7% wrong results — best quality |

**Mitigation**: If re-ranker is unavailable, force HITL review on all financial queries. Don't serve degraded results for high-stakes decisions without human verification.

## LinkedIn Post Angle
**Hook**: "Vector similarity is lying to you. Here's the one step that fixed our RAG quality."
**Medium deep dive**: "We Tried 3 Chunking Strategies on Logistics Contracts. Only One Survived Production." — full benchmark data, code snippets, precision/recall charts.

## Key Metrics to Screenshot
- Before/after: retrieval precision with and without re-ranking
- Chunking comparison table: fixed vs semantic vs parent-child
- Embedding model benchmark chart (precision vs cost vs latency)
- HyDE: vague query retrieval improvement
