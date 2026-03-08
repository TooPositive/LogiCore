# Phase 6 Technical Recap: Air-Gapped Vault — Local Inference

## What This Phase Does (Business Context)

Regulated industries (Swiss banking, Polish pharma, EU healthcare) cannot send data to cloud APIs. Phase 6 makes the entire LogiCore AI system run locally — same agents, same RBAC, same search — by swapping one environment variable. The engineering problem: build a provider abstraction that makes cloud-vs-local a deployment decision, not a code decision.

## Architecture Overview

```
                        ┌─────────────────┐
                        │    Settings      │
                        │  llm_provider:   │
                        │  "azure"|"ollama"│
                        └───────┬─────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
            ┌───────────────┐       ┌───────────────┐
            │ AzureOpenAI   │       │ Ollama        │
            │ Provider      │       │ Provider      │
            │ (LangChain    │       │ (LangChain    │
            │  AzureChatAI) │       │  ChatOllama)  │
            └───────┬───────┘       └───────┬───────┘
                    │                       │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  LLMProvider Protocol │
                    │  generate()           │
                    │  generate_structured()│
                    │  model_name           │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Agents (unchanged)   │
                    │  ReaderAgent          │
                    │  ModelRouter          │
                    │  AuditWorkflow        │
                    └───────────────────────┘

    Embeddings: same pattern
    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
    │AzureOpenAI   │     │ Ollama       │     │ Mock         │
    │Embedder      │     │ Embedder     │     │ Embedder     │
    │(LangChain)   │     │ (httpx)      │     │ (SHA-256)    │
    └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
           └─────────────────┬──┘─────────────────┘
                    ┌────────▼────────┐
                    │ BaseEmbedder ABC│
                    │ embed_query()   │
                    │ embed_documents()│
                    │ dimensions      │
                    └─────────────────┘
```

Data flow for air-gapped mode:
1. User query arrives at FastAPI
2. `get_embedder("ollama")` embeds query via local Ollama `/api/embed` (768d)
3. Qdrant returns docs filtered by RBAC (unchanged from cloud mode)
4. `get_llm_provider(settings)` returns `OllamaProvider`
5. Agent calls `provider.generate(prompt)` — hits local Ollama at `http://ollama:11434`
6. Response parsed, returned to user. Zero bytes leave the network.

## Components Built

### LLMProvider Protocol + LLMResponse: `apps/api/src/core/infrastructure/llm/provider.py`

**What it does**: Defines the contract all LLM providers must satisfy. `LLMResponse` is a frozen dataclass capturing content, model name, token counts, and latency.

**The pattern**: **Protocol (structural subtyping)** instead of ABC (nominal subtyping). Any class with the right methods automatically satisfies the Protocol — no `class Foo(LLMProvider)` inheritance required.

**Key code walkthrough**:
```python
# provider.py:40-61
@runtime_checkable
class LLMProvider(Protocol):
    async def generate(self, prompt: str, **kwargs) -> LLMResponse: ...
    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse: ...

    @property
    def model_name(self) -> str: ...
```

`@runtime_checkable` enables `isinstance(provider, LLMProvider)` checks. This is used in tests to verify both Azure and Ollama providers satisfy the contract (see `test_satisfies_llm_provider_protocol` in both test classes).

**Why Protocol over ABC**: ABC requires explicit inheritance. If you use a third-party class that happens to have the right methods, ABC won't recognize it. Protocol uses duck typing — "if it quacks like an LLMProvider, it is one." This matters when wrapping LangChain objects, which we don't control.

**Why LLMResponse is frozen**: Immutability prevents accidental mutation of response data between cost tracking, logging, and caching. Once generated, the response is a fact.

**Alternatives considered**:
- **ABC (Abstract Base Class)**: More traditional, requires inheritance. Would work but adds coupling.
- **TypedDict**: No methods, just structure. Can't enforce `total_tokens` property.
- **Pydantic model**: Heavier than needed. LLMResponse has no validation logic.

### AzureOpenAIProvider: `apps/api/src/core/infrastructure/llm/azure_openai.py`

**What it does**: Wraps LangChain's `AzureChatOpenAI` behind the `LLMProvider` Protocol. Tracks latency via `time.perf_counter()` and extracts token counts from `response.usage_metadata`.

**The pattern**: **Adapter pattern**. The existing LangChain interface (`.ainvoke()` returning an `AIMessage`) is adapted to return `LLMResponse`.

**Key code walkthrough**:
```python
# azure_openai.py:44-57
async def generate(self, prompt: str, **kwargs) -> LLMResponse:
    start = time.perf_counter()
    response = await self._llm.ainvoke(prompt, **kwargs)
    elapsed_ms = (time.perf_counter() - start) * 1000

    usage = response.usage_metadata or {}
    return LLMResponse(
        content=response.content,
        model=self._deployment,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=elapsed_ms,
    )
```

**Why `usage.get("input_tokens", 0)` with default 0**: Some LangChain responses have `usage_metadata = None` (e.g., streaming, or non-OpenAI providers). Defaulting to 0 instead of crashing means cost tracking degrades gracefully — you lose precision, not availability.

### OllamaProvider: `apps/api/src/core/infrastructure/llm/ollama.py`

**What it does**: Wraps LangChain's `ChatOllama` behind `LLMProvider`. Handles three error modes with actionable error messages.

**The pattern**: **Adapter + error translation**. Converts generic Python exceptions into domain-specific errors with operator instructions.

**Key code walkthrough**:
```python
# ollama.py:46-69
async def generate(self, prompt: str, **kwargs) -> LLMResponse:
    start = time.perf_counter()
    try:
        response = await self._llm.ainvoke(prompt, **kwargs)
    except ConnectionError as e:
        raise ConnectionError(
            f"Ollama at {self._host} is not reachable. "
            f"Is the Ollama service running? Original error: {e}"
        ) from e
    except TimeoutError as e:
        raise TimeoutError(
            f"Ollama request timed out for model '{self._model}'. "
            f"The model may be too large for available hardware. "
            f"Original error: {e}"
        ) from e
    except Exception as e:
        error_msg = str(e).lower()
        if "not found" in error_msg:
            raise ValueError(
                f"Model '{self._model}' not found in Ollama. "
                f"Run: ollama pull {self._model}"
            ) from e
        raise
```

**Why three specific error handlers**: Each failure mode has a different fix. Connection refused = start Ollama. Model not found = `ollama pull`. Timeout = model too large for hardware. Generic "something went wrong" wastes the operator's time. The error message IS the runbook.

**Critical design: no silent fallback to Azure**. When Ollama fails, it raises — it does NOT try Azure. In air-gapped mode, falling back to cloud would be a compliance violation. The red team test `test_connection_refused_does_not_fallback_to_azure` proves this.

### LLM Provider Factory: `apps/api/src/core/infrastructure/llm/provider.py`

**What it does**: `get_llm_provider(settings)` reads `settings.llm_provider` and returns the right provider. Uses `match/case` with lazy imports.

**The pattern**: **Factory function with lazy imports**. Each provider is imported inside its `case` branch, so importing `provider.py` doesn't pull in `langchain_ollama` (which might not be installed in cloud-only deployments).

**Key code walkthrough**:
```python
# provider.py:64-101
def get_llm_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "azure":
            from apps.api.src.core.infrastructure.llm.azure_openai import (
                AzureOpenAIProvider,
            )
            return AzureOpenAIProvider(
                endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                deployment=settings.azure_openai_deployment,
                api_version=settings.azure_openai_api_version,
            )
        case "ollama":
            from apps.api.src.core.infrastructure.llm.ollama import (
                OllamaProvider,
            )
            return OllamaProvider(
                host=settings.ollama_host,
                model=settings.ollama_model,
            )
        case _:
            raise ValueError(...)
```

**Why lazy imports**: In cloud-only deployments, `langchain-ollama` may not be installed. If the factory imported `OllamaProvider` at module level, importing `provider.py` would crash even when using Azure. Lazy imports inside the `case` branches mean you only need the dependencies for the provider you're using.

### OllamaEmbedder: `apps/api/src/core/rag/embeddings.py`

**What it does**: Calls Ollama's `/api/embed` endpoint via httpx for local embeddings. Extends the existing `BaseEmbedder` ABC.

**The pattern**: **Extension of existing ABC hierarchy**. `OllamaEmbedder` joins `AzureOpenAIEmbedder`, `CohereEmbedder`, and `MockEmbedder` in the same inheritance tree.

**Key code walkthrough**:
```python
# embeddings.py:289-329
class OllamaEmbedder(BaseEmbedder):
    def __init__(self, host="http://localhost:11434", model="nomic-embed-text", dimensions=768):
        self._host = host.rstrip("/")
        self._model = model
        self._dimensions = dimensions

    async def _call_embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._host}/api/embed"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "model": self._model,
                "input": texts,
            }, timeout=60.0)
            response.raise_for_status()
            data = response.json()
        return data["embeddings"]
```

**Why httpx instead of LangChain OllamaEmbeddings**: LangChain's wrapper adds abstraction without value here. The Ollama embed API is trivial (POST with model + input, get embeddings back). httpx gives full control over timeouts and error handling with no extra dependency.

**Critical dimension mismatch**: Azure text-embedding-3-small = 1536d. nomic-embed-text = 768d. You CANNOT query a 1536d Qdrant collection with 768d vectors. Air-gapped deployments need a separate collection indexed with the local model. This is the gap most "run AI locally" tutorials miss.

### Think-tag stripping: `apps/api/src/domains/logicore/agents/brain/reader.py`

**What it does**: Strips `<think>...</think>` reasoning tags from Ollama model output before JSON parsing.

**The pattern**: **Input normalization before parsing**. Not a security boundary — a compatibility fix for models that emit reasoning traces.

**Key code walkthrough**:
```python
# reader.py:80-84
# Strip <think>...</think> tags (common in Ollama/qwen3 output)
think_pattern = re.compile(r"<think>.*?</think>", re.DOTALL)
content = think_pattern.sub("", content).strip()
```

**Why this exists**: qwen3 (and some other models) prefix every response with internal reasoning wrapped in `<think>` tags. Without stripping, the JSON parser receives `<think>...reasoning...</think>[{"rate": ...}]` and fails. This broke ALL invoice audit rate extraction on the first end-to-end test with Ollama. Two lines of regex, but a critical integration fix.

**Security note**: This is parsing convenience, not a security boundary. If stripping fails (e.g., unclosed tag), worst case = JSON parse fails = empty rate list returned. The security model (RBAC, parameterized SQL, read-only DB role) does not depend on think-tag behavior.

### Settings: `apps/api/src/core/config/settings.py`

**What it does**: Pydantic BaseSettings with 5 new fields for provider selection.

**The pattern**: **Config-driven behavior**. Deployment topology is determined by environment variables, not code branches.

```python
# settings.py:5-18
class Settings(BaseSettings):
    llm_provider: str = "azure"              # azure | ollama
    embedding_provider: str = "azure_openai"  # azure_openai | ollama | mock
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_embed_model: str = "nomic-embed-text"
```

**Why defaults favor Azure**: Existing deployments don't set these variables. Default to Azure means zero disruption for cloud users. Air-gapped users explicitly set `LLM_PROVIDER=ollama`.

### Docker Compose overlay: `docker-compose.airgap.yml`

**What it does**: Adds Ollama service and overrides API environment variables. Used with: `docker compose -f docker-compose.yml -f docker-compose.airgap.yml up`

**The pattern**: **Compose file overlay**. Base compose has all services. Air-gapped overlay adds Ollama and changes env vars. No duplication.

```yaml
# docker-compose.airgap.yml
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama-models:/root/.ollama
    deploy:
      resources:
        reservations:
          memory: 16G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
  api:
    environment:
      LLM_PROVIDER: ollama
      EMBEDDING_PROVIDER: ollama
      OLLAMA_HOST: http://ollama:11434
```

**Why 16G memory reservation**: Ollama loads the model into memory. qwen3:8b at Q4 quantization needs ~5GB. 16G gives headroom for the model + inference buffers + the OS. Without this, Docker may kill the Ollama container under memory pressure with no error.

## Key Decisions Explained

### Decision 1: Protocol over ABC for LLM providers

- **The choice**: Python `Protocol` (structural subtyping)
- **The alternatives**: ABC (nominal subtyping), plain duck typing (no type checking)
- **The reasoning**: Protocol allows any class with the right methods to satisfy the contract without inheriting. This matters for wrapping third-party classes (LangChain models) that we don't control.
- **The trade-off**: Protocol's `isinstance()` check with `@runtime_checkable` is slower than ABC's (checks all methods at runtime). Irrelevant for our use case (factory called once at startup).
- **When to revisit**: If we need shared implementation methods (e.g., common retry logic), ABC would be better. Protocol only defines interface, not implementation.
- **Interview version**: "We used a Protocol instead of ABC because our providers wrap third-party LangChain classes. With ABC, those wrappers would need explicit inheritance. With Protocol, any class that implements generate(), generate_structured(), and model_name automatically satisfies the contract. The trade-off is that Protocols can't share implementation — if we needed common retry logic across providers, we'd switch to ABC."

### Decision 2: Ollama over vLLM

- **The choice**: Ollama for dev and single-site deployments
- **The alternatives**: vLLM (2-5x throughput via continuous batching), llama.cpp (lower-level), TensorRT-LLM (NVIDIA-only)
- **The reasoning**: vLLM has no Apple Silicon support (no macOS at all). Dev happens on M4 Pro. Target customer (Swiss bank IT team) runs Docker Compose, not CUDA clusters.
- **The trade-off**: Lower throughput than vLLM at high concurrency. Ollama processes requests largely sequentially.
- **When to revisit**: >10K queries/day, or multi-GPU deployment, or Linux/NVIDIA production. ADR-007 documents the switch condition.
- **Interview version**: "We chose Ollama over vLLM because vLLM doesn't run on Apple Silicon, and our target deployment is a Swiss bank IT team running docker compose, not managing CUDA clusters. The trade-off is throughput — vLLM's continuous batching gives 2-5x improvement. We documented the switch condition: move to vLLM when query volume exceeds 10K/day or you need multi-GPU. The Protocol abstraction makes that swap a 1-2 day task."

### Decision 3: httpx for OllamaEmbedder instead of LangChain OllamaEmbeddings

- **The choice**: Direct httpx calls to Ollama's `/api/embed` endpoint
- **The alternatives**: LangChain's `OllamaEmbeddings` wrapper
- **The reasoning**: The embed API is trivial (POST with model + input). LangChain's wrapper adds a dependency and abstraction layer without value. httpx gives full control over timeout, error handling, and response parsing.
- **The trade-off**: Must handle Ollama API changes manually (httpx doesn't abstract the API version).
- **When to revisit**: If Ollama's embed API changes significantly, or if LangChain adds features we'd use (batching, retry).
- **Interview version**: "For embeddings, we used httpx directly instead of LangChain's OllamaEmbeddings. The Ollama embed API is a single POST endpoint — wrapping it in LangChain adds a dependency without value. For LLM generation we DID use LangChain (ChatOllama) because the chat API has more complexity (streaming, tool calling) that LangChain handles well. Different tools for different complexity levels."

### Decision 4: Separate embedding providers (not tied to LLM provider)

- **The choice**: Independent `embedding_provider` setting separate from `llm_provider`
- **The alternatives**: Single `provider` setting controlling both generation and embeddings
- **The reasoning**: You might want Azure embeddings (1536d, higher quality) with local generation (compliance). Or mock embeddings (testing) with Azure generation. Tying them together reduces deployment flexibility.
- **The trade-off**: Two settings to configure instead of one. Potential for misconfiguration (e.g., Azure embeddings with Ollama generation in air-gapped mode).
- **When to revisit**: If misconfigurations become common, add a validation check that warns when embedding_provider requires internet in air-gapped mode.
- **Interview version**: "We separated LLM provider from embedding provider because they serve different architectural concerns. A customer might want local generation for compliance but cloud embeddings for quality. In air-gapped mode both must be local, but in hybrid mode you want flexibility. The trade-off is configuration complexity — two settings instead of one."

## Patterns & Principles Used

### 1. Protocol (Structural Subtyping)
- **What**: Type contract satisfied by having the right methods, not by inheritance
- **Where**: `apps/api/src/core/infrastructure/llm/provider.py:40-61`
- **Why**: Wrapping third-party LangChain classes without modifying them
- **When NOT to use**: When you need shared implementation across providers (use ABC instead)

### 2. Factory Function with Lazy Imports
- **What**: Function that creates the right object based on config, importing dependencies only when needed
- **Where**: `apps/api/src/core/infrastructure/llm/provider.py:64-101`
- **Why**: Avoid importing `langchain_ollama` in cloud-only deployments where it's not installed
- **When NOT to use**: When all dependencies are always available (simpler to import at module level)

### 3. Adapter Pattern
- **What**: Wrapping an existing interface to match a new contract
- **Where**: Both `AzureOpenAIProvider` and `OllamaProvider` adapt LangChain's `.ainvoke()` to return `LLMResponse`
- **Why**: Agents should not depend on LangChain's response format
- **When NOT to use**: When the existing interface already matches your contract

### 4. Config-Driven Deployment Topology
- **What**: Environment variables determine which services to use, not code branches
- **Where**: `apps/api/src/core/config/settings.py:5-18` + `docker-compose.airgap.yml`
- **Why**: Same codebase, same agents, different deployment. No forking.
- **When NOT to use**: When different deployments need fundamentally different code paths (not just different backends)

### 5. Deterministic Test Doubles (existing, extended)
- **What**: `MockEmbedder` uses SHA-256 hash to produce deterministic vectors
- **Where**: `apps/api/src/core/rag/embeddings.py:134-170`
- **Why**: Tests don't need real embeddings — they need deterministic, reproducible vectors
- **When NOT to use**: When you're testing embedding quality (use real embeddings for benchmarks)

### 6. Error Translation with Actionable Messages
- **What**: Catch generic exceptions, re-raise with operator instructions
- **Where**: `apps/api/src/core/infrastructure/llm/ollama.py:50-69`
- **Why**: "Connection refused" tells you nothing. "Ollama is not reachable. Is the Ollama service running?" tells you what to check.
- **When NOT to use**: For internal errors where the operator can't act (let them propagate)

### 7. Docker Compose Overlay Pattern
- **What**: Multiple compose files merged at runtime (`-f base -f overlay`)
- **Where**: `docker-compose.airgap.yml`
- **Why**: No duplication of base services. Air-gapped overlay adds Ollama and changes env vars only.
- **When NOT to use**: When the overlay changes so much that the merge is harder to understand than a standalone file

## Benchmark Results & What They Mean

### Live Ollama Benchmark (qwen3:8b, Apple Silicon)

| Metric | Value | What it means |
|--------|-------|---------------|
| p50 latency | 29,376 ms | Dev hardware only. Reasoning is 4x slower than extraction (96s vs 22s). Production NVIDIA would be 5-20x faster. |
| p95 latency | 182,037 ms | Reasoning queries dominate p95. Confirms routing decision: complex queries should go to cloud when allowed. |
| Throughput | 19.9 tok/s | Adequate for single-site. vLLM would give 40-80 tok/s on same hardware class with batching. |
| Keyword accuracy | 100% (15/15) | Weak signal — "contains expected keyword" doesn't prove semantic correctness. |
| Financial extraction | 100% (10/10, 5 EN + 5 PL) | Stronger signal — exact EUR amount extraction matches ground truth. Q4 quantization doesn't corrupt rate extraction on clean excerpts. |
| Cost per query | EUR 0.00 | Zero marginal cost after hardware amortization. |

**The boundary**: 10/10 on clean single-rate excerpts. The boundary where extraction breaks (multi-rate, buried clauses, amendments) is not yet found. That's Phase 7 input for routing thresholds.

### Break-even Analysis

| Scenario | Cloud (routed) | Local | Winner |
|----------|---------------|-------|--------|
| 2,400 queries/day | EUR 4,380/year | EUR 5,000/year | Cloud by EUR 620 |
| 7,100 queries/day | EUR 12,958/year | EUR 5,000/year | Break-even |
| 10,000 queries/day | EUR 18,250/year | EUR 5,000/year | Local by EUR 13,250 |
| Regulated (any volume) | Not allowed | Only option | Local (compliance) |

## Test Strategy

### Organization

| Directory | Count | What they prove |
|-----------|-------|-----------------|
| `tests/unit/test_llm_provider.py` | 37 | Protocol contract, factory routing, error handling for both providers |
| `tests/unit/test_ollama_embedder.py` | 13 | OllamaEmbedder extends BaseEmbedder correctly, httpx calls work, factory routes to it |
| `tests/unit/test_docker_compose_airgap.py` | 13 | YAML is valid, required services present, env vars set correctly |
| `tests/unit/test_provider_swap.py` | 8 | Same calling code works for both providers, LLMResponse schema identical |
| `tests/unit/test_financial_extraction.py` | 21 | ReaderAgent parses EUR amounts in all formats, handles think tags, rejects bad data |
| `tests/unit/test_polish_quality.py` | 13 | Polish text accepted, diacritics preserved, number formats handled |
| `tests/unit/test_benchmark_local.py` | 31 | Benchmark script categories, cost computation, numerical extraction |
| `tests/red_team/test_airgap_security.py` | 17 | Zero external calls, no silent Azure fallback, RBAC independent of provider, input length limits |
| `tests/integration/test_local_inference.py` | 10 | Real Ollama: generate, embed, factory, latency, token counts |
| `tests/integration/test_financial_extraction_live.py` | 2 | Real Ollama extracts correct EUR amounts from 10 contract excerpts |

### What the tests PROVE

- **Air-gap is structural**: OllamaProvider only constructs localhost URLs. No code path reaches Azure. (`test_ollama_provider_host_is_localhost`, `test_ollama_provider_no_azure_credentials_used`)
- **Failure is explicit, never silent**: Connection refused raises, doesn't fall back to cloud. Model not found tells you to `ollama pull`. (`test_connection_refused_does_not_fallback_to_azure`, `test_model_not_found_suggests_pull`)
- **RBAC is provider-independent**: Clearance filters are built at the Qdrant query level. Switching LLM provider doesn't change them. (`test_rbac_filter_independent_of_provider_setting`)
- **Financial extraction survives quantization**: Q4 model correctly extracts EUR 0.45, 1.25, 850.00, 0.35, 0.52, 1.85, 720.00, 0.48, 3.15, 2.80 from contract text.
- **Think tags don't break parsing**: `<think>...</think>` prefix stripped before JSON parsing. (`test_extract_with_think_tags_stripped`)

### Mocking strategy

- **LLM responses**: `MagicMock` with `.content` and `.usage_metadata` — simulates LangChain's `AIMessage` without importing it
- **httpx calls**: `unittest.mock.patch` on `httpx.AsyncClient` for OllamaEmbedder tests
- **Settings**: Constructed directly with test values — no `.env` file dependency
- **Retriever**: `AsyncMock` with `.search()` returning controlled results

### What ISN'T tested

| Gap | Why | Future phase |
|-----|-----|-------------|
| Head-to-head Azure vs Ollama on 52-query ground truth | Needs Azure credentials + Ollama running simultaneously | Phase 7 (routing thresholds) |
| Multi-page contract extraction | Needs realistic long contract fixtures | Phase 7 |
| Concurrent request handling (Ollama queuing) | Needs load testing infrastructure | Phase 7 |
| Langfuse traces for local model | Wiring exists but not connected | Phase 12 |
| Model supply chain verification (SHA-256 hash check) | Operational security, not application architecture | Phase 10 |

## File Map

| File | Purpose | Key patterns | Lines |
|------|---------|-------------|-------|
| `apps/api/src/core/infrastructure/llm/provider.py` | Protocol + LLMResponse + factory | Protocol, Factory, Lazy imports | ~100 |
| `apps/api/src/core/infrastructure/llm/azure_openai.py` | Azure LLM provider | Adapter, Latency tracking | ~62 |
| `apps/api/src/core/infrastructure/llm/ollama.py` | Ollama LLM provider | Adapter, Error translation | ~85 |
| `apps/api/src/core/rag/embeddings.py` | Extended with OllamaEmbedder | ABC hierarchy extension, httpx | ~360 |
| `apps/api/src/core/config/settings.py` | 5 new provider fields | Config-driven behavior | ~44 |
| `apps/api/src/domains/logicore/agents/brain/reader.py` | Think-tag stripping fix | Input normalization | ~123 |
| `docker-compose.airgap.yml` | Air-gapped overlay | Compose overlay | ~37 |
| `scripts/benchmark_local.py` | Azure vs Ollama benchmark | CLI harness, strict mode | ~300 |
| `docs/adr/007-ollama-over-vllm.md` | ADR: Ollama for dev, vLLM for prod | Decision record | ~63 |
| `tests/unit/test_llm_provider.py` | Provider tests (37) | Mocked LangChain | ~718 |
| `tests/unit/test_ollama_embedder.py` | Embedder tests (13) | Mocked httpx | ~200 |
| `tests/unit/test_financial_extraction.py` | Financial precision (21) | Mocked LLM responses | ~400 |
| `tests/unit/test_polish_quality.py` | Polish language (13) | Provider acceptance | ~250 |
| `tests/red_team/test_airgap_security.py` | Security tests (17) | Negative tests, boundary probing | ~376 |
| `tests/integration/test_local_inference.py` | Live Ollama tests (10) | Real inference, skipif | ~200 |

## Interview Talking Points

1. **Protocol vs ABC**: "We used Protocol for the LLM provider abstraction because we're wrapping third-party LangChain classes. Protocol uses structural subtyping — any class with generate(), generate_structured(), and model_name satisfies it. No inheritance needed. The trade-off: Protocols can't share implementation. If we needed common retry logic, we'd use ABC."

2. **Air-gap is architectural, not behavioral**: "RBAC filtering happens at the Qdrant query level, before the LLM ever sees documents. Switching from Azure to Ollama changes the inference backend, not the security model. The red team tests prove RBAC is provider-independent."

3. **Error translation pattern**: "When Ollama is unreachable, we don't surface 'Connection refused.' We surface 'Ollama at http://localhost:11434 is not reachable. Is the service running?' The error message IS the runbook. Three failure modes, three specific messages, three specific fixes."

4. **The embedding gap nobody talks about**: "Everyone focuses on local LLM generation. Nobody mentions local embeddings. Air-gapped mode also means no Azure for text-embedding-3-small. Different embedding model = different dimensions = separate Qdrant collection = full re-index on migration. This was not in the spec — we caught it during analysis."

5. **Lazy imports in the factory**: "The factory imports providers inside each match/case branch. This avoids importing langchain_ollama in cloud-only deployments where it's not installed. Module-level imports would crash on import even when using Azure."

6. **Think-tag bug as integration proof**: "Ollama's qwen3 model prefixes responses with `<think>` reasoning tags. Unit tests all passed (mocked responses don't have tags). First end-to-end test with real Ollama: zero rates extracted. JSON parser choked on XML-like tags. This is why integration tests exist — they catch assumptions that unit tests confirm."

7. **Cost is the wrong frame for regulated deployments**: "Break-even vs routed cloud is 7,100 queries/day. Below that, cloud is cheaper. But for Swiss banking (FINMA) or Polish pharma, the question isn't cost — it's compliance. Air-gapped is the only option. The cost comparison exists for non-regulated customers making an elective choice."

8. **vLLM decision boundary**: "Ollama for dev (Apple Silicon) and single-site (Swiss bank IT team). vLLM for production Linux with >10K queries/day. The Protocol abstraction means switching is a 1-2 day task — implement three methods, register in factory. ADR-007 documents the switch condition."

## What I'd Explain Differently Next Time

**Start with the embedding problem, not the generation problem.** Generation is the easy part — wrap the LLM call, return a standardized response. Embeddings are where air-gapped deployment actually breaks: different models, different dimensions, incompatible Qdrant collections, full re-index required. If I were advising a team, the first question would be "what's your embedding strategy?" not "which local model?"

**The think-tag bug teaches more than the Protocol design.** The Protocol is clean engineering, but it's a textbook pattern. The think-tag bug is a real production surprise that only surfaces in integration testing. In a technical interview, the bug story demonstrates more architect thinking than the Protocol explanation: "we built the abstraction, tested it in isolation, then the first real end-to-end test revealed a model behavior nobody documented."

**Mock data that looks real is worse than no data.** The benchmark script's dry-run mode produced mock accuracy numbers (87% local vs 93% cloud). These looked like real benchmarks. When live tests showed 100%, it created a contradiction that confused the review. Next time: clearly synthetic test data (e.g., `[SIMULATED] 87%` in every output line) or no mock accuracy numbers at all.

**Test the hardest assumption first.** I built the provider abstraction before testing financial extraction accuracy. If I'd run 10 contract excerpts through Ollama on day one, I would have found the think-tag bug immediately and known the quantization risk was lower than expected. The Protocol design took a week. The extraction test took an hour. Start with the business validation.
