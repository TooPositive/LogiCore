# Phase 6: "The Air-Gapped Vault" — Infrastructure & Local Inference

## Business Problem

Swiss banks, Polish manufacturers, EU healthcare providers — they cannot send sensitive data to OpenAI's API. Regulatory requirements mandate that financial documents, patient records, and trade secrets never leave the internal network. Cloud AI is a non-starter.

**CTO pain**: "Our legal team says we can't use OpenAI for anything touching customer financial data. But the board wants AI. Build it on-premise."

## Real-World Scenario: LogiCore Transport

**Feature: On-Premise Deployment Mode**

LogiCore Transport signs a contract with a Swiss private bank for warehouse logistics. The bank's CISO says: "No data leaves our network. Not to OpenAI, not to Azure, not to anyone. Show us it runs locally or we walk."

**The deployment meeting**: Change one line in `.env`: `LLM_PROVIDER=ollama`. Run `docker compose -f docker-compose.yml -f docker-compose.airgap.yml up`. The entire system starts — Qdrant, PostgreSQL, Redis, Langfuse, LangGraph agents — all running inside the bank's network. Llama 4 Scout (17B active / 109B MoE, quantized to ~24GB) handles inference locally — GPT-4-class quality on consumer GPU hardware.

**What stays the same**: Anna Schmidt searches contracts — same hybrid search, same RBAC, same re-ranking. The invoice audit workflow runs — same agents, same HITL gateway, same compliance logging. The only difference: slower inference (2s vs 0.5s) and no API bill.

**What changes**: Complex multi-hop reasoning ("analyze this contract against EU AI Act requirements and draft a compliance report") is strong on Llama 4 Scout but still trails GPT-5.2 on the hardest tasks. For extreme edge cases, Qwen 3 (235B MoE, ~22B active) offers an alternative local model. Solution: route most tasks locally, flag the hardest multi-hop tasks for human review or cloud escalation. Phase 7 makes this automatic.

**Cost comparison for the sales pitch**: 10,000 queries/day at routed cloud pricing (avg €0.005/query with GPT-5 nano/mini mix) = €50/day = €18,250/year. Local (Llama 4 Scout): €0/query after hardware (amortized over 3 years: ~€15,000/year for a decent GPU server). Net saving: €3,250/year at routed pricing. At unrouted GPT-5.2 pricing (€0.018/query): €65,700/year savings. The business case depends on your model routing maturity.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Air-gapped deployment | "No data leaves this building" guarantee | Unlocks regulated industries: banking, healthcare, defense |
| LLM provider abstraction | One config change to swap cloud ↔ local AI | No code rewrite, same features, different backend |
| MoE architecture + quantization | Llama 4 Scout (109B MoE, 17B active) runs on consumer GPU (~24GB VRAM) | GPT-4-class quality without expensive GPU clusters |
| Docker Compose (single file) | `docker compose up` → entire AI system running | IT team deploys in 10 minutes, not 10 weeks |
| Ollama integration | Local AI inference that "just works" | Familiar developer experience, no CUDA debugging |

## Architecture

```
LogiCore (Air-Gapped Deployment)
  ├── Ollama / llama.cpp (local inference)
  │     └── Llama 4 Scout (17B active / 109B MoE) or Qwen 3 (235B MoE, ~22B active)
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
- Llama 4 Scout: 17B active params from 109B MoE — fits quantized in ~24GB VRAM (consumer GPU territory)
- Qwen 3: 235B MoE with ~22B active — alternative for tasks where Llama 4 underperforms
- Full `docker-compose.yml` delivers entire stack — zero external dependencies

## Implementation Guide

### Prerequisites
- Phases 1-3 complete
- Ollama installed locally (`brew install ollama`)
- Model pulled: `ollama pull llama4-scout` (or `ollama pull qwen3` for alternative)
- Understanding of quantization trade-offs and MoE activation patterns

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
OLLAMA_MODEL=llama4-scout    # or "qwen3" for alternative
```

### Success Criteria
- [ ] `LLM_PROVIDER=ollama` — full RAG pipeline works with local Llama 4 Scout
- [ ] `LLM_PROVIDER=azure` — same pipeline works with Azure OpenAI (no code change)
- [ ] Air-gapped compose starts all services including Ollama
- [ ] Benchmark script shows latency/throughput comparison
- [ ] Zero external API calls in air-gapped mode (verified with network monitor)
- [ ] Langfuse traces local inference with model name and token counts

## Cost of Getting It Wrong

Air-gapped deployment eliminates cloud data risk. It introduces different risks.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Quantization rounding on EUR** | Q4 quantization introduces systematic rounding. Every invoice calculation off by EUR 10-50. Nobody benchmarked numerical precision. | EUR 120,000-600,000/year if undetected (systematic across 12,000 invoices) | Continuous if not benchmarked |
| **GPU hardware failure** | Single GPU server dies. Air-gapped = no cloud fallback by definition. ALL AI features offline. | EUR 6,750/day (50 invoice audits at EUR 135 manual each) + fleet monitoring gap | 1-3 days/year |
| **12% quality gap on financial reasoning** | Llama 4 Scout at 88% vs GPT-5.2 at 100% on multi-hop. 12% of complex audits return wrong results. | EUR 5,000-50,000/year (wrong legal/financial advice) | 2-5/month for complex queries |
| **Silent quality degradation** | Can't phone home for drift detection. Local model quality degrades after quantization update. No external benchmark. | EUR 1,000-5,000/month accumulated | Continuous without local eval suite |

**The CTO line**: "The Swiss bank pays for air-gapped deployment because a data leak ends their banking license. But running quantized models on financial calculations without numerical precision benchmarks introduces systematic EUR 10-50 rounding errors across every invoice. Different risk, same impact."

### Numerical Precision Benchmark (CRITICAL for Financial Use Case)

Before deploying any quantized model for financial calculations, run this benchmark:

```python
# Run 1,000 invoice calculations through both models
test_invoices = load_test_invoices()  # known correct answers
for invoice in test_invoices:
    cloud_result = gpt5_calculate(invoice)  # ground truth
    local_result = llama4_q4_calculate(invoice)  # quantized
    deviation = abs(cloud_result.amount - local_result.amount)
    assert deviation < 0.01, f"Rounding error: EUR {deviation} on {invoice.id}"
```

If systematic deviation > EUR 0.01/invoice, use Q8 quantization (higher precision, more VRAM) or apply post-processing rounding correction.

### Air-Gap Constraint Cascade

The air-gap requirement ripples through every phase:

| Phase | Cloud Assumption | Air-Gap Reality |
|---|---|---|
| Phase 2 | Cohere re-ranker | Must use local cross-encoder (ms-marco-MiniLM) |
| Phase 4 | Langfuse cloud | Must self-host Langfuse (already planned) |
| Phase 5 | Judge uses Claude Opus | Must use local judge model (quality risk) |
| Phase 7 | Circuit breaker falls to cloud | No cloud fallback exists — need GPU redundancy |
| Phase 10 | Red team tools may need internet | All security testing must run locally |

## Decision Framework: Cloud vs Local Inference

The 2026 model landscape has fundamentally changed the cloud-vs-local calculus. Llama 4 Scout delivers GPT-4-class quality locally, and Qwen 3 pushes even further. The decision is no longer "cloud for quality, local for compliance" — it's nuanced.

### Decision Tree

```
Does the deployment have a regulatory constraint requiring data on-premise?
  │
  ├── YES → Local inference is mandatory. Full stop.
  │     └── Primary: Llama 4 Scout (17B active / 109B MoE)
  │     └── Alternative: Qwen 3 (235B MoE, ~22B active)
  │     └── Lightweight/edge: Qwen 3.5 small models (<8B)
  │
  └── NO → Cost comparison at your query volume determines the winner.
        │
        ├── Do you already have GPU hardware (or can amortize it)?
        │     └── YES → likely local (see break-even analysis below)
        │     └── NO → cloud is cheaper until volume justifies hardware purchase
        │
        └── Do you need frontier-level reasoning (GPT-5.2 / Claude Opus 4.6)?
              └── YES → cloud for hardest tasks, local for the rest (hybrid)
              └── NO → local handles most workloads at GPT-4-class quality
```

### Break-Even Analysis: Cloud vs Local (2026 Pricing)

```
Cloud cost (routed):  avg €0.005/query (nano/mini mix) + €180/mo infra
Cloud cost (unrouted): avg €0.018/query (all GPT-5.2) + €180/mo infra

Local cost:  €1,250/mo (GPU server amortized over 3 years) + €0.00/query

Break-even vs routed cloud:
  €1,250 - €180 = €1,070 / €0.005 = 214,000 queries/month
  = ~7,100 queries/day

Break-even vs unrouted cloud:
  €1,070 / €0.018 = 59,444 queries/month
  = ~1,980 queries/day

LogiCore today (~2,400 queries/day):
  - vs unrouted cloud: local saves ~€470/month ✓
  - vs routed cloud: cloud is still cheaper by ~€730/month ✗
  - BUT: if regulatory constraint exists, local is the only option regardless

At 10x scale (24K queries/day):
  - vs unrouted cloud: local saves ~€11,700/month
  - vs routed cloud: local saves ~€2,380/month
```

### Hardware Requirements (2026 Local Models)

| Model | Architecture | Active Params | Total Params | VRAM (Q4 quant) | Recommended GPU | Quality Level |
|---|---|---|---|---|---|---|
| Llama 4 Scout | MoE | 17B | 109B | ~24GB | RTX 4090 / A6000 | GPT-4 class |
| Qwen 3 | MoE | ~22B | 235B | ~48GB | 2x RTX 4090 / A100 | GPT-4+ class |
| Qwen 3.5 small | Dense | 3-8B | 3-8B | 4-8GB | Any modern GPU | Good for simple tasks |
| Llama 4 Scout (FP16) | MoE | 17B | 109B | ~220GB | 3x A100 80GB | Maximum quality |

### Cost Comparison Table (2026)

| Provider | Model | Input/1M tokens | Output/1M tokens | Cost per avg query (3K in, 500 out) |
|---|---|---|---|---|
| Cloud | GPT-5 nano | $0.05 | $0.40 | $0.00035 |
| Cloud | GPT-5 mini | $0.25 | $2.00 | $0.00175 |
| Cloud | GPT-5.2 | $1.75 | $14.00 | $0.01225 |
| Cloud | Claude Sonnet 4.6 | $3.00 | $15.00 | $0.01650 |
| Cloud | Claude Opus 4.6 | $5.00 | $25.00 | $0.02750 |
| Local | Llama 4 Scout | $0.00 | $0.00 | $0.00 (after hardware) |
| Local | Qwen 3 | $0.00 | $0.00 | $0.00 (after hardware) |

### Performance Benchmarks (2026 Local Models)

The gap between local and cloud models has narrowed dramatically since 2024.

| Task Type | Llama 4 Scout (local) | Qwen 3 (local) | GPT-5.2 (cloud) | Notes |
|---|---|---|---|---|
| Document search / RAG | 95% | 96% | 100% (baseline) | Near-parity for retrieval-augmented tasks |
| Classification / routing | 97% | 97% | 100% | MoE models excel at classification |
| Data extraction | 94% | 95% | 100% | Strong on structured extraction |
| Multi-hop reasoning | 88% | 91% | 100% | Gap remains on hardest reasoning chains |
| Code generation | 92% | 94% | 100% | Competitive on common patterns |
| Latency (TTFT) | ~200ms | ~300ms | ~150ms | Local is competitive, not faster |
| Throughput (tokens/sec) | ~40 t/s | ~30 t/s | ~80 t/s | Cloud still wins on throughput |

**Key takeaway**: For 90%+ of enterprise queries (search, classification, extraction, summaries), local models in 2026 are functionally equivalent to cloud. The remaining gap is in frontier reasoning — which can be selectively routed to cloud if regulations allow a hybrid approach.

## LinkedIn Post Template

### Hook
"Swiss banks and Polish manufacturers can't send their data to OpenAI. Here's the modern on-premise AI stack for 2026."

### Body
Built the same multi-agent system running 100% locally. Zero external API calls.

The stack:
- Ollama serving Llama 4 Scout (17B active / 109B MoE — GPT-4-class quality, runs on consumer GPU)
- Qdrant for hybrid search
- LangGraph for orchestration
- Langfuse for observability
- PostgreSQL for state

Everything in one `docker-compose.yml`. One command to start. One command to tear down.

The abstraction layer is the key: a Protocol-based LLM provider. Swap `LLM_PROVIDER=azure` to `LLM_PROVIDER=ollama` in your `.env`. Same agents, same RAG, same HITL gates. Different inference backend.

Performance on Llama 4 Scout? Genuinely strong — GPT-4-class quality on structured tasks, solid on multi-hop reasoning too. For the absolute hardest cases, Qwen 3 (235B MoE) is an alternative. The 2026 local model landscape has closed most of the cloud quality gap.

Cost comparison:
- Cloud (GPT-5.2, unrouted): ~$0.018 per query
- Cloud (routed nano/mini mix): ~$0.005 per query
- Local Llama 4 Scout: $0.00 per query (after hardware amortization)

For a company processing 10K queries/day on unrouted cloud, that's $180/day saved.

### Visual
Side-by-side: "Cloud Architecture" (data leaving network boundary) vs "Air-Gapped Architecture" (everything inside Docker network). Cost comparison table.

### CTA
"Are you running any AI workloads on-premise? With Llama 4 Scout hitting GPT-4-class quality, the cloud vs local math has changed. What's your inference stack?"

## Key Metrics to Screenshot
- Benchmark results: Azure OpenAI vs Ollama (latency, throughput, cost)
- `docker compose ps` showing all services running (air-gapped mode)
- Network monitor proving zero external calls
- Langfuse trace showing local model name and inference time
