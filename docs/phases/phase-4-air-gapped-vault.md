# Phase 4: "The Air-Gapped Vault" — Infrastructure & Local Inference

## Business Problem

Swiss banks, German manufacturers, EU healthcare providers — they cannot send sensitive data to OpenAI's API. Regulatory requirements mandate that financial documents, patient records, and trade secrets never leave the internal network. Cloud AI is a non-starter.

**CTO pain**: "Our legal team says we can't use OpenAI for anything touching customer financial data. But the board wants AI. Build it on-premise."

## Architecture

```
LogiCore (Air-Gapped Deployment)
  ├── Ollama / llama.cpp (local inference)
  │     └── Llama 3 8B / Mistral 7B (quantized)
  ├── Qdrant (local vectors)
  ├── PostgreSQL (local state)
  ├── Redis (local cache)
  ├── Langfuse (local observability)
  └── LangGraph (orchestration)

  ALL within docker-compose.yml
  ZERO external API calls
  Network: isolated Docker bridge
```

> **Note**: vLLM does not support Apple Silicon (M-series). This phase uses **Ollama** or **llama.cpp** for local inference. Production deployments on Linux/NVIDIA would use vLLM for higher throughput.

**Key design decisions**:
- Ollama for dev (simple, M4 Pro compatible), vLLM for prod (Linux + NVIDIA)
- Model abstraction layer — swap Azure OpenAI ↔ Ollama with config change
- Quantized models (Q4_K_M) for memory efficiency on 36GB unified memory
- Full `docker-compose.yml` delivers entire stack — zero external dependencies

## Implementation Guide

### Prerequisites
- Phases 1-3 complete
- Ollama installed locally (`brew install ollama`)
- Model pulled: `ollama pull llama3:8b`
- Understanding of quantization trade-offs

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/infrastructure/llm/__init__.py` | Package init |
| `apps/api/src/infrastructure/llm/provider.py` | Abstract LLM provider interface |
| `apps/api/src/infrastructure/llm/azure_openai.py` | Azure OpenAI implementation |
| `apps/api/src/infrastructure/llm/ollama.py` | Ollama implementation (local inference) |
| `apps/api/src/config/settings.py` | Add LLM_PROVIDER toggle (azure \| ollama) |
| `docker-compose.airgap.yml` | Full air-gapped compose (adds Ollama service) |
| `scripts/benchmark_local.py` | Latency + throughput benchmark: Azure vs local |
| `tests/integration/test_local_inference.py` | Ollama integration tests |
| `docs/adr/004-ollama-over-vllm.md` | ADR for local inference choice |
| `infra/terraform/` | Baseline Terraform for AKS/EKS deployment (placeholder) |

### Technical Spec

**LLM Provider Abstraction**:
```python
class LLMProvider(Protocol):
    async def generate(self, prompt: str, **kwargs) -> str: ...
    async def embed(self, text: str) -> list[float]: ...

# Factory
def get_llm_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "azure":
            return AzureOpenAIProvider(settings)
        case "ollama":
            return OllamaProvider(settings)
```

**Docker Compose (air-gapped addition)**:
```yaml
# docker-compose.airgap.yml
services:
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama
    deploy:
      resources:
        reservations:
          memory: 16G
```

**Environment toggle**:
```
LLM_PROVIDER=ollama          # or "azure"
OLLAMA_HOST=http://ollama:11434
OLLAMA_MODEL=llama3:8b
```

### Success Criteria
- [ ] `LLM_PROVIDER=ollama` — full RAG pipeline works with local Llama 3
- [ ] `LLM_PROVIDER=azure` — same pipeline works with Azure OpenAI (no code change)
- [ ] Air-gapped compose starts all services including Ollama
- [ ] Benchmark script shows latency/throughput comparison
- [ ] Zero external API calls in air-gapped mode (verified with network monitor)
- [ ] Langfuse traces local inference with model name and token counts

## LinkedIn Post Template

### Hook
"Swiss banks and German manufacturers can't send their data to OpenAI. Here's the modern on-premise AI stack for 2026."

### Body
Built the same multi-agent system running 100% locally. Zero external API calls.

The stack:
- Ollama serving Llama 3 8B (quantized, 6GB RAM)
- Qdrant for hybrid search
- LangGraph for orchestration
- Langfuse for observability
- PostgreSQL for state

Everything in one `docker-compose.yml`. One command to start. One command to tear down.

The abstraction layer is the key: a Protocol-based LLM provider. Swap `LLM_PROVIDER=azure` to `LLM_PROVIDER=ollama` in your `.env`. Same agents, same RAG, same HITL gates. Different inference backend.

Performance on Llama 3 8B? Surprisingly good for structured tasks (data extraction, comparison, classification). Where it struggles: complex multi-hop reasoning. That's fine — you route those to the cloud model and keep sensitive data local.

Cost comparison:
- Azure OpenAI: ~$0.03 per audit query
- Local Llama 3: $0.00 per query (after hardware amortization)

For a company processing 10K queries/day, that's $300/day saved.

### Visual
Side-by-side: "Cloud Architecture" (data leaving network boundary) vs "Air-Gapped Architecture" (everything inside Docker network). Cost comparison table.

### CTA
"Are you running any AI workloads on-premise? What's your inference stack? I'm comparing Ollama vs vLLM vs llama.cpp for production."

## Key Metrics to Screenshot
- Benchmark results: Azure OpenAI vs Ollama (latency, throughput, cost)
- `docker compose ps` showing all services running (air-gapped mode)
- Network monitor proving zero external calls
- Langfuse trace showing local model name and inference time
