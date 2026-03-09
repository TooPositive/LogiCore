# Phase 1 Technical Recap: Corporate Brain (RAG + RBAC)

## What This Phase Does (Business Context)

Logistics companies have mountains of unstructured documents (HR manuals, contracts, safety protocols) that employees can't find. Phase 1 builds a search system where: (a) employees find documents regardless of language, typos, or terminology mismatches, and (b) the LLM never sees documents outside the user's authorization level. The RBAC constraint is enforced at the database query level, not post-retrieval.

## Architecture Overview

```
User Query (e.g. "towary niebezpieczne")
  │
  ▼
POST /api/v1/search ─────────────────────── apps/api/src/api/v1/search.py
  │
  ├─ resolve_user_context(user_id) ───────── apps/api/src/security/rbac.py
  │    └─ Returns: UserContext(clearance=1, departments=["warehouse"])
  │
  ├─ build_qdrant_filter(user) ───────────── apps/api/src/security/rbac.py
  │    └─ Returns: Filter(dept IN [...], clearance <= N)
  │
  └─ hybrid_search(query, user, ...) ─────── apps/api/src/rag/retriever.py
       │
       ├─ embed_fn(query) ────────────────── apps/api/src/rag/embeddings.py
       │    └─ Returns: [float] * 1536 (dense vector)
       │
       ├─ text_to_sparse_vector(query) ───── apps/api/src/rag/sparse.py
       │    └─ Returns: SparseVector(indices, values) (BM25 TF)
       │
       └─ qdrant.query_points(
              prefetch=[dense, bm25],
              query=FusionQuery(RRF),      ← server-side fusion
              query_filter=rbac_filter      ← RBAC applied HERE
          )
          └─ Returns: [SearchResult(...)]


POST /api/v1/ingest ──────────────────────── apps/api/src/api/v1/ingest.py
  │
  ├─ Validate file_path against ALLOWED_DATA_DIR (path traversal protection)
  │
  ├─ chunk_text(text, 512, 50) ───────────── apps/api/src/rag/ingestion.py
  │    └─ Returns: ["chunk1", "chunk2", ...]
  │
  ├─ embed_fn(chunks) ────────────────────── apps/api/src/rag/embeddings.py
  │
  ├─ text_to_sparse_vector(chunk) ────────── apps/api/src/rag/sparse.py (per chunk)
  │
  └─ qdrant.upsert(points=[
         PointStruct(vector={"dense": [...], "bm25": SparseVector(...)},
                     payload={content, document_id, department_id,
                              clearance_level, source_file, chunk_index})
     ])
```

Data model: `apps/api/src/domain/document.py`
Collection schema: `apps/api/src/infrastructure/qdrant/collections.py`

## Components Built

### 1. RBAC Filter: `apps/api/src/security/rbac.py`

**What it does**: Resolves user identity to clearance + departments, builds a Qdrant filter that constrains all queries. The LLM never sees unauthorized documents.

**The pattern**: **Fail-Closed Guard**. Rather than a permissive filter that might leak data, the system refuses to build a filter at all if the user's department list is empty. This prevents MatchAny([]) from potentially matching everything in Qdrant (undefined behavior that varies across versions).

**Key code walkthrough**:

```python
# apps/api/src/security/rbac.py:54-81
def build_qdrant_filter(user: UserContext) -> Filter:
    # FAIL CLOSED: empty departments = refuse to query, not "query everything"
    # Why? MatchAny([]) behavior is undefined in Qdrant.
    # Some versions match all, some match none. Both are wrong.
    if not user.departments:
        raise ValueError(
            f"User {user.user_id} has empty departments list. "
            "Refusing to build filter — MatchAny([]) could bypass RBAC."
        )

    return Filter(
        must=[
            # TWO conditions, both MUST match:
            # 1. Document's department must be in user's department list
            FieldCondition(key="department_id", match=MatchAny(any=user.departments)),
            # 2. Document's clearance must be <= user's clearance level
            FieldCondition(key="clearance_level", range=Range(lte=user.clearance_level)),
        ]
    )
```

**Why it matters**: If you skip the empty-list guard, a user with no departments (DB migration error, new user not yet assigned) could see everything or nothing depending on the Qdrant version. Both are security failures. The guard makes the failure mode explicit and auditable.

**Alternatives considered**:
- **Post-retrieval filtering**: The LLM already saw the unauthorized documents. A prompt injection in any retrieved doc could leak the content. Rejected.
- **Prompt-level RBAC** ("Do not reference documents above clearance level X"): Bypassable via prompt injection. Rejected.
- **Separate collections per clearance level**: Would work but creates O(clearance_levels * departments) collections. Payload filtering on a single collection is simpler and Qdrant handles it with indexed fields.

### 2. Hybrid Search Retriever: `apps/api/src/rag/retriever.py`

**What it does**: Executes RBAC-filtered search in one of three modes (dense_only, sparse_only, hybrid). Hybrid uses Qdrant's prefetch + Reciprocal Rank Fusion server-side.

**The pattern**: **Strategy Pattern via enum** + **Dependency Injection via callable**. The `mode` enum selects the search strategy. The `embed_fn` callable is injected rather than importing a specific embedding client. This means tests can inject mocks, Phase 2 can inject a different embedder, and the retriever never knows or cares which provider generated the vector.

**Key code walkthrough**:

```python
# apps/api/src/rag/retriever.py:44-51
async def hybrid_search(
    query: str,
    user: UserContext,
    qdrant_client: AsyncQdrantClient,
    embed_fn: Callable[[str], Coroutine],  # <-- DI: any async fn that returns a vector
    top_k: int = 5,
    mode: SearchMode = SearchMode.HYBRID,  # <-- Strategy: enum selects behavior
) -> list[SearchResult]:
```

The hybrid path is the interesting one:

```python
# apps/api/src/rag/retriever.py:87-109
else:  # HYBRID — prefetch both, fuse with RRF
    query_vector = await embed_fn(query)        # dense embedding
    sparse_vector = text_to_sparse_vector(query) # BM25 term frequencies

    response = await qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            # Both branches are executed in parallel by Qdrant
            models.Prefetch(query=query_vector, using="dense", limit=prefetch_limit),
            models.Prefetch(query=sparse_vector, using="bm25", limit=prefetch_limit),
        ],
        # RRF fusion happens SERVER-SIDE — no manual rank merging
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=rbac_filter,  # RBAC applied to BOTH branches + fused result
        limit=top_k,
        with_payload=True,
    )
```

**Why `prefetch_limit = top_k * 4`**: Over-fetching gives the RRF fusion more candidates to rank. If you only prefetch top_k from each branch, the fusion has at most 2*top_k candidates, and rare matches from one branch might be lost. 4x gives enough headroom.

**Why it matters**: Without DI on `embed_fn`, every test needs Azure OpenAI credentials or a complex mock setup. With it, unit tests inject `AsyncMock(return_value=[0.1]*1536)` and integration tests inject `MockEmbedder`. The retriever code is identical in all cases.

**Alternatives considered**:
- **Alpha-weighted blending** (spec'd): Manual blending with `alpha` param. Qdrant native RRF replaces this — simpler, server-side, no manual rank computation.
- **Application-side fusion**: Fetch dense results and sparse results separately, merge in Python. More code, more latency (serial queries), more bugs. Qdrant does it in one round-trip.

### 3. Sparse Vector Encoder: `apps/api/src/rag/sparse.py`

**What it does**: Converts text to a BM25-style sparse vector using term frequency + hash-based index mapping. Qdrant applies IDF weighting server-side.

**The pattern**: **Lightweight Local Implementation** over external dependency. SPLADE would give learned term expansion but requires a 400MB+ transformer model download. For Phase 1, TF + Qdrant IDF achieves the core goal (exact keyword matching for codes like ISO-9001) without the dependency.

**Key code walkthrough**:

```python
# apps/api/src/rag/sparse.py:26-29
# Tokenizer preserves hyphenated codes — "ISO-9001" stays as one token
_TOKEN_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?", re.IGNORECASE)
_VOCAB_SIZE = 2**16  # 65536 buckets

# apps/api/src/rag/sparse.py:37-62
def text_to_sparse_vector(text: str) -> SparseVector:
    tokens = tokenize(text)
    if not tokens:
        return SparseVector(indices=[], values=[])

    tf = Counter(tokens)

    # Hash collision handling: if two tokens hash to the same bucket,
    # sum their counts. Rare with 65536 buckets, but Qdrant requires
    # unique indices, so collisions must be merged.
    index_map: dict[int, float] = {}
    for token, count in tf.items():
        idx = hash(token) % _VOCAB_SIZE
        index_map[idx] = index_map.get(idx, 0.0) + float(count)

    return SparseVector(indices=list(index_map.keys()), values=list(index_map.values()))
```

**Why it matters**: The tokenizer regex keeps "ISO-9001" and "CTR-2024-001" as single tokens. A naive split on `-` would break these into fragments, losing the exact-match capability that justifies BM25 in the pipeline.

**Hash collision fix**: Phase 2 discovered that the original implementation (before the fix) could produce duplicate indices in the SparseVector, causing Qdrant to reject the upsert. The `index_map` dict with summing handles this correctly.

### 4. Document Ingestion: `apps/api/src/rag/ingestion.py`

**What it does**: Chunks text into overlapping segments, embeds them, generates BM25 sparse vectors, and upserts into Qdrant with RBAC metadata.

**The pattern**: **Pipeline with injected steps**. `embed_fn` is injected (same pattern as retriever). Chunking parameters are configurable. Each point gets both dense AND sparse vectors plus full RBAC metadata.

**Key code walkthrough**:

```python
# apps/api/src/rag/ingestion.py:13-55
def chunk_text(text: str, chunk_size: int = 512, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks at word boundaries."""
    # Character-based with word-boundary awareness
    # Advance = chunk_words - overlap_words to create overlap
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        # ... accumulate words until chunk_size chars reached
        overlap_words = max(1, overlap // 5)  # approximate overlap in words
        advance = max(1, (end - start) - overlap_words)
        start += advance
```

**Design choice — character-based vs token-based**: Phase 1 uses 512 chars because it's simpler and avoids a tiktoken dependency. The trade-off: inconsistent semantic density per chunk (a chunk of short words has fewer tokens than one of long words). Phase 2 benchmarks this properly with three strategies (FixedSize, Semantic, ParentChild).

```python
# apps/api/src/rag/ingestion.py:78-98
# Each Qdrant point gets BOTH vector types + full RBAC payload
points.append(
    models.PointStruct(
        id=point_id,
        vector={
            "dense": embedding,           # 1536-d from text-embedding-3-small
            "bm25": sparse,               # sparse TF vector for keyword matching
        },
        payload={
            "content": chunk,             # for display
            "document_id": document_id,   # for dedup/linking
            "department_id": department_id, # RBAC
            "clearance_level": clearance_level, # RBAC
            "source_file": source_file,   # provenance
            "chunk_index": i,             # ordering
        },
    )
)
```

### 5. Collection Schema: `apps/api/src/infrastructure/qdrant/collections.py`

**What it does**: Creates the Qdrant collection with dense + sparse vector configs and indexed RBAC payload fields.

**The pattern**: **Idempotent Setup** — checks if collection exists before creating. Safe to call multiple times.

**Key code walkthrough**:

```python
# apps/api/src/infrastructure/qdrant/collections.py:19-49
await client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config={
        "dense": models.VectorParams(
            size=dense_size,              # 1536 for small, 3072 for large
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(
            modifier=models.Modifier.IDF,  # Qdrant applies IDF server-side
        ),
    },
)

# Payload indexes enable fast RBAC filtering without full scan
await client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="department_id",
    field_schema=models.PayloadSchemaType.KEYWORD,  # indexed for MatchAny
)
await client.create_payload_index(
    collection_name=COLLECTION_NAME,
    field_name="clearance_level",
    field_schema=models.PayloadSchemaType.INTEGER,   # indexed for Range(lte=)
)
```

**Why `Modifier.IDF`**: Without IDF, the sparse vector is just raw term frequencies. With IDF, Qdrant downweights common terms and upweights rare ones server-side. This means the client (sparse.py) only needs to compute TF — no corpus-level IDF calculation required.

### 6. Embedding Module: `apps/api/src/rag/embeddings.py`

**What it does**: Multi-provider embedding system with ABC + Factory pattern. Supports Azure OpenAI, Cohere, and Mock providers. Phase 1 backward compatibility preserved via `get_embeddings()`.

**The pattern**: **ABC + Factory + Deterministic Test Double**.

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

The Factory:
```python
# apps/api/src/rag/embeddings.py:285-309
def get_embedder(provider: str | EmbeddingProvider, **kwargs) -> BaseEmbedder:
    constructors: dict[str, type[BaseEmbedder]] = {
        EmbeddingProvider.AZURE_OPENAI: AzureOpenAIEmbedder,
        EmbeddingProvider.COHERE: CohereEmbedder,
        EmbeddingProvider.MOCK: MockEmbedder,
    }
    return constructors[provider_str](**kwargs)
```

The Deterministic Test Double:
```python
# apps/api/src/rag/embeddings.py:134-170
class MockEmbedder(BaseEmbedder):
    """Same text always produces the same vector. Different texts produce
    different vectors. No external dependencies."""

    def _hash_to_vector(self, text: str) -> list[float]:
        vectors = []
        block = 0
        while len(vectors) < self._dimensions:
            h = hashlib.sha256(f"{text}:{block}".encode()).digest()
            for i in range(0, len(h), 4):
                val = struct.unpack(">I", h[i : i + 4])[0]
                normalized = (val / (2**32 - 1)) * 2.0 - 1.0
                vectors.append(normalized)
            block += 1
        return vectors[:self._dimensions]
```

**Why MockEmbedder uses SHA-256 instead of random**: Tests must be deterministic. If you use random vectors, search results change between runs and you can't write assertions about ranking. SHA-256 hash of the text + block counter gives consistent vectors across test runs.

**Why the legacy `get_embeddings()` wrapper exists**: Phase 1 code imports `get_embeddings()` which returns a langchain `AzureOpenAIEmbeddings` directly. Phase 2 introduced `get_embedder()` (factory pattern) but Phase 1 endpoints still call the legacy wrapper. Both work; the legacy one is for backward compatibility.

### 7. API Endpoints: `apps/api/src/api/v1/search.py` + `ingest.py`

**What search.py does**: Resolves user, gets Qdrant client and embeddings, calls `hybrid_search()`, returns results.

```python
# apps/api/src/api/v1/search.py:14-32
@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    try:
        user = await resolve_user_context(request.user_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))  # Unknown user = 403, not 404

    qdrant = await get_qdrant_client()
    embeddings = get_embeddings()

    results = await hybrid_search(
        query=request.query,
        user=user,
        qdrant_client=qdrant,
        embed_fn=embeddings.aembed_query,  # langchain's async embed method
        top_k=request.top_k,
    )
    return SearchResponse(results=results, query=request.query)
```

**What ingest.py does**: Path traversal protection + chunk + embed + upsert.

```python
# apps/api/src/api/v1/ingest.py:17-29
ALLOWED_DATA_DIR = Path(__file__).resolve().parents[5] / "data"

@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    file_path = Path(request.file_path).resolve()

    # Zero-trust: reject paths outside the allowed data directory
    if not str(file_path).startswith(str(ALLOWED_DATA_DIR.resolve())):
        raise HTTPException(status_code=403, detail="File path outside allowed data directory")
```

**Why `.resolve()` before comparison**: Without resolving, `../../etc/passwd` wouldn't be caught by a naive string prefix check. `.resolve()` canonicalizes the path, collapsing `..` traversals.

### 8. Domain Models: `apps/api/src/domain/document.py`

**The pattern**: **Pydantic v2 models with field constraints**. Clearance levels are bounded 1-4 at the model level via `Field(ge=1, le=4)`. Invalid clearance values are rejected before they ever reach RBAC logic. Same with `chunk_index: int = Field(ge=0)` and `top_k: int = Field(default=5, ge=1, le=50)`.

```python
class UserContext(BaseModel):
    user_id: str
    clearance_level: int = Field(ge=1, le=4)  # Pydantic rejects 0, -1, 5
    departments: list[str]
```

**Why this matters**: The `build_qdrant_filter()` guard against empty departments is the second defense. The first is Pydantic's type validation. A clearance_level of 0 never reaches RBAC because Pydantic rejects it at deserialization. Defense in depth without extra code.

### 9. Qdrant Client Factory: `apps/api/src/infrastructure/qdrant/client.py`

**The pattern**: **Async Singleton**. Uses a module-level `_client` variable to avoid creating multiple connections. Thread-safe enough for the Phase 1 demo (single async event loop).

```python
_client: AsyncQdrantClient | None = None

async def get_qdrant_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    return _client
```

**Why singleton**: Qdrant client holds a connection pool. Creating a new client per request would exhaust connections. One client, reused across requests.

## Key Decisions Explained

### Decision 1: Qdrant Native BM25 Instead of SPLADE

- **The choice**: Use Qdrant's built-in IDF modifier with raw term frequency sparse vectors
- **The alternatives**: SPLADE (learned sparse representation), no sparse vectors (dense only)
- **The reasoning**: SPLADE needs a 400MB+ transformer model download and inference step. For Phase 1, BM25 with Qdrant IDF achieves the core goal: exact keyword matching for codes like ISO-9001 and CTR-2024-001. BM25 carries ~10% of the retrieval value — don't over-engineer it when embeddings handle 90%.
- **The trade-off**: No learned term expansion. BM25 can't match "car" when the document says "automobile." That's fine because dense embeddings handle this.
- **When to revisit**: If you need BM25 to do semantic expansion (rare — that's what embeddings are for), or if you move to an air-gapped setup where embeddings aren't available.
- **Interview version**: "We used Qdrant's native BM25 with IDF instead of SPLADE because SPLADE requires a 400MB transformer model download for a capability that provides maybe 10% of the retrieval value. The embeddings handle synonyms, cross-lingual, and typos. BM25's job is exact code matching — term frequency with server-side IDF is sufficient for that."

### Decision 2: RRF Fusion Instead of Alpha Weighting

- **The choice**: Qdrant's server-side Reciprocal Rank Fusion via `FusionQuery(fusion=Fusion.RRF)`
- **The alternatives**: Manual alpha weighting (`score = alpha * dense + (1-alpha) * sparse`)
- **The reasoning**: The spec called for alpha weighting. During implementation, Qdrant's prefetch + RRF fusion turned out to be simpler — one API call instead of two queries + manual score merging. RRF is also more robust: it fuses ranks, not scores, so it's insensitive to score scale differences between dense (0-1 cosine) and sparse (unbounded TF-IDF).
- **The trade-off**: Less control over the blend ratio. With alpha you can tune 0.6 vs 0.8. With RRF you can't — it's rank-based. In practice, the benchmark showed this didn't matter: hybrid 24/26 vs dense 23/26, the gain is from having both signals, not from tuning their ratio.
- **When to revisit**: If you need per-query-type weighting (e.g., exact codes should weight BM25 higher). Phase 2's QueryRouter handles this by routing to different search modes entirely, not by tuning alpha.
- **Interview version**: "We switched from alpha weighting to Qdrant's native RRF fusion because it's one API call instead of two queries plus manual score merging. RRF fuses ranks rather than scores, which avoids the problem of dense cosine scores (0-1) being on a different scale than BM25 TF-IDF scores. Less control but simpler code and the benchmarks showed the gain comes from having both signals, not from tuning their ratio."

### Decision 3: RBAC at Query Level, Not Post-Retrieval

- **The choice**: `query_filter` applied directly in the Qdrant query call
- **The alternatives**: Retrieve everything, then filter results in Python before sending to LLM
- **The reasoning**: Post-retrieval filtering means the LLM already processed unauthorized documents in its context window. Even if you hide them from the response, (a) the LLM "knows" about them and a prompt injection could leak content, (b) you waste compute embedding/retrieving docs the user can't see. Query-level filtering means unauthorized docs never enter the pipeline.
- **The trade-off**: You need RBAC metadata on every point in Qdrant. Payload indexes add minor storage overhead. Both are negligible compared to the security benefit.
- **When to revisit**: Never. Post-retrieval RBAC is fundamentally broken for any system where the context window touches an LLM.
- **Interview version**: "We filter at the Qdrant query level because post-retrieval filtering means the LLM has already processed unauthorized documents. They're in the context window. A prompt injection in any of those docs could leak content even if our application hides it from the response. By filtering at the DB level, unauthorized documents literally don't exist from the LLM's perspective."

### Decision 4: Two-Tier Test Strategy (Mock + Live)

- **The choice**: Auto tests use hash-based fake embeddings; live tests (manual `pytest -m live`) use real Azure OpenAI
- **The alternatives**: All tests use real embeddings, all tests use mocks, or record/replay
- **The reasoning**: Auto tests must run without credentials (CI, new dev setup). Live tests must verify real semantic quality (does "towary niebezpieczne" actually find the hazmat doc with real embeddings?). Two tiers give both. Hash-based mocks are deterministic and test the pipeline (API, RBAC, Qdrant integration). Live tests verify the AI actually works.
- **The trade-off**: Live tests require Azure OpenAI credentials and cost money. They're excluded from `make test` (only `pytest -m live`).
- **When to revisit**: If you add a local embedding model (Phase 6 air-gapped), it could replace live tests for some scenarios.
- **Interview version**: "We have two test tiers. Auto tests use deterministic SHA-256 based fake embeddings — they test the pipeline, RBAC, and API without needing credentials. Live tests use real Azure OpenAI to verify semantic quality: does searching in Polish actually find English documents? Both are necessary. Auto tests catch regressions in CI. Live tests prove the AI works."

### Decision 5: Path Traversal Protection via Allowlist

- **The choice**: Ingest endpoint resolves the file path and checks it starts with `ALLOWED_DATA_DIR`
- **The alternatives**: No validation (original implementation), blocklist of dangerous paths, chroot/sandboxing
- **The reasoning**: The original implementation accepted any `file_path` from the request body. Someone could POST `{"file_path": "/etc/passwd"}` and the endpoint would read it. An allowlist (only files under `data/`) is the simplest correct solution. Blocklists are fragile (you can't enumerate all dangerous paths). Chroot is overkill for Phase 1.
- **The trade-off**: Files must be in the `data/` directory. In production, this would be a configurable setting.
- **When to revisit**: Production deployments need a configurable allowed directory via env var, not a hardcoded path relative to the source file.
- **Interview version**: "The ingest endpoint originally accepted arbitrary file paths — a classic path traversal vulnerability. We fixed it with an allowlist: the path is resolved (collapsing `..` traversals) and must start with the `data/` directory. We chose allowlist over blocklist because you can't enumerate all dangerous paths. The vulnerability was caught during development, not by TDD, which is something I'd do differently — write the attack test first."

## Patterns & Principles Used

### 1. Dependency Injection via Callable

- **What**: Pass functions as arguments instead of importing concrete implementations
- **Where**: `hybrid_search(embed_fn=...)` in `retriever.py:48`, `ingest_document(embed_fn=...)` in `ingestion.py:65`
- **Why**: The retriever doesn't know or care if the embedding comes from Azure OpenAI, Cohere, or a SHA-256 hash. Tests inject mocks. Production injects real clients. Same code path.
- **When you wouldn't use it**: If there's only ever one implementation and testing doesn't require substitution. But for anything involving external APIs, always inject.

### 2. ABC + Factory (Embeddings)

- **What**: Abstract base class defines the contract; factory function instantiates the right implementation
- **Where**: `BaseEmbedder` ABC in `embeddings.py:109`, `get_embedder()` factory in `embeddings.py:285`
- **Why**: Adding a new embedding provider (e.g., Voyage AI) means: (a) implement 3 methods, (b) add to the factory dict. Zero changes to retriever, ingestion, or tests. The factory also validates the provider name at construction time.
- **When you wouldn't use it**: If you'll only ever have one provider. At 4 providers (Azure, Cohere, Nomic, Mock), the ABC pays for itself.

### 3. Deterministic Test Double (MockEmbedder)

- **What**: SHA-256 hash expansion produces consistent vectors for the same input text
- **Where**: `MockEmbedder._hash_to_vector()` in `embeddings.py:148-164`
- **Why**: Random vectors make tests flaky — search results change between runs. Hash-based vectors are deterministic: "ISO 9001" always produces the same 1536-d vector. Tests can assert exact result counts and rankings.
- **When you wouldn't use it**: When you need to test actual semantic similarity. For that, use live tests with real embeddings.

### 4. Strategy Pattern (Search Modes)

- **What**: Enum selects which code path to execute
- **Where**: `SearchMode` enum in `retriever.py:33-36`, branching in `hybrid_search()` at lines 65, 76, 87
- **Why**: Clean separation of dense-only, sparse-only, and hybrid paths. Adding a new mode (e.g., `DENSE_WITH_RERANK`) means adding an enum value and a branch. The caller just passes `mode=SearchMode.NEW_MODE`.
- **When you wouldn't use it**: If modes share enough logic that branching creates duplication. Phase 2's `enhanced_search()` wraps `hybrid_search()` rather than adding more branches.

### 5. Fail-Closed Guard (RBAC)

- **What**: Refuse to operate rather than risk a security breach
- **Where**: Empty department check in `rbac.py:64-68`, unknown user raises ValueError in `rbac.py:49`
- **Why**: The alternative (fail-open: empty departments = see everything) is a full RBAC bypass. Fail-closed means the worst case is a user seeing nothing, which is visible and debuggable.
- **When you wouldn't use it**: Almost never in security code. For non-security contexts (e.g., missing optional config), fail-open with defaults might be appropriate.

### 6. Idempotent Setup (Collection)

- **What**: Check if resource exists before creating
- **Where**: `ensure_collection()` in `collections.py:13-14` — `if exists: return`
- **Why**: Safe to call in test fixtures, startup hooks, migration scripts. No error on duplicate creation.
- **When you wouldn't use it**: If you need to enforce that the resource doesn't already exist (e.g., user registration — duplicate username should error).

### 7. Pydantic Validation as First Defense

- **What**: Field constraints reject invalid data at deserialization, before business logic runs
- **Where**: `clearance_level: int = Field(ge=1, le=4)` in `document.py:10`, `top_k: int = Field(default=5, ge=1, le=50)` in `document.py:33`
- **Why**: Defense in depth. Clearance 0 is rejected by Pydantic before it ever reaches `build_qdrant_filter()`. No extra validation code needed in RBAC logic.
- **When you wouldn't use it**: If validation rules are context-dependent (e.g., max clearance varies per tenant). Then you need runtime validation in addition to Pydantic.

## Benchmark Results & What They Mean

### Search Mode Comparison (26 queries, 12 docs, 7 categories)

| Mode | Synonym (4) | Exact Code (4) | Ranking (4) | Jargon (4) | Polish (4) | Typo (4) | Negation (2) | Total |
|---|---|---|---|---|---|---|---|---|
| BM25 (free, 2ms) | 2/4 | 4/4 | 2/4 | 2/4 | 2/4 | 2/4 | 2/2 | **16/26** |
| Dense ($0.02/1M, 147ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 1/2 | **23/26** |
| Hybrid RRF (128ms) | 4/4 | 4/4 | 3/4 | 3/4 | 4/4 | 4/4 | 2/2 | **24/26** |

**What the numbers mean**:
- BM25 fails consistently on 4 categories (synonyms, Polish, typos, jargon) — all variations of "the user doesn't know the exact term in the document." This is structural, not a tuning issue.
- Dense handles real-world query patterns (cross-lingual, typos, jargon) without domain fine-tuning. text-embedding-3-small's cross-lingual training handles Polish queries searching English documents.
- Hybrid's only gain over dense is negation (2/2 vs 1/2) and better exact code ranking at top_k=1. BM25 matches "non-perishable" by keyword when dense matches "temperature" semantically (wrong for a negation query).
- Hybrid is faster than dense-only (128ms vs 147ms) due to Qdrant's prefetch parallelization.

**Architecture decision**: The real question was never "BM25 or Dense?" — it was "Dense alone or Dense+BM25?" Dense is mandatory. BM25 is a precision supplement for exact codes and negation keywords.

**Boundary**: Phase 2 expanded to 52 queries and the recommendation REVERSED: dense MRR=0.885 beat hybrid MRR=0.847. BM25 added noise at higher query diversity. Benchmark conclusions are scale-dependent.

### Embedding Model Comparison

| Model | Dimensions | Cost/1M tokens | Score (26 queries) |
|---|---|---|---|
| text-embedding-3-small | 1536 | $0.02 | 23/26 |
| text-embedding-3-large | 3072 | $0.13 | 23/26 |

**What the numbers mean**: At 12 documents, the extra 1536 dimensions add zero discriminating power. Embeddings are already spread far apart in 1536-d space. The 6.5x cost buys nothing.

**Boundary**: This result is specific to 12 documents. At ~1000+ semantically similar documents (e.g., 50 contracts all discussing temperature penalties), the higher-dimensional space might separate close embeddings better. This is an assumption, not evidence. Phase 2 confirmed the finding holds at 52 queries too.

### RBAC Verification

- Unknown user: ValueError (403)
- Empty departments: ValueError (refused, not "no filter")
- Clearance boundaries (0, -1, 5): Rejected by Pydantic
- Path traversal on ingest: 403
- Same query "salary compensation termination", three users: Max sees 2 docs, Katrin sees 1, Eva sees 6 (verified with real Azure OpenAI embeddings)

## Test Strategy

### Organization (80 total: 56 unit + 3 integration + 21 e2e)

| Layer | Tests | What They Prove |
|---|---|---|
| Unit (56) | test_rbac (13), test_retriever (10), test_domain_models (12), test_ingestion (7), test_api_search (6), test_sparse (8) | Individual components work correctly in isolation. RBAC filter construction is correct for all user types. Pydantic rejects invalid inputs. Sparse vectors preserve hyphenated codes. |
| Integration (3) | test_search_e2e | RBAC filters actually work against a real Qdrant instance. Not just "do the filter objects look right" but "does Qdrant return the right docs for this user." |
| E2E (7) | test_phase1_demo | Full workflow: ingest docs → search as different users → verify access control. Path traversal blocked. Unknown user rejected. Uses mock embeddings (no credentials needed). |
| Live (14) | test_phase1_live (9), test_phase1_benchmarks (5) | Real Azure OpenAI embeddings confirm semantic quality. "towary niebezpieczne" actually finds hazmat docs. Same query gives different results per user with real vectors. The 26-query benchmark runs here. |

### What the tests prove (outcomes, not counts)

- **Unauthorized documents are invisible**: Max (clearance 1) searching "compensation" gets zero results. Not a refusal — the LLM never receives the document. Verified with real embeddings.
- **RBAC can't be bypassed via empty departments**: Empty department list throws ValueError, not "match everything."
- **Invalid clearance values are rejected at the boundary**: Clearance 0, -1, 5 all rejected by Pydantic. 1 and 4 accepted (edge of valid range).
- **Path traversal is blocked**: `../../etc/passwd` → 403. The file is never read.
- **BM25 preserves hyphenated codes**: "ISO-9001" and "CTR-2024-001" tokenize as single tokens. Hyphens aren't stripped.
- **Hash collisions in sparse vectors are handled**: Colliding indices are merged by summing values. Qdrant doesn't crash on duplicate indices.

### Key test patterns

- **Mock embedding via AsyncMock**: Unit tests for the retriever inject `AsyncMock(return_value=[0.1]*1536)`. No API calls, instant execution.
- **SHA-256 fake embeddings in E2E**: `hashlib.sha256(text.encode()).digest()` expanded to 1536 floats. Deterministic, reproducible, credential-free.
- **Nested `patch()` for API tests**: The search endpoint test mocks `get_qdrant_client()`, `get_embeddings()`, and the embed method — three layers of patching because the endpoint calls them in sequence before reaching `hybrid_search()`.
- **`pytest.mark.live` for credential-dependent tests**: Excluded from `make test`. Run manually with `pytest -m live`.

### What ISN'T tested (mapped to future phases)

- Substring department names (e.g., "ware" matching "warehouse") → Phase 10
- Concurrent RBAC checks under load → Phase 4 with PostgreSQL
- Severe typos ("farmacorp" vs "pharamcorp") → Phase 2
- Complex Polish phrases → Phase 2
- Confidence thresholds (irrelevant queries still return results) → Phase 5
- Cross-document reasoning queries → Phase 3
- Langfuse tracing → Phase 4

## File Map

| File | Purpose | Key Patterns | Lines |
|------|---------|-------------|-------|
| `apps/api/src/domain/document.py` | Pydantic models: Document, Chunk, UserContext, Search*, Ingest* | Pydantic Field constraints as first defense | 76 |
| `apps/api/src/security/rbac.py` | `build_qdrant_filter()`, `resolve_user_context()`, DEFAULT_USER_STORE | Fail-closed guard, query-level RBAC | 81 |
| `apps/api/src/infrastructure/qdrant/client.py` | Async singleton Qdrant client factory | Singleton, module-level state | 26 |
| `apps/api/src/infrastructure/qdrant/collections.py` | Collection schema: dense + sparse vectors, RBAC payload indexes | Idempotent setup, IDF modifier | 49 |
| `apps/api/src/rag/embeddings.py` | BaseEmbedder ABC, AzureOpenAI/Cohere/Mock implementations, factory | ABC + Factory, deterministic test double | 331 |
| `apps/api/src/rag/ingestion.py` | `chunk_text()`, `ingest_document()` — chunk + embed + upsert | DI via callable, pipeline steps | 106 |
| `apps/api/src/rag/sparse.py` | BM25-style sparse vector encoder (TF + hash indices) | Lightweight local impl, hash collision merge | 62 |
| `apps/api/src/rag/retriever.py` | `hybrid_search()` — 3 modes: dense, sparse, hybrid RRF | Strategy pattern, DI via callable | 367* |
| `apps/api/src/api/v1/search.py` | POST /api/v1/search endpoint | Thin controller, delegates to retriever | 32 |
| `apps/api/src/api/v1/ingest.py` | POST /api/v1/ingest with path traversal protection | Allowlist validation, `.resolve()` | 50 |
| `scripts/seed_documents.py` | Seeds 6 mock contracts into Qdrant | — | — |
| `data/mock-contracts/*.txt` | 6 text contracts, 3 departments, clearance 1-4 | — | — |
| `tests/unit/test_rbac.py` | 13 tests: filter construction, edge cases, clearance boundaries | — | 134 |
| `tests/unit/test_retriever.py` | 10 tests: RBAC filter passed, modes call Qdrant correctly | Mock-heavy, AsyncMock | 238 |
| `tests/unit/test_sparse.py` | 8 tests: tokenization, hyphenated codes, hash collisions | — | 48 |
| `tests/e2e/test_phase1_demo.py` | 7 tests: full workflow with mock embeddings | SHA-256 fake embeddings, nested patch | 311 |
| `tests/e2e/test_phase1_benchmarks.py` | 5 live benchmark tests (26 queries, 7 categories) | Real Azure OpenAI, pytest.mark.live | — |

*retriever.py is 367 lines including Phase 2's `enhanced_search()`. Phase 1's `hybrid_search()` is lines 44-123 (~80 lines).

## Interview Talking Points

1. **RBAC at query level vs post-retrieval**: "We filter at the Qdrant query level so unauthorized documents never enter the LLM's context window. Post-retrieval filtering is fundamentally broken — the LLM has already seen the content, and a prompt injection could leak it. The trade-off is needing RBAC metadata on every vector point, but that's negligible storage overhead compared to a data leak."

2. **BM25's role in hybrid search**: "BM25 isn't a search engine for enterprise use — it's a lookup tool. It fails 38% of queries from real humans (synonyms, cross-lingual, typos). But it puts contract ID CTR-2024-001 at rank 1 where dense puts it rank 2. We keep BM25 specifically for exact code precision and negation keyword matching. Switch to dense-only when your corpus has no alphanumeric codes."

3. **Embedding model choice**: "We benchmarked text-embedding-3-small vs large across 26 queries. Identical results at 6.5x cost difference. At 12 documents, the extra 1536 dimensions add zero discriminating power. We'd revisit at ~1000+ semantically similar documents where close embeddings start overlapping, but that boundary is an assumption we haven't tested."

4. **Empty department list as security boundary**: "MatchAny([]) has undefined behavior across Qdrant versions — it could match everything (data leak) or nothing (silent failure). Both are wrong. We raise ValueError instead. An empty department list in production means a database migration error or misconfigured IdP. The correct response is fail-closed: zero results, not all results."

5. **Dependency injection via embed_fn callable**: "The retriever accepts `embed_fn: Callable[[str], Coroutine]` instead of importing a specific embedding client. Unit tests inject AsyncMock. Integration tests inject MockEmbedder (SHA-256 deterministic). Production injects Azure OpenAI. Same retriever code in all cases. This also made Phase 2's multi-provider embedding swap trivially easy."

6. **RRF vs alpha weighting**: "The spec called for alpha-weighted blending between dense and sparse scores. We switched to Qdrant's server-side RRF fusion because (a) one API call instead of two queries + manual merging, (b) RRF fuses ranks not scores, avoiding the scale mismatch between cosine similarity (0-1) and TF-IDF (unbounded), (c) the benchmark showed the gain comes from having both signals, not from tuning their ratio."

7. **Path traversal caught during development**: "The ingest endpoint originally accepted arbitrary file paths. I caught it during development and fixed it before writing the test. That's the wrong order — TDD means write the attack test first, watch it pass (bad), then fix. Security follows the same red-green-refactor cycle. I got lucky. Luck isn't a security model."

8. **Phase 2 reversed Phase 1's hybrid recommendation**: "At 26 queries, hybrid (24/26) beat dense (23/26). At 52 queries (Phase 2), dense MRR=0.885 beat hybrid MRR=0.847. BM25 added noise when query diversity increased. The lesson: benchmark conclusions are scale-dependent. Always re-validate when the dataset doubles."

## What I'd Explain Differently Next Time

**Start the RBAC explanation with the failure mode, not the implementation.** "What happens when someone with no departments queries the system?" is a much better entry point than "here's how we build a Qdrant filter." The failure mode shows why the implementation exists. The implementation without context is just code.

**The BM25 vs Dense framing was wrong initially.** I started by comparing them as alternatives. The real question was always "Dense alone or Dense+BM25?" — reframing the comparison as "do I need BM25 at all once I have embeddings?" makes the analysis clearer and the conclusion more obvious.

**Character-based chunking is fine for Phase 1 but explain WHY it's temporary.** The difference between 512 chars and 512 tokens matters for semantic density: short words pack more tokens into 512 chars than long words. This doesn't matter at 12 documents but creates inconsistent chunk quality at scale. Phase 2 benchmarks three strategies.

**The test pyramid shape (56 unit > 3 integration > 21 e2e) has an unusual middle.** Only 3 integration tests because the integration layer is thin — just Qdrant connection + RBAC filter verification. Most RBAC logic is pure Python (testable at unit level). The Qdrant-specific behavior (does the filter actually work?) only needs a few tests. The E2E layer is thick because the full workflow (ingest → search → RBAC check → results) has many scenarios to cover.

**MockEmbedder's SHA-256 approach is a pattern worth teaching explicitly.** Many RAG tutorials use random vectors in tests and then wonder why results are non-deterministic. The key insight: test embeddings need to be (a) deterministic (same text = same vector every time), (b) different (different text = different vector), (c) fast (no API calls). Hash functions give all three.
