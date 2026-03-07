# ADR-006: Multi-Provider Embedding Architecture — Benchmarked on 52 Queries

## Status
Accepted

## Context
Phase 1 proved that `text-embedding-3-small` matches `text-embedding-3-large` on a 12-doc logistics corpus — both score 23/26 on dense-only search. The large model costs 6.5x more ($0.13 vs $0.02/1M tokens) for zero additional results. But this finding is corpus-scale-dependent: at 1,000+ semantically similar documents, the 3072-dimension space may separate close embeddings that 1536 dimensions cannot.

Phase 2 needs to: (1) benchmark additional models (Cohere, Nomic), (2) make the embedding layer swappable without code changes, (3) support air-gapped deployments with local models.

## Decision
**Multi-provider embedding architecture with 4 benchmarked models:**

| Model | Provider | Dimensions | Cost/1M Tokens | Role |
|-------|----------|------------|-----------------|------|
| `text-embedding-3-small` | Azure OpenAI | 1536 | $0.02 | **Default** — MRR 0.885 on 52 queries. Best AND cheapest. |
| `text-embedding-3-large` | Azure OpenAI | 3072 | $0.13 | MRR 0.856 on 52 queries. 6.5x cost for LOWER MRR (-0.029). NOT justified. |
| `cohere-embed-v4` | Cohere | 1024 | $0.10 | Registered, not yet benchmarked. Reduces Azure dependency. |
| `nomic-embed-text-v1.5` | Nomic (open-source) | 768 | $0.00 | Registered, not yet benchmarked. Air-gapped candidate for Phase 6. |

All providers implement `BaseEmbedder` ABC. Factory function `get_embedder(provider, **kwargs)` selects provider at runtime. `MockEmbedder` (deterministic SHA-256 hash-based) enables testing without credentials.

## Architecture

```
get_embedder("azure_openai", model="text-embedding-3-small")  -> AzureOpenAIEmbedder
get_embedder("cohere", api_key="...", model="embed-v4.0")      -> CohereEmbedder
get_embedder("mock", dimensions=1536)                          -> MockEmbedder
```

- `AzureOpenAIEmbedder` wraps LangChain's `AzureOpenAIEmbeddings` (proven Phase 1 integration)
- `CohereEmbedder` uses httpx directly (single POST endpoint, SDK unnecessary)
- `MockEmbedder` uses SHA-256 hash expansion for deterministic, reproducible test vectors
- Backward compatible: `get_embeddings()` still returns LangChain `AzureOpenAIEmbeddings` for Phase 1 code

## Benchmark Harness

`EmbeddingBenchmarkResult` captures per-model metrics:
- precision@k, recall@k, MRR against 52-query ground truth dataset
- Average latency per embedding call
- Cost per 1M tokens
- Total queries evaluated

Benchmark scripts in `scripts/benchmark_embeddings.py` run against live infrastructure or mock mode for CI.

## Alternatives Considered

| Alternative | Why Not |
|-------------|---------|
| Single provider (Azure only) | Vendor lock-in. No air-gapped option. No competitive pressure on pricing. |
| Cohere as default | Strong model but adds vendor dependency on top of Azure. Benchmark first — switch only if measurably better. |
| Nomic as default | Open-source and free, but 768 dimensions may underperform on semantic overlap at scale. Benchmark candidate for Phase 6. |
| SPLADE (learned sparse) | Different category — sparse retrieval, not dense embedding. BM25 is sufficient for sparse in Phase 1-2. |
| Direct OpenAI API (not Azure) | LogiCore targets enterprise — Azure is the enterprise deployment path with data residency, RBAC, and compliance certifications. |

## Switch Conditions

| Current Choice | Switch When |
|----------------|-------------|
| text-embedding-3-small (default) | Corpus grows to 1,000+ semantically similar docs AND retrieval precision drops measurably — then benchmark large again |
| Azure OpenAI provider | Enterprise requires air-gapped deployment → switch to Nomic (Phase 6) |
| Single embedding model | A/B testing shows Cohere outperforms Azure on domain-specific queries by >5% precision@5 |

## Consequences
- `BaseEmbedder` ABC adds one layer of abstraction over provider-specific SDKs — minimal overhead, maximum flexibility
- Adding a new provider requires only: implement `BaseEmbedder`, add to `get_embedder()` factory, add to `EMBEDDING_MODELS` registry
- `MockEmbedder` eliminates credential dependency for 329 unit/integration tests
- Qdrant collection schema ties to vector dimensionality — changing models requires collection recreation or shadow collection + atomic swap
- Model version pinning is critical — silent provider updates invalidate existing vectors (drift detection planned for Phase 5)
