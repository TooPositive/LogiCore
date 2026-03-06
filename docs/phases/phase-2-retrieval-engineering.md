# Phase 2: "Retrieval Engineering" — Chunking, Re-Ranking, HyDE & Embedding Evaluation

## Business Problem

Phase 1 built a working RAG pipeline. It passes the demo. But in production, retrieval quality is the bottleneck — not the LLM. A logistics contract has 47 pages of clauses. Naive fixed-size chunking slices a termination clause across two chunks. Vector similarity returns "mathematically similar" results that aren't actually relevant. Users ask vague questions and get nothing useful back.

**CTO pain**: "The AI found 'similar' documents, but they weren't the right documents. We need retrieval we can trust for legal decisions."

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
  → LLM
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
    hypothetical = await llm.generate(
        f"Write a short passage that would answer: {query}"
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

### Success Criteria
- [ ] 3 chunking strategies implemented with benchmark script
- [ ] Semantic chunking shows >15% precision improvement over fixed-size on contract queries
- [ ] Re-ranking improves precision@5 by >20% over raw hybrid search
- [ ] HyDE improves recall on vague queries ("what's our termination policy?") by >25%
- [ ] Embedding model benchmark completed, winner documented in ADR
- [ ] End-to-end retrieval quality gate: precision@5 > 0.85, MRR > 0.80
- [ ] All benchmarks reproducible via scripts

## LinkedIn Post Angle
**Hook**: "Vector similarity is lying to you. Here's the one step that fixed our RAG quality."
**Medium deep dive**: "We Tried 3 Chunking Strategies on Logistics Contracts. Only One Survived Production." — full benchmark data, code snippets, precision/recall charts.

## Key Metrics to Screenshot
- Before/after: retrieval precision with and without re-ranking
- Chunking comparison table: fixed vs semantic vs parent-child
- Embedding model benchmark chart (precision vs cost vs latency)
- HyDE: vague query retrieval improvement
