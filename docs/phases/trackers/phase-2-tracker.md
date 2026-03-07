# Phase 2 Tracker: Retrieval Engineering — Chunking, Re-Ranking, HyDE

**Status**: IN PROGRESS
**Spec**: `docs/phases/phase-2-retrieval-engineering.md`
**Depends on**: Phase 1

## Implementation Tasks

- [x] `apps/api/src/rag/chunking.py` — multiple chunking strategies: fixed-size, semantic, parent-child (48 tests)
- [x] `apps/api/src/rag/reranker.py` — cross-encoder re-ranking (Cohere + local model) (42 tests)
- [x] `apps/api/src/rag/query_transform.py` — HyDE, multi-query expansion, query decomposition, query router, query sanitizer (68 tests)
- [x] `apps/api/src/rag/embeddings.py` — MODIFY: multi-provider embedding (Azure OpenAI, Cohere, Mock) + BaseEmbedder ABC + factory + benchmark harness (52 tests)
- [x] `apps/api/src/rag/retriever.py` — MODIFY: integrate re-ranking + query transform + enhanced_search() pipeline (25 tests)
- [x] `scripts/benchmark_chunking.py` — compare chunking strategies (6 configs, clause integrity metric)
- [x] `scripts/benchmark_embeddings.py` — compare embedding models (mock + live modes, 52-query ground truth)
- [x] `scripts/benchmark_retrieval.py` — end-to-end retrieval quality (mock + live modes, per-category breakdown)
- [x] `tests/evaluation/test_retrieval_quality.py` — automated retrieval quality gate (30 tests: 7 precision@k, 6 recall@k, 7 MRR, 4 aggregate, 6 ground truth validation)
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
- **RerankResult is a dataclass, not Pydantic.** Same rationale as ChunkResult — internal pipeline data that never crosses API boundaries. Lightweight over Pydantic for intermediary data structures.
- **CrossEncoder import guarded with try/except.** `sentence-transformers` is optional — not all deployments need local cross-encoder. If missing, `LocalCrossEncoderReranker.rerank()` raises `RerankerError` with an install hint. This keeps the dependency optional for cloud-only deployments using CohereReranker.
- **CohereReranker uses httpx, not Cohere SDK.** Minimizes external dependencies. The Cohere Rerank v2 API is a single POST endpoint — a full SDK adds complexity with no benefit for a single API call.
- **TransformResult/QueryClassification are dataclasses, not Pydantic.** Same rationale as ChunkResult/RerankResult — internal pipeline data that never crosses API boundaries.
- **All transformers accept `llm_fn` callable, not a specific LLM client.** This makes unit testing trivial (pass a mock async function) and keeps the module framework-agnostic. The caller adapts their LLM client to this interface.
- **QueryRouter is a separate class, not a BaseQueryTransformer subclass.** Router classifies queries, it does not transform them. Different interface (classify vs transform) reflects different responsibility.
- **QuerySanitizer custom patterns REPLACE defaults, not supplement.** When you specify custom injection patterns, you get exactly those and no hidden defaults. This is intentional — domain-specific deployments may need entirely different pattern sets (e.g., SQL injection patterns instead of prompt injection patterns).
- **CohereEmbedder uses httpx, not Cohere SDK.** Same rationale as CohereReranker — the Cohere v2 embed endpoint is a single POST call. A full SDK adds complexity with no benefit.
- **MockEmbedder uses SHA-256 hash expansion, not random.** Deterministic by design — same text always produces the same vector across runs, which makes tests reproducible. Random-based mocks cause flaky tests.
- **AzureOpenAIEmbedder dimensions from registry, unknown defaults to 1536.** When using a custom deployment name not in EMBEDDING_MODELS, we default to 1536 (the most common OpenAI embedding dimension) rather than raising an error. This keeps the module usable with custom Azure deployment names.
- **EnhancedSearchResult is Pydantic, not dataclass.** Unlike RerankResult/ChunkResult (internal pipeline data), EnhancedSearchResult crosses API boundaries — it's the return type of enhanced_search() which may be serialized in API responses. Pydantic is the right choice here for validation + JSON serialization.
- **RetrievalPipelineConfig uses `object` type hints for pipeline components.** Avoids circular imports between retriever.py and query_transform.py. The actual types (QueryRouter, HyDETransformer, etc.) are duck-typed at runtime. Tests verify the correct interfaces are called.
- **HyDE replaces the embed_fn query, not the search query.** When HyDE is active, the hypothetical answer is used for the embedding vector (dense search), but the original query is used for BM25 (sparse search) in hybrid mode. This preserves exact-match capability while improving semantic search quality.
- **Multi-query deduplicates by (document_id, chunk_index) keeping highest score.** When multiple sub-queries return the same chunk, we keep the highest-scoring instance rather than the first-seen. This ensures the best match surfaces regardless of which sub-query found it.

## Code Artifacts

| File | Commit | Notes |
|---|---|---|
| `apps/api/src/rag/chunking.py` | feat(phase-2) | 3 strategies (FixedSize, Semantic, ParentChild), factory function, ChunkResult dataclass. All domain-agnostic — strategy, chunk_size, overlap, similarity_threshold, section_pattern all configurable. SemanticChunker accepts injectable embed_fn for testability. |
| `tests/unit/test_chunking.py` | feat(phase-2) | 48 tests: 12 FixedSize, 13 Semantic, 14 ParentChild, 5 factory, 3 ChunkResult, 3 BaseChunker ABC. Semantic tests use deterministic topic-based fake embedder. |
| `apps/api/src/rag/reranker.py` | feat(phase-2) | 5 reranker implementations (NoOp, Cohere, LocalCrossEncoder, CircuitBreaker, BaseReranker ABC), factory function, RerankResult dataclass, RerankerError, RerankerStrategy enum. All configurable via params. CircuitBreaker is composable (wraps any primary/fallback pair). CrossEncoder import is optional (guarded try/except). CohereReranker uses httpx directly. |
| `tests/unit/test_reranker.py` | feat(phase-2) | 42 tests: 2 RerankResult, 3 BaseReranker ABC, 7 NoOpReranker, 7 CohereReranker (mocked httpx), 7 LocalCrossEncoderReranker (mocked CrossEncoder), 8 CircuitBreakerReranker (CLOSED/OPEN/HALF_OPEN states, configurable threshold/timeout, failure reset), 7 factory, 1 enum. |
| `apps/api/src/rag/query_transform.py` | feat(phase-2) | 6 components: QuerySanitizer (9 default injection patterns, configurable max_length/patterns), HyDETransformer (hypothetical document for embedding), MultiQueryTransformer (configurable num_queries), QueryDecomposer (multi-hop splitting), QueryRouter (4-category classification with JSON parsing + fallback), BaseQueryTransformer ABC. Factory function for all transformer strategies. All transformers auto-sanitize input via composable QuerySanitizer. LLM-agnostic via injectable llm_fn callable. |
| `tests/unit/test_query_transform.py` | feat(phase-2) | 68 tests: 21 QuerySanitizer (injection stripping x9 patterns, case-insensitive, truncation, control chars, unicode, empty input, configurable max_length/patterns, custom-replaces-defaults, multi-pattern), 3 TransformResult, 2 QueryClassification, 1 TransformStrategy, 8 HyDETransformer (result structure, sanitization, LLM error, configurable model/prompt/sanitizer, metadata), 7 MultiQueryTransformer (expansion, configurable num_queries, default limit, LLM error, sanitization, empty line filtering, metadata), 6 QueryDecomposer (multi-hop split, single-hop passthrough, LLM error, sanitization, empty lines, metadata), 12 QueryRouter (4 categories, LLM error default, configurable default/model, sanitization, raw/sanitized preservation, malformed JSON fallback, unknown category fallback), 6 factory, 2 ABC. |
| `apps/api/src/rag/embeddings.py` | feat(phase-2) | Extended from single-provider to multi-provider: EmbeddingProvider enum (azure_openai, cohere, nomic, mock), EmbeddingModel dataclass with EMBEDDING_MODELS registry (4 models), BaseEmbedder ABC (embed_query, embed_documents, dimensions), AzureOpenAIEmbedder (wraps langchain), CohereEmbedder (httpx direct, not SDK), MockEmbedder (deterministic SHA-256 hash-based), EmbeddingBenchmarkResult dataclass, EmbeddingError, get_embedder() factory. Backward compatible: get_embeddings(), EMBEDDING_SMALL, EMBEDDING_LARGE all preserved. |
| `tests/unit/test_embeddings.py` | feat(phase-2) | 52 tests: 4 EmbeddingProvider enum, 5 EmbeddingModel + registry, 3 EmbeddingBenchmarkResult (fields, default notes, custom notes), 3 BaseEmbedder ABC (instantiation blocked, partial impl blocked, full impl works), 10 MockEmbedder (dimensionality, determinism, uniqueness, types, empty list, normalization, configurable dims), 6 AzureOpenAIEmbedder (delegation to langchain, params, dimensions for small/large/unknown), 8 CohereEmbedder (API call structure, dimensions, multi-doc, error handling, configurable model/input_type, unknown model default), 7 get_embedder factory (all providers, invalid, kwargs, enum), 4 backward compat (get_embeddings, model param, constants), 2 EmbeddingError. |
| `apps/api/src/rag/retriever.py` | feat(phase-2) | Added enhanced_search() pipeline wrapper around hybrid_search(). RetrievalPipelineConfig dataclass for composable pipeline stages. Pipeline: sanitize -> route -> transform -> search -> rerank. Each stage optional, each handles its own errors (graceful degradation). hybrid_search() unchanged for Phase 1 backward compatibility. EnhancedSearchResult added to domain/document.py (Pydantic, extends SearchResult fields + pipeline metadata). |
| `tests/unit/test_enhanced_retriever.py` | feat(phase-2) | 25 tests: 5 basic (no-pipeline returns EnhancedSearchResult, preserves fields, empty results, RBAC filter, search mode forwarding), 5 reranker (reorders results, scores available, top_k respected, failure degrades gracefully, rerank_top_k overrides search limit), 4 query transform (HyDE transforms embedding query, multi-query merges+deduplicates, HyDE failure fallback, multi-query failure fallback), 5 router (KEYWORD skips transforms+reranking, STANDARD applies reranking only, VAGUE applies HyDE+reranking, MULTI_HOP applies decompose+reranking, router failure defaults to STANDARD), 4 full pipeline (full stage ordering, all stages optional, pipeline=None, sanitizer-before-everything ordering), 2 backward compat (hybrid_search signature unchanged, returns SearchResult not Enhanced). |
| `tests/evaluation/ground_truth.py` | feat(phase-2) | 52 ground truth queries across 10 categories: exact_code (8), natural_language (8), vague (6), negation (6), german (4), synonym (4), typo (4), jargon (4), ranking (4), multi_hop (4). GroundTruthQuery dataclass with query, category, relevant_doc_ids, description. Helper functions: get_queries_by_category(), get_all_categories(). Self-validating: asserts 50+ queries and 10 categories on import. |
| `tests/evaluation/corpus.py` | feat(phase-2) | Shared 12-document CorpusDocument dataclass (doc_id, text, department, clearance_level). Canonical corpus matching Phase 1 benchmark DOCS array. Used by all benchmark scripts and evaluation tests. |
| `tests/evaluation/metrics.py` | feat(phase-2) | 3 metric functions: compute_precision_at_k, compute_recall_at_k, compute_mrr. RetrievalEvalResult dataclass (aggregate + per-category). run_evaluation() function for batch evaluation against ground truth. Zero external dependencies. |
| `tests/evaluation/test_retrieval_quality.py` | feat(phase-2) | 30 tests: TestPrecisionAtK (7 tests — perfect, zero, partial, k truncation, empty edge cases), TestRecallAtK (6 tests — same coverage), TestMRR (7 tests — rank position, multiple relevant, empty edge cases), TestRunRetrieval (4 tests — perfect/zero/per-category/empty), TestGroundTruthDataset (6 tests — 50+ queries, 10 categories, 4+ per category, valid doc IDs, unique queries). |
| `scripts/benchmark_chunking.py` | feat(phase-2) | Compares 6 chunking configurations (FixedSize 512/256, Semantic 0.5/0.3, ParentChild default/min30). Measures: chunk count, avg size, size variance, clause integrity (8 key clauses). Supports --data-dir for disk files or inline corpus fallback. --output-json for CI. Includes architect verdict on clause integrity. |
| `scripts/benchmark_embeddings.py` | feat(phase-2) | Benchmarks embedding models against 52 ground truth queries. Mock mode (--mock) or live mode (--models). Measures: precision@k, recall@k, MRR, latency, cost. Architect verdict: cost/quality tradeoff with recommendation and revisit condition. |
| `scripts/benchmark_retrieval.py` | feat(phase-2) | End-to-end pipeline benchmark: chunking + embedding + search. Mock mode (in-memory cosine similarity) or live mode (Qdrant + Azure OpenAI). Per-category breakdown. Architect verdict with quality gate (MRR >= 0.80). |

## Test Results

| Test | Status | Notes |
|---|---|---|
| `tests/unit/test_chunking.py` (48 tests) | PASS | FixedSize: word boundary, overlap, coverage, empty/single/long inputs. Semantic: topic clustering, boundary detection, min/max size, configurable threshold. ParentChild: parent-child hierarchy, child-references-parent, metadata, custom patterns, min_child_size merge, max_parent_size split. Factory: all strategies + invalid strategy error. |
| Full suite (112 tests) | PASS | No regressions from Phase 1 (64 existing tests unaffected) |
| `tests/unit/test_reranker.py` (42 tests) | PASS | NoOp: order preservation, empty input, top_k, content/metadata preservation, confidence threshold (filter/exclude/all-below-empty). Cohere: API call structure, reorder by score, top_k, API error -> RerankerError, configurable model, confidence threshold. LocalCrossEncoder: predict call with pairs, reorder by score, top_k, model load failure -> RerankerError, configurable model, confidence threshold. CircuitBreaker: primary when healthy, fallback after N failures, configurable threshold, reset on success, half-open after timeout, half-open failure reopens, half-open success closes, stays open within timeout. Factory: all strategies + invalid. |
| Full suite (154 tests) | PASS | No regressions. 42 new reranker + 48 chunking + 64 Phase 1 tests. |
| `tests/unit/test_query_transform.py` (68 tests) | PASS | QuerySanitizer: 9 injection patterns stripped (case-insensitive), control char removal, truncation, unicode preservation, empty/whitespace handling, configurable patterns (replace not supplement), multi-pattern stripping. HyDE: result structure, sanitization before LLM, error handling, configurable model/prompt/sanitizer, metadata. MultiQuery: expansion + limit to num_queries, empty line filtering, sanitization. Decomposer: multi-hop split, single-hop passthrough, sanitization. Router: 4 categories, JSON parsing, malformed JSON fallback, unknown category fallback, configurable default, raw/sanitized preservation. Factory: all strategies + string input + invalid error. ABC: instantiation blocked. |
| Full suite (222 tests) | PASS | No regressions. 68 new query_transform + 42 reranker + 48 chunking + 64 Phase 1 tests. |
| `tests/unit/test_embeddings.py` (52 tests) | PASS | EmbeddingProvider: 4 enum values. EmbeddingModel: all fields + 4 registry entries (small, large, cohere, nomic). EmbeddingBenchmarkResult: all fields + default/custom notes. BaseEmbedder ABC: instantiation blocked, partial blocked, full works. MockEmbedder: correct dimensions, deterministic, unique vectors, float types, empty list, normalized values, configurable dims. AzureOpenAIEmbedder: delegates to langchain (query + documents), correct params, dimensions from registry (small=1536, large=3072, unknown=1536). CohereEmbedder: correct API call structure, embed_documents uses search_document input_type, API error -> EmbeddingError, configurable model/input_type, dimensions from registry. Factory: all 3 providers + invalid error + kwargs passthrough + enum input. Backward compat: get_embeddings() still works, model param works, EMBEDDING_SMALL/LARGE constants exported. |
| Full suite (274 tests) | PASS | No regressions. 52 new embeddings + 68 query_transform + 42 reranker + 48 chunking + 64 Phase 1 tests. |
| `tests/unit/test_enhanced_retriever.py` (25 tests) | PASS | Basic: no-pipeline passthrough returns EnhancedSearchResult, preserves all SearchResult fields, empty results, RBAC filter verified, search mode forwarded. Reranker: result reordering, rerank_score in metadata, top_k after rerank, graceful degradation on failure (returns un-reranked), rerank_top_k overrides search limit. QueryTransform: HyDE hypothetical used for embedding, multi-query merges+deduplicates by (doc_id, chunk_index) keeping highest score, both HyDE and multi-query fall back to original query on failure. Router: KEYWORD fast path skips transforms+reranking, STANDARD applies reranking only, VAGUE applies HyDE+reranking, MULTI_HOP applies decompose+reranking, router failure defaults to STANDARD. Full pipeline: stage ordering verified (sanitize before route), all stages independently optional, pipeline=None equivalent to empty config. Backward compat: hybrid_search() signature unchanged, returns SearchResult (not EnhancedSearchResult). |
| Full suite (299 tests) | PASS | No regressions. 25 new enhanced_retriever + 52 embeddings + 68 query_transform + 42 reranker + 48 chunking + 64 Phase 1 tests. |
| `tests/evaluation/test_retrieval_quality.py` (30 tests) | PASS | Precision@k: 7 tests (perfect, zero, partial, k>retrieved, k truncation, empty retrieved, empty relevant). Recall@k: 6 tests (same coverage). MRR: 7 tests (rank 1/2/3, no relevant, multiple relevant, empty). Aggregate: 4 tests (perfect/zero retrieval, per-category, empty results). Ground truth validation: 6 tests (50+ queries, 10 categories, 4+ per category, valid doc IDs, unique). |
| Full suite (329 tests) | PASS | No regressions. 30 new evaluation + 25 enhanced_retriever + 52 embeddings + 68 query_transform + 42 reranker + 48 chunking + 64 Phase 1 tests. |

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
