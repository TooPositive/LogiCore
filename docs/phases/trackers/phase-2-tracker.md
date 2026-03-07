# Phase 2 Tracker: Retrieval Engineering — Chunking, Re-Ranking, HyDE

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-2-retrieval-engineering.md`
**Depends on**: Phase 1

## Implementation Tasks

- [ ] `apps/api/src/rag/chunking.py` — multiple chunking strategies: fixed-size, semantic, parent-child
- [ ] `apps/api/src/rag/reranker.py` — cross-encoder re-ranking (Cohere + local model)
- [ ] `apps/api/src/rag/query_transform.py` — HyDE, multi-query expansion, query decomposition
- [ ] `apps/api/src/rag/embeddings.py` — MODIFY: support multiple embedding models, benchmark harness
- [ ] `apps/api/src/rag/retriever.py` — MODIFY: integrate re-ranking + query transform
- [ ] `scripts/benchmark_chunking.py` — compare chunking strategies
- [ ] `scripts/benchmark_embeddings.py` — compare 4 embedding models
- [ ] `scripts/benchmark_retrieval.py` — end-to-end retrieval quality
- [ ] `tests/evaluation/test_retrieval_quality.py` — automated retrieval quality gate
- [ ] `docs/adr/004-chunking-strategy.md`
- [ ] `docs/adr/005-reranking-layer.md`
- [ ] `docs/adr/006-embedding-model-choice.md`

## Success Criteria

- [ ] 3 chunking strategies implemented with benchmark script
- [ ] Semantic chunking >15% precision improvement over fixed-size on contract queries
- [ ] Re-ranking improves precision@5 by >20% over raw hybrid search
- [ ] HyDE improves recall on vague queries by >25%
- [ ] Embedding model benchmark completed, winner documented in ADR
- [ ] End-to-end quality gate: precision@5 > 0.85, MRR > 0.80

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Chunking winner | semantic | | benchmark results |
| Re-ranker | Cohere Rerank v3 | | |
| Embedding model | 4-way benchmark | | benchmark results |
| HyDE prompt template | generic | | |

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
| Fixed-size chunking precision@5 | | baseline |
| Semantic chunking precision@5 | | vs fixed-size |
| Parent-child chunking precision@5 | | vs fixed-size |
| Re-ranking precision@5 improvement | | before/after re-rank |
| HyDE recall improvement (vague queries) | | before/after HyDE |
| text-embedding-3-small precision | | benchmark |
| text-embedding-3-large precision | | benchmark |
| cohere-embed-v4 precision | | benchmark |
| nomic-embed-text-v1.5 precision | | benchmark |
| Embedding cost per 1K docs | | per model |
| Re-ranking latency overhead | | ms added per query |

## Screenshots Captured

- [ ] Chunking comparison table (3 strategies)
- [ ] Re-ranking before/after precision chart
- [ ] Embedding model benchmark chart
- [ ] HyDE vague query improvement

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | "We Tried 3 Chunking Strategies. Only One Survived." |
