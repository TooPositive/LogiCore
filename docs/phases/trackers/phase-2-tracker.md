# Phase 2 Tracker: Retrieval Engineering — Chunking, Re-Ranking, HyDE

**Status**: IN PROGRESS
**Spec**: `docs/phases/phase-2-retrieval-engineering.md`
**Depends on**: Phase 1

## Implementation Tasks

- [x] `apps/api/src/rag/chunking.py` — multiple chunking strategies: fixed-size, semantic, parent-child (48 tests)
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

- **ChunkResult is a dataclass, not Pydantic.** The spec shows `ChunkResult` as a plain data container. Using `@dataclass` is lighter than Pydantic for internal pipeline data that never crosses API boundaries. Domain `Chunk` (Pydantic) is applied at ingestion time.
- **SemanticChunker uses synchronous embed_fn.** The chunker itself is CPU-bound (sentence splitting, similarity math). The embed_fn is called once per chunk() call with all sentences batched. Async is unnecessary here — the caller can await externally if needed.

## Code Artifacts

| File | Commit | Notes |
|---|---|---|
| `apps/api/src/rag/chunking.py` | feat(phase-2) | 3 strategies (FixedSize, Semantic, ParentChild), factory function, ChunkResult dataclass. All domain-agnostic — strategy, chunk_size, overlap, similarity_threshold, section_pattern all configurable. SemanticChunker accepts injectable embed_fn for testability. |
| `tests/unit/test_chunking.py` | feat(phase-2) | 48 tests: 12 FixedSize, 13 Semantic, 14 ParentChild, 5 factory, 3 ChunkResult, 3 BaseChunker ABC. Semantic tests use deterministic topic-based fake embedder. |

## Test Results

| Test | Status | Notes |
|---|---|---|
| `tests/unit/test_chunking.py` (48 tests) | PASS | FixedSize: word boundary, overlap, coverage, empty/single/long inputs. Semantic: topic clustering, boundary detection, min/max size, configurable threshold. ParentChild: parent-child hierarchy, child-references-parent, metadata, custom patterns, min_child_size merge, max_parent_size split. Factory: all strategies + invalid strategy error. |
| Full suite (112 tests) | PASS | No regressions from Phase 1 (64 existing tests unaffected) |

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
