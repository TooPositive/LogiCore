---
title: "One Environment Variable Separates Cloud AI from Air-Gapped AI"
subtitle: "How a Protocol-based abstraction made local inference a config change, not a rewrite"
phase: 6
series: "LogiCore — Building an Enterprise AI System"
date: "2026-03-08"
status: draft
tags: ["ai-architecture", "local-inference", "ollama", "air-gapped", "enterprise-ai"]
word_count: ~3200
---

# One Environment Variable Separates Cloud AI from Air-Gapped AI

## 1. The Meeting That Changes Everything

Karol flies to Zurich for the biggest deal LogiCore Transport has ever pursued. A private bank needs warehouse logistics for their document storage facility. Temperature-controlled vaults, biometric access, armored transport between branches. EUR 180,000/year contract. The bank's CISO, Dr. Meier, has one question.

"Where does the data go?"

Karol walks through the architecture. Qdrant for vector search. PostgreSQL for state. LangGraph for agent orchestration. Then he gets to inference. "We use Azure OpenAI for—"

"Stop." Dr. Meier closes his laptop. "No data leaves this building. Not to Microsoft. Not to anyone. Swiss banking regulation FINMA Circular 2018/3 requires it. Your competitors showed us an on-premise deployment last week."

The competitor's demo crashed twice. Their "on-premise mode" was a fork of their codebase with half the features disabled. But they had one. LogiCore doesn't.

Karol calls Warsaw. "We need the whole system running locally. Same features. No internet. How long?"

The answer, it turns out, is one environment variable. But getting to that answer required building something most "run AI locally" tutorials completely miss.

This is Phase 6 of a 12-phase AI system for a logistics company. Phase 1 proved that embeddings are mandatory for enterprise search (BM25 fails 50% of natural-language queries). Phase 2 benchmarked 6 re-ranking models and found that "multilingual training" doesnt mean "multilingual effectiveness." Phase 3 built invoice audit agents that physically cannot bypass human approval. Phase 4 cut AI costs 93% with model routing. Phase 5 caught judge bias inflating quality scores by 10-15%. Phase 6 asks a different question: what if the customer bans cloud APIs entirely?

## 2. The Abstraction Nobody Talks About

Donella Meadows writes in *Thinking in Systems* that the most impactful intervention point in a system is its paradigm — the mindset out of which the system arises. Most engineering teams treat "local inference" as a feature to add: swap the API endpoint, test a few queries, ship it. The paradigm shift is realizing that cloud vs local is a deployment decision, not an architecture decision. If your code knows which provider it's talking to, you've already lost.

The existing codebase had a subtle problem. Every agent used LangChain's `.ainvoke()` on an injected LLM object. This looks provider-agnostic. It isn't. The injection was always an Azure-configured LangChain model. No abstraction layer existed to swap backends without touching agent code.

The fix is a Python Protocol — structural subtyping, no inheritance required:

```python
@runtime_checkable
class LLMProvider(Protocol):
    async def generate(self, prompt: str, **kwargs) -> LLMResponse: ...
    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse: ...

    @property
    def model_name(self) -> str: ...
```

Any class that has these three methods satisfies `LLMProvider`. The Azure implementation wraps LangChain's `AzureChatOpenAI`. The Ollama implementation wraps `ChatOllama`. Neither knows about the other. A factory function reads the settings and returns the right one:

```python
def get_llm_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "azure":
            return AzureOpenAIProvider(...)
        case "ollama":
            return OllamaProvider(
                host=settings.ollama_host,
                model=settings.ollama_model,
            )
```

Martin Fowler's point about the interface segregation principle applies directly here. The agents dont need to know about Azure deployment names or Ollama model tags. They need `generate()` and thats it. The `LLMResponse` dataclass carries content, model name, token counts, and latency — enough for cost tracking and observability regardless of provider.

## 3. The Gap Every Tutorial Misses

Everyone writing about local LLM deployment focuses on generation. "Replace your OpenAI call with an Ollama call." Thats the easy part. The part they skip: embeddings.

LogiCore's search pipeline embeds queries with Azure's `text-embedding-3-small` (1536 dimensions). In air-gapped mode, Azure isnt available. That means the entire search pipeline — the core feature, the thing that makes everything else work — breaks silently. No error. Just zero results from Qdrant because you cant query 1536-dimension vectors with 768-dimension query embeddings.

The solution required extending the existing embedder abstraction:

```python
class OllamaEmbedder(BaseEmbedder):
    async def _call_embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._host}/api/embed"
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "model": self._model,
                "input": texts,
            }, timeout=60.0)
```

Chose httpx direct calls over LangChain's `OllamaEmbeddings` wrapper. One fewer dependency. Full control over timeouts. Same result.

But the dimension mismatch has a deeper implication. You cant just add a local embedder and call it done. Air-gapped deployments need their own Qdrant collection, indexed with the local embedding model. Cloud-to-air-gap migration requires a full re-index of every document. Thats an operational step most architecture docs never mention.

## 4. The Integration Surprise That Broke Everything

Gene Kim observes in *The Phoenix Project* that the most dangerous assumptions are the ones you dont know you're making. The assumption here: LLM output is always just text.

First end-to-end test with Ollama's qwen3 model. The invoice reader agent sends a contract excerpt, asks for rate extraction in JSON format. Expected output:

```json
[{"contract_id": "C-2024-001", "rate": "0.45", "currency": "EUR"}]
```

Actual output:

```
<think>The user wants me to extract rates from this contract text.
I can see the rate is EUR 0.45 per kilogram for standard cargo.
Let me format this as JSON...</think>
[{"contract_id": "C-2024-001", "rate": "0.45", "currency": "EUR"}]
```

The `<think>` prefix broke the JSON parser completely. Zero rates extracted. Every invoice audit returned "no contract rates found." If this had shipped to production without end-to-end testing, the entire invoice audit system would silently fail on every air-gapped deployment.

Two lines of regex:

```python
think_pattern = re.compile(r"<think>.*?</think>", re.DOTALL)
content = think_pattern.sub("", content).strip()
```

The lesson isnt about regex. Its about the gap between "the API works" (unit test passes) and "the system works" (end-to-end test reveals a model behavior nobody documented). This is Nassim Taleb's domain of unknown unknowns — you cant plan for what you dont know you dont know. You can only run the actual system and see what breaks.

## 5. The Financial Precision Question

| Provider | Rate Input | Extracted Value | Correct? |
|---|---|---|---|
| Azure GPT-5.2 | "EUR 0.45/kg" | 0.45 | Yes |
| Ollama qwen3:8b (Q4) | "EUR 0.45/kg" | 0.45 | Yes |
| Azure GPT-5.2 | "Stawka EUR 1.85 za kg" | 1.85 | Yes |
| Ollama qwen3:8b (Q4) | "Stawka EUR 1.85 za kg" | 1.85 | Yes |
| Ollama qwen3:8b (Q4) | "EUR 720.00 za transport" | 720.00 | Yes |

The spec's own risk analysis flagged quantization precision as the highest-risk technical decision. Q4 quantization reduces floating-point precision. If the model reads "EUR 0.45/kg" and extracts "EUR 0.44/kg", thats EUR 0.01 per invoice. Across 12,000 invoices/year, systematic extraction error compounds.

Tested 10 real contract excerpts through the local model — 5 English, 5 Polish. All 10 extracted the correct EUR amount. The rate parsing pipeline uses Python's `Decimal` type (exact arithmetic, no floating-point drift), so even if the model outputs "0.449999", `Decimal("0.449999")` preserves it without rounding.

Honest caveat: 10 clean excerpts is not production validation. Real contracts have 47 pages with rates buried in clause 12.3.1(b), surcharges in footnotes, amendments that override base rates. The 10/10 proves that Q4 quantization doesnt corrupt basic rate extraction. It doesnt prove the model finds rates in messy real-world documents. Thats Phase 7's routing benchmark.

## 6. The Cost Decision

Peter Drucker's observation that "what gets measured gets managed" applies in reverse here: what gets assumed gets mis-managed. Most "cloud vs local" comparisons assume unrouted cloud pricing. Thats the wrong comparison.

| Deployment | Cost Model | At 2,400 queries/day | At 10,000 queries/day |
|---|---|---|---|
| Cloud (unrouted, all GPT-5.2) | EUR 0.018/query | EUR 15,768/year | EUR 65,700/year |
| Cloud (routed, nano/mini mix) | EUR 0.005/query | EUR 4,380/year | EUR 18,250/year |
| Local (Ollama, amortized GPU) | EUR 0.00/query + EUR 5,000/year hardware | EUR 5,000/year | EUR 5,000/year |

Break-even against routed cloud: 7,100 queries/day. Below that, cloud with model routing (Phase 4) is cheaper. Above that, local wins on pure cost.

But cost is the wrong frame for the Swiss bank decision. Dr. Meier doesnt care whether local costs EUR 620 more or EUR 620 less per year. FINMA Circular 2018/3 says data stays on-premise. The cost comparison is irrelevant when the alternative is losing the EUR 180,000/year contract.

The architect recommendation: deploy local when regulatory constraints prohibit cloud, regardless of cost. Deploy cloud with model routing when regulations allow, unless query volume exceeds 7,100/day. The business case for air-gapped is compliance, not cost optimization.

## 7. What Breaks (and Where Phase 7 Picks Up)

Three boundaries found:

**Reasoning latency.** Extraction queries average 22 seconds on dev hardware. Reasoning queries average 96 seconds — 4x slower. Dev hardware (Apple Silicon, sequential inference) isnt representative of production, but the 4x ratio between extraction and reasoning probably holds on NVIDIA too. Phase 7 uses this ratio to set routing thresholds: extraction stays local, complex reasoning escalates to cloud when regulations allow.

**Single GPU = single point of failure.** Air-gapped means no cloud fallback by definition. GPU dies at 2 AM, all AI features offline. 50 invoice audits at EUR 135 manual cost each = EUR 6,750/day downtime. Consumer GPUs under sustained load have higher failure rates than enterprise hardware. Phase 7 builds circuit breaker routing with cache fallback for air-gapped deployments.

**The head-to-head quality gap is unknown.** The local model got 10/10 on financial extraction and 15/15 on keyword matching. But these are easy bars. The full 52-query ground truth from Phase 2 hasnt been run through both providers for a category-by-category comparison. That comparison is Phase 7's input for routing thresholds — you cant decide "route X% local, Y% cloud" without knowing WHERE local breaks.

## 8. What I'd Do Differently

Eric Ries writes in *The Lean Startup* about the minimum viable product — the fastest way to learn. Looking back, I built the provider abstraction before validating the hardest assumption (financial extraction accuracy). If I'd run the 10-contract extraction test on day one, I would have found the think-tag bug immediately and saved a day of debugging. The Protocol is elegant engineering. The extraction test is the business validation. Business validation first.

I also underestimated the embedding problem. The spec had a full section on local LLM generation. Zero mention of local embeddings. That gap in the spec became a gap in the implementation plan, caught only during the analysis phase. If I were advising a team on air-gapped deployment, the first question would be "whats your embedding strategy?" not "which local model?"

The benchmark script includes a mock "dry-run" mode that produces simulated numbers (87% local vs 93% cloud). I thought it would be useful for testing the script without Ollama running. Instead it created a contradiction: mock says 87%, live tests say 100%. Different metrics measuring different things, but confusing to anyone reading the tracker. I'd remove the mock accuracy number entirely and just test the script's output format with clearly synthetic data. Lesson: mock data that looks real is worse than no data.

## 9. Vendor Lock-in & Swap Costs

| Component | Current | Alternative | Swap Cost | Swap Trigger |
|---|---|---|---|---|
| LLM provider | Ollama | vLLM | 1-2 days (new provider class, same Protocol) | >10K queries/day or multi-GPU deployment |
| LLM model | qwen3:8b | llama4-scout, command-r | 0 (env var change) | Language requirements, reasoning quality needs |
| Embedding model | nomic-embed-text (768d) | bge-m3 (1024d) | Full re-index of Qdrant collection | Multilingual embedding quality needs |
| Orchestration | LangGraph + LangChain | Direct API + custom state machine | 2-3 weeks (significant refactor) | LangChain introduces breaking changes |
| Container runtime | Docker Compose | Kubernetes | 1-2 weeks (Helm charts, operators) | Multi-site deployment, auto-scaling |

The Protocol abstraction is the insurance policy. Adding an Anthropic provider, a vLLM provider, or a TensorRT-LLM provider is the same task: implement three methods, register in the factory. Agents dont change. Tests dont change. RBAC doesnt change.

The riskiest lock-in isnt the LLM provider — its the embedding model. Changing embeddings means re-indexing every document in Qdrant. At 10,000 documents, thats minutes. At 1M documents, thats hours. The embedding choice is stickier than the generation choice.

## 10. Series Close

The Docker Compose overlay that makes it all work is 37 lines:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama-models:/root/.ollama
    deploy:
      resources:
        reservations:
          memory: 16G
  api:
    environment:
      LLM_PROVIDER: ollama
      EMBEDDING_PROVIDER: ollama
      OLLAMA_HOST: http://ollama:11434
```

One command: `docker compose -f docker-compose.yml -f docker-compose.airgap.yml up`. The bank's IT team deploys the entire AI system — search, agents, human approval gates, observability — without touching the internet.

Karol flies back to Zurich. This time Dr. Meier watches the entire demo run on a laptop disconnected from WiFi. Same search results. Same audit workflow. Same RBAC. The only visible difference: responses take 2 seconds instead of 0.5 seconds.

"Acceptable," Dr. Meier says. He opens his laptop again.

Phase 6/12 of the LogiCore series. Next up: that GPU is a single point of failure. When it dies at 2 AM in the air-gapped vault, there is no cloud to fall back to. Phase 7 builds the resilience layer.
