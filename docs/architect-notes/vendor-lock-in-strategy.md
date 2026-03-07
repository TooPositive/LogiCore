# Architect Notes: Vendor Lock-In Strategy

> How I designed LogiCore so we can swap any component in under a week.

## Portability Assessment

| Component | Lock-In Risk | Exit Time | Abstraction Layer | Exit Strategy |
|---|---|---|---|---|
| Azure OpenAI | LOW | 1 day | `LLMProvider` Protocol (Phase 6) | Swap to Anthropic, Ollama, or any OpenAI-compatible API. One env var change. |
| Qdrant | MEDIUM | 1 week | None yet — needs building | Export vectors via API, import to Weaviate/Pinecone. Sparse vectors need re-indexing. |
| PostgreSQL | LOW | 2 days | Standard SQLAlchemy/asyncpg | Works on any Postgres-compatible: Aurora, CockroachDB, Supabase, Neon. |
| Redis | LOW | 1 day | Standard redis-py | Works on any Redis-compatible: Dragonfly, KeyDB, Valkey, Upstash. |
| Langfuse | MEDIUM | 1 week | Callback handler interface | OpenTelemetry export. Alternative: LangSmith, Arize, custom Postgres logging. OSS = self-host forever. |
| Kafka | LOW | 3 days | confluent-kafka client | Works on Confluent Cloud, Redpanda, Amazon MSK. Standard protocol. |
| LangGraph | HIGH | 2-4 weeks | None (by design) | Most coupled component. Graph definitions, state schemas, checkpointer. Alternative: custom state machine. |
| Next.js | LOW | 1 week | Standard React components | Can migrate to Remix, Vite, or plain React. shadcn/ui components are framework-agnostic. |

**Overall portability score: 8/10.** LangGraph is the only high-risk coupling, and it's a conscious trade-off.

## Abstraction Layers to Build

### 1. Vector Database Abstraction (for Qdrant exit)

```python
class VectorStore(Protocol):
    """Abstract vector store — swap Qdrant for Weaviate/Pinecone without code changes."""
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None: ...
    async def search(self, collection: str, query_vector: list[float],
                     filters: dict, top_k: int) -> list[SearchResult]: ...
    async def hybrid_search(self, collection: str, dense_vector: list[float],
                           sparse_vector: dict, filters: dict, top_k: int) -> list[SearchResult]: ...
    async def delete(self, collection: str, point_ids: list[str]) -> None: ...
```

**Files to create:**
- `apps/api/src/infrastructure/vectordb/protocol.py` — abstract interface
- `apps/api/src/infrastructure/vectordb/qdrant.py` — Qdrant implementation
- `apps/api/src/infrastructure/vectordb/factory.py` — factory using `VECTOR_DB_PROVIDER` env var

**When**: Build during Phase 1. The abstraction costs ~2 hours upfront, saves weeks if we ever migrate.

### 2. Observability Abstraction (for Langfuse exit)

```python
class ObservabilityProvider(Protocol):
    """Abstract observability — swap Langfuse for LangSmith/custom without code changes."""
    def trace(self, name: str, metadata: dict) -> Trace: ...
    def span(self, trace: Trace, name: str) -> Span: ...
    def log_generation(self, span: Span, prompt: str, response: str,
                      model: str, tokens: int, cost: float) -> None: ...
    def score(self, trace: Trace, name: str, value: float) -> None: ...
```

**Files to create:**
- `apps/api/src/telemetry/provider.py` — abstract interface
- `apps/api/src/telemetry/langfuse_provider.py` — Langfuse implementation
- `apps/api/src/telemetry/factory.py` — factory using `OBSERVABILITY_PROVIDER` env var

**When**: Build during Phase 4. Langfuse is unlikely to disappear (OSS, funded), but the abstraction keeps options open.

### 3. LLM Provider Abstraction (already designed in Phase 6)

Already planned. Protocol-based: `AzureOpenAIProvider`, `OllamaProvider`. Add later: `AnthropicProvider`, `MistralProvider`.

## Vendor Risk Scenarios

### Scenario: Qdrant doubles pricing

**Impact**: MEDIUM — Qdrant is self-hosted in Docker, so pricing doesn't affect us directly. But if Qdrant Cloud is needed for scaling, alternatives exist.

**Action plan (4 hours)**:
1. Export vectors via Qdrant API (scripted, ~10 min for 50K vectors)
2. Import to Weaviate (similar API, similar performance)
3. Update `VectorStore` factory to use Weaviate implementation
4. Re-index sparse vectors (BM25 implementation differs)
5. Run retrieval benchmark to verify quality

### Scenario: Azure OpenAI discontinues or changes pricing

**Impact**: LOW — already have Ollama fallback.

**Action plan (1 hour)**:
1. Change `LLM_PROVIDER=ollama` in `.env`
2. Or add `AnthropicProvider` implementation (Claude API is OpenAI-compatible with adapter)
3. Update model routing tiers
4. Re-run quality benchmarks

### Scenario: LangGraph goes closed-source or abandoned

**Impact**: HIGH — most coupled component.

**Action plan (2-4 weeks)**:
1. LangGraph state schemas → custom TypedDict state machines
2. Graph definitions → custom async pipeline with explicit routing
3. Checkpointer → custom PostgreSQL state persistence
4. HITL gateway → custom interrupt/resume pattern
5. This is the one that would hurt. Mitigation: LangGraph is MIT-licensed and backed by LangChain (well-funded).

### Scenario: Langfuse acquired and shut down

**Impact**: MEDIUM — Langfuse is open-source, can self-host forever.

**Action plan (0 hours)**:
1. Already self-hosting. If Langfuse org disappears, fork the repo.
2. If we want to migrate: OpenTelemetry export → any compatible backend.
3. Alternative: Custom PostgreSQL-based trace logging (our audit log already captures most of this).

## Decision: What to Abstract Now vs Later

| Component | Abstract Now? | Why |
|---|---|---|
| LLM Provider | YES (Phase 6) | High switching probability. Multiple viable alternatives. Low abstraction cost. |
| Vector DB | YES (Phase 1) | Medium switching probability. Abstraction is simple (5 methods). |
| Observability | LATER (Phase 4) | Low switching probability. Langfuse is OSS. Abstraction can wait. |
| PostgreSQL | NO | Zero switching probability. Standard SQL everywhere. |
| Redis | NO | Zero switching probability. Standard protocol everywhere. |
| Kafka | NO | Very low switching probability. Standard protocol everywhere. |
| LangGraph | NO | Abstracting would defeat the purpose. Accept the coupling. |

## ADR to Create

- `docs/adr/009-vendor-portability.md` — documenting the conscious coupling decisions and exit strategies
