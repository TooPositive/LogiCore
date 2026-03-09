# Phase 2 Technical Recap: Retrieval Engineering

## What This Phase Does (Business Context)

Phase 1 built a working RAG pipeline: embed documents, search with Qdrant, return results filtered by RBAC. It passes the demo. Phase 2 solves the next problem: the AI finds "similar" documents, but they aren't the RIGHT documents. A logistics contract has penalty clauses, delivery terms, and termination conditions. Naive chunking cuts clauses in half. Vector similarity returns 5 documents about PharmaCorp when only 1 has the penalty clause. Phase 2 adds chunking strategies, re-ranking, query transformation, multi-provider embeddings, and a security sanitizer — all configurable, all swappable, all domain-agnostic.

## Architecture Overview

```
User Query
  │
  ▼
QuerySanitizer (strip 9 injection patterns)
  │
  ▼
QueryRouter (classify: KEYWORD / STANDARD / VAGUE / MULTI_HOP)
  │
  ├── KEYWORD → skip transforms, skip reranker → hybrid_search → return
  ├── STANDARD → hybrid_search → reranker → return
  ├── VAGUE → HyDETransformer → hybrid_search → reranker → return
  └── MULTI_HOP → QueryDecomposer → multi-search → merge → reranker → return
  │
  ▼
enhanced_search() wraps hybrid_search() from Phase 1
  │
  ▼
RetrievalPipelineConfig (dataclass, all stages optional)
```

Data flow: raw user query → sanitize → classify → optionally transform → search Qdrant (dense/sparse/hybrid with RBAC filter) → optionally re-rank with cross-encoder → return top-k as EnhancedSearchResult.

## Components Built

### 1. Chunking Module: `apps/api/src/rag/chunking.py`

**What it does**: Splits documents into chunks for embedding and retrieval. Three strategies for different document types.

**The pattern: Strategy Pattern + ABC + Factory**

Why Strategy Pattern: different document types need different chunking. A 47-page contract needs semantic boundaries (keep clauses together). A flat knowledge base article is fine with fixed-size chunks. A hierarchical policy document benefits from parent-child structure. The Strategy Pattern lets the caller pick at runtime without if/else chains.

Why ABC (not Protocol): `BaseChunker` is an abstract base class, not a Protocol. ABCs enforce "you MUST implement chunk()" at instantiation time — you get an error immediately if you forget, not at runtime when a user hits the missing method. For a pipeline component where correctness matters more than flexibility, ABC is the safer choice.

```python
# apps/api/src/rag/chunking.py:43-49
class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, text: str) -> list[ChunkResult]:
        ...
```

Why Factory: `get_chunker("semantic", similarity_threshold=0.3)` lets you create chunkers from config strings. The factory maps strategy names to constructors and passes kwargs through. This means the chunking strategy can come from a config file or environment variable — no code changes for different deployments.

```python
# apps/api/src/rag/chunking.py:423-442
def get_chunker(strategy: ChunkingStrategy | str, **kwargs) -> BaseChunker:
    constructors: dict[str, type[BaseChunker]] = {
        ChunkingStrategy.FIXED_SIZE: FixedSizeChunker,
        ChunkingStrategy.SEMANTIC: SemanticChunker,
        ChunkingStrategy.PARENT_CHILD: ParentChildChunker,
    }
    if strategy_str not in constructors:
        raise ValueError(f"Unknown chunking strategy: {strategy_str!r}.")
    return constructors[strategy_str](**kwargs)
```

**Key implementation details:**

- **FixedSizeChunker** (line 57-106): Character-based with word-boundary respect. Never cuts mid-word. Configurable overlap — overlap is measured in characters but applied at word boundaries. The `overlap_words = max(1, self.overlap // 5)` heuristic assumes ~5 chars/word.

- **SemanticChunker** (line 135-224): The interesting one. Takes an `embed_fn` callable — in production you pass real Azure OpenAI embeddings, in tests you pass a hash-based fake. It embeds ALL sentences at once (batch call, not per-sentence), then walks through consecutive pairs measuring cosine similarity. When similarity drops below the threshold, it starts a new chunk. This means sentences about the same topic cluster together naturally.

  Critical detail: `min_chunk_size` merging (line 204-215). After the initial split, tiny chunks get merged with their neighbors. Without this, a single short sentence between two topic boundaries becomes its own chunk with zero context.

- **ParentChildChunker** (line 232-415): Section-aware. Uses a regex to detect section headers (`Section`, `Article`, `Chapter`, or numbered sections like `1.`). Each section becomes a parent chunk; paragraphs within become children. Children reference their parent via `parent_index`. This lets you retrieve the specific clause but expand to the full section for context.

  Security note (line 239-241): "When used with RBAC, parent clearance = max(child clearance levels). This is enforced at ingestion time, not in this chunker." The chunker doesn't know about security — it just produces structure. RBAC metadata is applied later. This separation keeps the chunker domain-agnostic.

**ChunkResult is a dataclass, not Pydantic**: `ChunkResult` is internal pipeline data that never crosses API boundaries. Using `@dataclass` is lighter than Pydantic for this. The domain `Chunk` model (Pydantic) gets applied at ingestion time when document metadata (document_id, clearance_level, department) is added.

**Alternatives considered:**
- langchain text splitters: Would add a heavy dependency for something that's ~400 lines of straightforward code. Also harder to test — langchain splitters aren't designed for injectable embedding functions.
- spaCy sentence tokenizer: Better sentence boundary detection than regex, but adds a ~500MB model download. The regex approach (line 121: `re.split(r"(?<=[.!?])\s+", text)`) is good enough for logistics contracts where sentences end with periods.

---

### 2. Re-ranking Module: `apps/api/src/rag/reranker.py`

**What it does**: After vector search returns top-20 candidates, the re-ranker reads each query-document pair through a cross-encoder and re-scores them. The correct document moves from rank 4 to rank 1.

**The pattern: ABC + Factory + Circuit Breaker + Composable Wrappers**

This module uses the most patterns in the phase because re-ranking is the most failure-prone component (external model, loading time, potential crashes).

```python
# apps/api/src/rag/reranker.py:57-69
class BaseReranker(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        ...
```

**Five implementations of one interface:**

1. **NoOpReranker** (line 112-125): Pass-through. Returns results in original order. Used as the baseline in benchmarks AND as the fallback when the circuit breaker trips. Not a throwaway — it's a critical production component.

2. **CohereReranker** (line 135-186): Cloud re-ranking via Cohere API. Uses httpx directly, NOT the Cohere SDK. Why? The Cohere Rerank API is literally one POST endpoint. The full SDK would add dependency management complexity for a single HTTP call. The `httpx.AsyncClient` context manager handles connection pooling and cleanup.

3. **LocalCrossEncoderReranker** (line 194-239): The main one. Loads a `sentence-transformers` CrossEncoder model. **Lazy loading** (line 210-217): the model isn't loaded until the first `rerank()` call. This matters because the model is 568M params (~2GB disk) — you don't want to load it at import time if the feature might be disabled.

   The `try/except ImportError` guard at line 27-30 makes `sentence-transformers` optional. If it's not installed, `CrossEncoder = None`, and `_load_model()` raises a clear error with install instructions. This keeps the dependency optional for cloud-only deployments.

   ```python
   # apps/api/src/rag/reranker.py:225-239
   async def rerank(self, query: str, results: list[Any], top_k: int = 5):
       if not results:
           return []
       try:
           if self._model is None:
               self._load_model()
           pairs = [[query, r.content] for r in results]
           raw_scores = self._model.predict(pairs)
           scores = [float(s) for s in raw_scores]
       except RerankerError:
           raise
       except Exception as exc:
           raise RerankerError(f"Local cross-encoder re-ranking failed: {exc}") from exc
       return _to_rerank_results(results, scores, top_k, self.confidence_threshold)
   ```

   The `pairs = [[query, r.content] for r in results]` line is the key insight about cross-encoders. Unlike bi-encoders (which embed query and document separately), cross-encoders process the PAIR together. This is why they're more accurate (the model sees both texts in context) but slower (can't pre-compute document embeddings).

4. **CircuitBreakerReranker** (line 253-313): The resilience layer. This is the **Circuit Breaker pattern** from Michael Nygard's *Release It!*

   Three states:
   - **CLOSED** (normal): Primary reranker handles calls. Track consecutive failures.
   - **OPEN** (tripped): 3+ consecutive failures → all calls go to fallback (NoOp). Timer starts.
   - **HALF_OPEN** (probing): After 60s timeout, try primary once. Success → CLOSED. Failure → OPEN again.

   ```python
   # apps/api/src/rag/reranker.py:263-277
   def __init__(
       self,
       primary: BaseReranker,
       fallback: BaseReranker,
       failure_threshold: int = 3,
       recovery_timeout: float = 60.0,
   ) -> None:
   ```

   Why this matters: without the circuit breaker, if the BGE-m3 model fails to load (disk issue, memory pressure), every single search query would fail. With the circuit breaker, search degrades to "no re-ranking" (you lose the +25.8% quality improvement) but keeps working. The user never sees an error.

   **Composability**: `CircuitBreakerReranker` wraps ANY `BaseReranker` pair. You can chain it: `CircuitBreakerReranker(primary=BGE_m3, fallback=CircuitBreakerReranker(primary=Cohere, fallback=NoOp))`. Two layers of fallback, same interface.

5. **Factory** (`get_reranker()`): Creates rerankers from strategy strings + kwargs.

**RerankResult carries dual scores**: `original_score` (from vector search) and `rerank_score` (from cross-encoder). This enables A/B comparison — you can log both and see exactly how much the re-ranker changed the ranking.

---

### 3. Query Transformation Module: `apps/api/src/rag/query_transform.py`

**What it does**: Transforms user queries before search. Four components: sanitizer (security), HyDE (hypothetical answer), multi-query (reformulations), decomposer (multi-hop splitting), router (classification).

**The pattern: Dependency Injection via Callable**

All transformers accept an `llm_fn: Callable[..., Awaitable[str]]` — a function that takes a prompt and returns a string. NOT a specific LLM client. This is the key design decision.

```python
# apps/api/src/rag/query_transform.py:70
LLMCallable = Callable[[str], Awaitable[str]]
```

Why a callable instead of an LLM client object:
1. **Testing**: Pass `async def mock_llm(prompt, **kw): return "fake answer"` — no mocking library needed.
2. **Framework-agnostic**: Works with langchain, litellm, raw Azure OpenAI SDK, or any other client. The caller adapts their client to this interface, not the other way around.
3. **Composability**: You can wrap the callable with logging, caching, or rate limiting without modifying the transformer.

**QuerySanitizer** (line 73-137): Applied BEFORE any LLM call. Strips 9 injection patterns:

```python
# apps/api/src/rag/query_transform.py:81-91
DEFAULT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above",
    r"new\s+instructions",
    r"system\s*:",
    r"assistant\s*:",
    r"<\s*system\s*>",
    r"you\s+are\s+now",
    r"forget\s+(all\s+)?previous",
    r"disregard\s+(all\s+)?previous",
]
```

Critical design decision (line 96-103): **Custom patterns REPLACE defaults, they don't supplement them.** When you pass `injection_patterns=["my_pattern"]`, you get ONLY that pattern. No hidden defaults. This is intentional — a SQL injection-focused deployment needs completely different patterns than a prompt injection one. Implicit defaults that you can't fully control are a security risk.

Processing order: strip control characters → remove injection patterns → clean double spaces → truncate to max_length. The truncation happens LAST so that injection pattern removal doesn't create a string that's too short.

**QueryRouter** (line not shown but in the file): Classifies queries into 4 categories using an LLM call:
- KEYWORD: exact code lookups → skip transforms, skip re-ranking (fast path)
- STANDARD: normal queries → search + re-rank
- VAGUE: broad queries → HyDE + search + re-rank
- MULTI_HOP: complex queries → decompose + multi-search + merge + re-rank

The router defaults to STANDARD on any failure (malformed JSON, unknown category, LLM error). This is the "safe default" principle — if classification fails, you get the most common path, not a crash.

**HyDETransformer** (line 167-202): Generates a hypothetical answer and returns it for EMBEDDING only. The hypothetical is never shown to the user. In `enhanced_search()`, the HyDE output replaces the embedding vector for dense search, but the ORIGINAL query is still used for BM25 sparse search. This preserves exact-match capability.

---

### 4. Multi-Provider Embeddings: `apps/api/src/rag/embeddings.py`

**What it does**: Abstracts embedding providers behind a common interface. Four providers: Azure OpenAI (production), Cohere (alternative), Nomic (placeholder for air-gapped), Mock (testing).

**The pattern: ABC + Factory + Model Registry + Deterministic Test Doubles**

```python
# apps/api/src/rag/embeddings.py:109-127
class BaseEmbedder(ABC):
    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...
```

Three methods to implement: `embed_query`, `embed_documents`, `dimensions`. That's the contract. Any embedding provider that implements these works in the pipeline.

**Model Registry** (line 67-80): `EMBEDDING_MODELS` is a dict mapping model names to metadata (provider, dimensions, cost). This centralizes model knowledge — when you call `AzureOpenAIEmbedder(model="text-embedding-3-small")`, it looks up dimensions from the registry (1536) rather than hardcoding them. Unknown models default to 1536 (the most common OpenAI dimension).

**MockEmbedder** (line 134-170): This is important to understand. It uses **SHA-256 hash expansion** to create deterministic embeddings:

```python
# apps/api/src/rag/embeddings.py:148-164
def _hash_to_vector(self, text: str) -> list[float]:
    vectors: list[float] = []
    block = 0
    while len(vectors) < self._dimensions:
        h = hashlib.sha256(f"{text}:{block}".encode()).digest()
        for i in range(0, len(h), 4):
            if len(vectors) >= self._dimensions:
                break
            val = struct.unpack(">I", h[i : i + 4])[0]
            normalized = (val / (2**32 - 1)) * 2.0 - 1.0
            vectors.append(normalized)
        block += 1
    return vectors[: self._dimensions]
```

Why SHA-256 instead of `random.random()`:
1. **Deterministic**: Same text → same vector, every time, on any machine. No seed management.
2. **Unique**: Different texts produce different vectors (SHA-256 collision probability is negligible).
3. **Reproducible tests**: No flaky tests from random seed state.

The trade-off: hash-based embeddings don't capture semantic similarity. "dog" and "puppy" produce completely unrelated vectors. This means MockEmbedder is only valid for testing the API contract (correct dimensions, correct types, deterministic behavior). For testing SEARCH QUALITY, you need real embeddings — that's what the live benchmarks are for.

**Backward compatibility** (line 317-331): Phase 1 used `get_embeddings()` which returns a raw langchain `AzureOpenAIEmbeddings` object. Phase 2 adds `get_embedder()` which returns a `BaseEmbedder`. Both coexist — no Phase 1 code had to change.

---

### 5. Enhanced Retrieval Pipeline: `apps/api/src/rag/retriever.py`

**What it does**: Wraps Phase 1's `hybrid_search()` with the new pipeline stages. `enhanced_search()` is the Phase 2 entry point; `hybrid_search()` is preserved unchanged for backward compatibility.

**The pattern: Pipeline/Chain + Config Object + Graceful Degradation**

```python
# apps/api/src/rag/retriever.py:131-145
@dataclass
class RetrievalPipelineConfig:
    reranker: BaseReranker | None = None
    query_router: object | None = None
    hyde_transformer: object | None = None
    multi_query_transformer: object | None = None
    query_decomposer: object | None = None
    sanitizer: object | None = None
    rerank_top_k: int = 20
```

Every field defaults to `None`. Set it to skip the stage. This means you can use `enhanced_search()` with zero pipeline components and it behaves identically to `hybrid_search()` (just returns `EnhancedSearchResult` instead of `SearchResult`).

**Why `object` type hints instead of the actual types**: Avoids circular imports between `retriever.py` and `query_transform.py`. Both modules define types that reference each other's concepts. Using `object` + duck typing at runtime avoids the import cycle. The tests verify the correct interfaces are called.

**Deduplication** (line 167-175): When multi-query runs 3 reformulations, they might return the same document. `_deduplicate_results` keeps the highest-scoring instance per `(document_id, chunk_index)` pair:

```python
# apps/api/src/rag/retriever.py:167-175
def _deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: dict[tuple[str, int], SearchResult] = {}
    for r in results:
        key = (r.document_id, r.chunk_index)
        if key not in seen or r.score > seen[key].score:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)
```

---

### 6. Evaluation Framework: `tests/evaluation/`

**What it does**: 52 ground truth queries across 10 categories, shared corpus, metric functions — all the infrastructure for benchmarking retrieval quality.

**Key files:**
- `ground_truth.py`: 52 queries, each with category, relevant_doc_ids, description. Self-validating: asserts 50+ queries and 10 categories on import.
- `corpus.py`: Canonical 12-document corpus shared between all benchmarks.
- `metrics.py`: `compute_precision_at_k`, `compute_recall_at_k`, `compute_mrr` — zero external dependencies.
- `test_retrieval_quality.py`: 30 tests validating the metrics themselves and the ground truth dataset.

**Why this is separate from unit tests**: The evaluation framework tests RETRIEVAL QUALITY (does the right document rank first?), not code correctness (does the function return the right type?). Different concern, different directory, different test philosophy.

---

### 7. Benchmark Scripts: `scripts/`

Six benchmark scripts, all runnable from the command line:
- `benchmark_chunking.py`: 6 configs, clause integrity metric
- `benchmark_embeddings.py`: Mock + live modes, 52-query ground truth
- `benchmark_retrieval.py`: End-to-end pipeline, per-category breakdown
- `benchmark_hyde.py`: HyDE before/after comparison
- `benchmark_reranking.py`: Original 3-model comparison
- `benchmark_reranking_v2.py`: Expanded 6-model comparison on production corpora

Scripts vs tests: Scripts run LIVE (real Azure OpenAI, real Qdrant). Tests run with mocks. Scripts produce benchmark numbers for documentation. Tests prove code correctness. Both are necessary, neither replaces the other.

---

## Key Decisions Explained

### Decision 1: BGE-m3 over Cohere Rerank (and 5 other models)

- **The choice**: BGE-reranker-v2-m3 (568M params, local, multilingual)
- **The alternatives**: TinyBERT (14.5M, fast, English-only), ms-marco-MiniLM (33M, English-only), mmarco-mMiniLM (118M, "multilingual" but broken), BGE-base (278M, neutral), BGE-large (560M, strong), Cohere Rerank v3 (cloud, not benchmarked)
- **The reasoning**: 6-model benchmark on 2 production Polish corpora (57 docs, 5-9K chars). Only BGE-m3 (+25.8%) and BGE-large (+23.5%) improve retrieval. mmarco-multi HURTS (-6.6%) despite "multilingual" label — translated training data ≠ multilingual understanding. BGE-m3's dedicated m3 training objective (multi-lingual, multi-functionality, multi-granularity) is what makes the difference.
- **The trade-off**: ~480ms latency per query at 7K char docs. Typo handling slightly worse (-0.125 MRR on typo category).
- **When to revisit**: When Cohere multilingual benchmark results are available, or when latency budget is under 200ms.
- **Interview version**: "We benchmarked 6 cross-encoder re-ranking models. A model labeled 'multilingual' actually degraded search by 6.6% — its training data was machine-translated, which doesn't teach cross-lingual understanding. Only 2 of 6 models helped. The architecture uses an ABC so switching models is a config string change."

### Decision 2: Dense-only over Hybrid (reversing Phase 1)

- **The choice**: Dense-only search (MRR=0.885) as default
- **The alternatives**: Hybrid RRF (MRR=0.847, was the Phase 1 recommendation)
- **The reasoning**: At 26 queries, hybrid scored 24/26 vs dense 23/26. At 52 queries across 10 categories, dense MRR=0.885 beats hybrid MRR=0.847. BM25 helps on exact alphanumeric codes (1.000 MRR) but adds noise everywhere else.
- **The trade-off**: Exact code searches (CTR-2024-001) rank slightly lower (0.760 vs 1.000 MRR)
- **When to revisit**: When >25% of queries are exact alphanumeric codes, add BM25 back
- **Interview version**: "Our Phase 1 recommendation was hybrid search. Phase 2 doubled the test set and the conclusion reversed — BM25 adds noise when query diversity increases. The lesson is that benchmark conclusions are scale-dependent, and you should re-validate when your test set grows."

### Decision 3: text-embedding-3-small over large

- **The choice**: text-embedding-3-small (1536d, $0.02/1M tok, MRR=0.885)
- **The alternatives**: text-embedding-3-large (3072d, $0.13/1M tok, MRR=0.856)
- **The reasoning**: Large model is 6.5x more expensive AND performs worse (-0.029 MRR) at 12-doc corpus scale. Higher dimensions don't help when there's not enough semantic overlap in the corpus.
- **The trade-off**: Potentially worse at 1000+ semantically similar documents
- **When to revisit**: Corpus exceeds 1000+ docs with high semantic overlap
- **Interview version**: "We confirmed that the cheaper embedding model actually performs better on our corpus. Higher dimensions only matter when you have thousands of similar documents — at our scale, the extra separation isn't useful. We save 6.5x on embedding costs for better quality."

### Decision 4: Skip HyDE at small corpus scale

- **The choice**: HyDE disabled by default
- **The alternatives**: HyDE enabled for vague queries (as the spec originally planned)
- **The reasoning**: HyDE hurts across all 4 tested categories. Vague: -20.9% R@5. Exact codes: -25.0% MRR. At 12-doc scale, the hypothetical answer is less specific than the original query.
- **The trade-off**: Vague queries don't get the benefit of better embedding targets
- **When to revisit**: Corpus >500 semantically similar documents where direct queries can't distinguish candidates
- **Interview version**: "We tested HyDE — generating hypothetical answers to improve embedding quality. It hurt across every category because at our corpus size, direct queries already find the right document. The hypothetical adds semantic noise. We kept it in the architecture but disabled it, with a documented switching condition for larger corpora."

### Decision 5: QuerySanitizer custom patterns replace defaults

- **The choice**: When you pass custom injection patterns, they REPLACE the defaults entirely
- **The alternatives**: Supplement (custom + defaults combined)
- **The reasoning**: Security is a domain where implicit behavior is dangerous. If a deployment needs SQL injection patterns instead of prompt injection patterns, hidden default patterns would give a false sense of security while missing the actual threats. Explicit > implicit.
- **The trade-off**: If you pass custom patterns, you must include all the patterns you want. No free defaults.
- **Interview version**: "We designed the query sanitizer so custom patterns replace defaults rather than supplement them. In security, implicit behavior is dangerous — a deployment targeting SQL injection needs completely different patterns than one targeting prompt injection. We chose explicit control over convenience."

### Decision 6: Dataclass vs Pydantic for internal pipeline data

- **The choice**: `@dataclass` for ChunkResult, RerankResult, TransformResult. Pydantic for EnhancedSearchResult.
- **The reasoning**: Internal pipeline data that never crosses API boundaries doesn't need Pydantic's validation overhead. EnhancedSearchResult DOES cross API boundaries (it's the return type of `enhanced_search()` which may be serialized in API responses), so it uses Pydantic for validation + JSON serialization.
- **Interview version**: "We use Pydantic at system boundaries where data needs validation and serialization, and plain dataclasses for internal pipeline objects. The boundary is clear: if it crosses an API boundary, it's Pydantic. If it's internal plumbing, it's a dataclass."

---

## Patterns & Principles Used

### 1. Abstract Base Class (ABC) + Factory

- **What**: Define an interface (ABC), implement it multiple times, create instances via factory function
- **Where**: `BaseChunker` + `get_chunker()` (chunking.py), `BaseReranker` + `get_reranker()` (reranker.py), `BaseEmbedder` + `get_embedder()` (embeddings.py), `BaseQueryTransformer` (query_transform.py)
- **Why**: Config-driven component selection. Deploy different implementations without code changes. Type safety at instantiation time (ABC raises if you forget a method).
- **When NOT to use**: When you have exactly one implementation and no plans for alternatives. Over-abstracting a single class wastes time.

### 2. Circuit Breaker

- **What**: Track consecutive failures, trip after threshold, use fallback, probe to recover
- **Where**: `CircuitBreakerReranker` in reranker.py:253-313
- **Why**: The re-ranking model is 568M params loaded from disk. If it fails (disk error, OOM), you don't want every query to fail. The circuit breaker trips after 3 failures and uses NoOp (no re-ranking) as fallback. Search still works, quality degrades gracefully.
- **When NOT to use**: When the component is cheap to retry (e.g., a fast API call with retries). Circuit breakers add state management complexity — only worth it for expensive-to-fail components.

### 3. Dependency Injection via Callable

- **What**: Accept a function as a parameter instead of a specific client object
- **Where**: All transformers accept `llm_fn: Callable[..., Awaitable[str]]`, SemanticChunker accepts `embed_fn: Callable[[list[str]], list[list[float]]]`
- **Why**: Testing becomes trivial — pass `async def mock(prompt): return "fake"`. Framework-agnostic — works with any LLM client. No mocking libraries needed.
- **When NOT to use**: When the dependency has a complex interface with multiple methods. Callables are great for single-function interfaces.

### 4. Deterministic Test Doubles

- **What**: Test fakes that produce the same output for the same input, every time
- **Where**: `MockEmbedder` (embeddings.py:134-170) uses SHA-256 hash expansion
- **Why**: Reproducible tests. No flaky failures from random seeds. Same text → same vector on any machine. 265 unit tests run without any API credentials.
- **When NOT to use**: When you need semantic similarity in tests (e.g., testing that "dog" and "puppy" rank similarly). Hash-based embeddings don't capture semantics.

### 5. Graceful Degradation

- **What**: When a component fails, the system continues with reduced capability instead of crashing
- **Where**: `enhanced_search()` catches transformer failures and falls back to original query. Circuit breaker catches reranker failures and uses NoOp. Router failure defaults to STANDARD.
- **Why**: In a 5-stage pipeline, any stage can fail. If each failure crashes the pipeline, availability is the product of individual reliabilities. Graceful degradation means the user gets slightly worse results instead of an error page.

### 6. Pipeline Config Object

- **What**: A dataclass where each field represents an optional pipeline stage
- **Where**: `RetrievalPipelineConfig` in retriever.py:131-145
- **Why**: Composable pipeline definition. Set any field to None to skip that stage. No if/else chains in the pipeline — just null checks. Easy to test specific combinations.

---

## Benchmark Results & What They Mean

### Search Mode (52 queries, 12 docs, live Azure OpenAI)
- Dense MRR=0.885 > Hybrid MRR=0.847 > BM25 MRR=0.770
- **Architecture decision**: Default to dense-only. BM25 only helps exact codes (1.000 vs 0.760). Add BM25 when >25% of queries are exact alphanumeric lookups.
- **Boundary**: Negation MRR=0.458. Embeddings can't negate. This isn't fixable in retrieval — it's an agent reasoning problem (Phase 3).

### Re-ranking (52 queries, 6 models, 57 docs per corpus, 5-9K chars)
- 4 of 6 models hurt or add nothing. Only BGE-m3 (+25.8%) and BGE-large (+23.5%) help.
- **Architecture decision**: BGE-m3 as default, BGE-large as backup, circuit breaker to NoOp on failure.
- **Boundary**: mmarco-multi HURTS (-6.6%) despite "multilingual" label. Translation of training data ≠ multilingual understanding.

### Embedding Models (52 queries, 12 docs, live)
- Small MRR=0.885, Large MRR=0.856. Large is 6.5x more expensive AND worse.
- **Architecture decision**: Use small until corpus exceeds 1000+ semantically similar docs.
- **Boundary**: At what corpus size does large start helping? Unknown — mapped to Phase R.

### HyDE (4 categories, 12 docs, live gpt-5-mini)
- Hurts across all tested categories. Vague: -20.9% R@5. Exact codes: -25.0% MRR.
- **Architecture decision**: Disabled by default. Switching condition: 500+ semantically similar docs.
- **Boundary**: Only category with mixed results is negation (+11.1% R@5 but -7.1% MRR).

### Chunking (6 docs, 8 strategies, live embeddings)
- Semantic(t=0.3): 50 chunks avg 215 chars, 8/8 clauses intact. FixedSize(80): 6/8 clauses intact.
- **Architecture decision**: Semantic chunking for contracts (clause integrity). FixedSize for unstructured text.
- **Boundary**: Mock embeddings make t=0.3 and t=0.5 produce identical output. You MUST use real embeddings to benchmark semantic chunking.

---

## Test Strategy

- **290 unit tests**: Test each component in isolation. ALL external dependencies mocked (LLM calls, embedding calls, Qdrant, API clients). Run in <5 seconds with zero credentials.
- **7 integration tests**: Test Qdrant search with real embeddings (needs Docker running).
- **10 e2e tests**: Full pipeline tests with live Azure OpenAI (marked `live`, excluded from default run).
- **30 evaluation tests**: Test the metrics themselves and validate the ground truth dataset structure.

**What the tests prove**:
- Injection patterns are stripped BEFORE any LLM call — "ignore previous instructions" never reaches the model
- Circuit breaker transitions through all states correctly and always degrades to fallback, never crashes
- Re-ranker failure returns un-reranked results, not an error
- Router failure defaults to STANDARD path, not a crash
- HyDE replaces the EMBEDDING query but NOT the BM25 query — exact-match capability is preserved
- Multi-query deduplication keeps the HIGHEST score per document, not the first seen

**What ISN'T tested** (mapped to future):
- Adversarial injection bypass (unicode confusables, encoding tricks) → Phase 10
- Cross-encoder behavior on Polish-English code-switching → Phase 5
- Latency vs document length curve (only 2 data points) → Phase R
- HyDE on remaining 6 categories → Phase R

---

## File Map

| File | Purpose | Key Patterns | ~Lines |
|------|---------|-------------|--------|
| `apps/api/src/rag/chunking.py` | 3 chunking strategies | Strategy, ABC, Factory | 443 |
| `apps/api/src/rag/reranker.py` | 5 reranker implementations | ABC, Factory, Circuit Breaker, Composable Wrapper | 340 |
| `apps/api/src/rag/query_transform.py` | Sanitizer, HyDE, MultiQuery, Decomposer, Router | ABC, DI via Callable, Fail-safe defaults | 410 |
| `apps/api/src/rag/embeddings.py` | 4 embedding providers | ABC, Factory, Model Registry, Deterministic Doubles | 332 |
| `apps/api/src/rag/retriever.py` | Enhanced pipeline wrapping Phase 1 | Pipeline Config, Graceful Degradation | 262 |
| `apps/api/src/domain/document.py` | EnhancedSearchResult model | Pydantic at API boundary | 18 (added) |
| `tests/unit/test_chunking.py` | 48 tests | | 618 |
| `tests/unit/test_reranker.py` | 42 tests | | 840 |
| `tests/unit/test_query_transform.py` | 68 tests | | 724 |
| `tests/unit/test_embeddings.py` | 52 tests | | 633 |
| `tests/unit/test_enhanced_retriever.py` | 25 tests | | 880 |
| `tests/evaluation/test_retrieval_quality.py` | 30 tests | | 262 |
| `tests/evaluation/ground_truth.py` | 52 queries, 10 categories | | 418 |
| `tests/evaluation/corpus.py` | Shared 12-doc corpus | | 239 |
| `tests/evaluation/metrics.py` | P@k, R@k, MRR functions | | 155 |
| `scripts/benchmark_reranking_v2.py` | 6-model comparison | | 495 |
| `docs/adr/004-chunking-strategy.md` | Semantic over fixed-size | | 37 |
| `docs/adr/005-reranking-layer.md` | BGE-m3 selection, 6-model data | | 143 |
| `docs/adr/006-embedding-model-choice.md` | Small over large, switch conditions | | 69 |

---

## Interview Talking Points

1. **"We benchmarked 6 re-ranking models and proved that vendor labels are unreliable."** A model labeled "multilingual" degraded search by 6.6%. Its training data was machine-translated, not cross-lingually trained. We'd revisit if Cohere's multilingual reranker benchmarks become available.

2. **"Our Phase 1 conclusion was wrong at Phase 2 scale."** Hybrid search won at 26 queries, lost at 52. Benchmark conclusions are scale-dependent. We re-validate foundational assumptions whenever the test set grows significantly.

3. **"We disabled a feature we built because the evidence said it hurt."** HyDE hurts at small corpus scale. We kept it in the architecture with a documented switching condition (500+ similar docs) but disabled it by default. Architect decision: knowing when NOT to use a technique is as important as building it.

4. **"Every component implements an ABC with a factory."** Switching embedding providers is 3 methods + 1 registry entry. Switching re-rankers is a config string change. The architecture is designed for the swap, not just for today's choice.

5. **"The circuit breaker means search never crashes."** The re-ranking model is 568M params. If it fails to load, the circuit breaker trips after 3 failures and falls back to no re-ranking. The user gets slightly worse results instead of an error page.

6. **"Mock embeddings use SHA-256, not random."** Deterministic test doubles — same text produces the same vector on any machine. 265 unit tests run without API credentials in under 5 seconds. But hash-based embeddings don't capture semantics, so they're only valid for testing the API contract, not search quality.

7. **"The cheaper embedding model actually performs better."** text-embedding-3-small (1536d, $0.02/1M tok) beats large (3072d, $0.13/1M tok) by +0.029 MRR. Higher dimensions only help with 1000+ semantically similar documents. Until then, you're paying 6.5x for worse results.

8. **"Security sanitization happens first, always."** QuerySanitizer strips 9 injection patterns before any LLM call. Custom patterns replace defaults entirely — no hidden behavior in security code. The sanitizer is composable and automatically wired into every transformer.

---

## What I'd Explain Differently Next Time

**Start with the pipeline diagram, then zoom into components.** When explaining Phase 2, the first thing people need is "query goes in, stages happen in order, results come out." Then you can zoom into any stage. Starting with individual components (chunking, re-ranking) loses the forest for the trees.

**The ABC + Factory pattern is really just "interface + config-driven creation."** Don't over-explain the pattern — just say "every embedding provider implements 3 methods, a factory creates them from config strings, so swapping providers is a config change, not a code change."

**The mock embedder's SHA-256 trick is the thing people remember.** It's a simple idea (hash text → deterministic vector) but it's the one that makes people go "oh that's clever." Lead with it when discussing testing strategy.

**The mmarco-multi finding is the strongest talking point.** "A model labeled multilingual made our multilingual search worse" is counterintuitive and memorable. It demonstrates that benchmarking beats vendor trust.

**Benchmark reversals are uncomfortable but they're the point.** Phase 1 said hybrid, Phase 2 said dense-only. This isn't a mistake — it's evidence that conclusions are scale-dependent. Frame it as a positive: "our process caught its own earlier recommendation being wrong."
