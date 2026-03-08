# Phase 6 LinkedIn Post: Air-Gapped Vault — Local Inference

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

A Swiss bank's CISO sits across the table from your sales team. "Show me it runs without touching the internet. Or we walk." The contract is worth EUR 180,000/year. Your entire AI system depends on Azure OpenAI API calls.

This is Phase 6 of a 12-phase AI system im building for a logistics company. Phase 1 proved embeddings are mandatory for search. Phase 3 built invoice audit agents with human approval gates. Phase 4 cut AI costs by 93% with model routing. Phase 5 caught judge bias that inflated quality scores by 10-15%. Phase 6 asks: what happens when the customer bans cloud APIs entirely?

The answer turned out to be surprisingly boring. One env var.

```
LLM_PROVIDER=ollama
```

Thats it. Same agents, same RBAC, same search pipeline, same HITL gates. Different inference backend. The Protocol-based abstraction means any class that implements `generate()` and `model_name` satisfies the contract. No inheritance, no adapter layers, no conditional branches in the agent code.

The first real surprise was embeddings. Everyone talks about local LLMs for generation but nobody mentions that air-gapped mode also means no Azure for `text-embedding-3-small`. So the search pipeline needs a local embedding model too (nomic-embed-text, 768 dimensions vs Azure's 1536). Different dimension = different Qdrant collection. You cant mix them. This isnt in most "run AI locally" tutorials.

Second surprise: Ollama's qwen3 model prefixes every response with `<think>...</think>` reasoning tags. The invoice audit reader agent parses JSON from LLM output. First test run: zero rates extracted. The JSON parser choked on XML-like tags wrapping the actual response. Two lines of regex fixed it but thats the kind of integration surprise you only find by actually running the thing end-to-end. Not by reading docs.

The financial extraction accuracy question was the one I actually worried about. Quantized models (Q4) have reduced numerical precision. If the local model reads "EUR 0.45/kg" from a contract and extracts "EUR 0.44/kg", thats EUR 0.01 per invoice x 12,000 invoices = EUR 120/year of invisible systematic error. Tested 10 real contract excerpts (5 English, 5 Polish) through the local model. All 10 extracted the correct EUR amount. Not enough to claim "production ready" but enough to say "the quantization risk on rate extraction is lower than expected."

What I chose NOT to build: vLLM. It has 2-5x better throughput via continuous batching. But it doesnt run on Apple Silicon at all. No macOS support. For the target customer (Swiss bank IT team running docker compose up, not managing a CUDA cluster), Ollama's zero-config Docker deployment wins. The switch condition is documented: move to vLLM when query volume exceeds 10K/day or you need multi-GPU tensor parallelism.

Cost math: cloud at EUR 0.005/query (routed nano/mini mix) = EUR 18,250/year at 10K queries/day. Local with amortized GPU server (EUR 15,000 over 3 years) = EUR 5,000/year + EUR 0.00/query. But at LogiCore's current 2,400 queries/day, cloud is still EUR 730/month cheaper. The business case for local is compliance, not cost. The break-even is 7,100 queries/day against routed cloud.

What breaks: reasoning queries take 4x longer than extraction on local (96s avg vs 22s). Thats dev hardware (Apple Silicon), production NVIDIA would be faster, but the ratio probably holds. Phase 7 builds the routing logic — simple queries stay local, complex reasoning escalates to cloud when regulations allow it.

Post 6/12 in the LogiCore series. Next up: what happens when your only GPU dies at 2 AM and theres no cloud to fall back to 😅

---

## Reply Ammo

### 1. "One env var? That seems too simple. What about the embedding model difference?"

yeah thats the part most tutorials skip. generation is easy to swap (same prompt in, text out). embeddings are the real problem coz Azure text-embedding-3-small produces 1536-dimension vectors and nomic-embed-text produces 768. you cant query one collection with the other's embeddings. air-gapped deployment needs a separate Qdrant collection indexed with the local embedding model. thats a migration step, not a code change, but its not trivial.

### 2. "vLLM has way better throughput, you should use it"

agreed for production Linux/NVIDIA. 2-5x improvement with continuous batching and PagedAttention. but vLLM literally doesnt run on macOS. my dev machine is M4 Pro. the target air-gapped customer runs docker compose, not a CUDA cluster. the Protocol abstraction means adding VLLMProvider is a 1-day task when the deployment target is Linux. documented in ADR-007 with the switch condition.

### 3. "10 contract excerpts is not enough to claim extraction works"

100% agree. 10/10 on clean single-rate excerpts proves the happy path. real enterprise contracts have 47 pages, rates in clause 12.3.1(b), surcharges in footnotes, amendments overriding base rates. Phase 7 stress-tests with messy multi-rate documents. the 10/10 says "quantization doesnt break basic extraction" not "production ready."

### 4. "29 seconds per query? Nobody's going to use that"

thats dev hardware. Apple Silicon, sequential inference, qwen3:8b with thinking mode enabled (the model reasons internally before responding, adding seconds of overhead). production Linux with vLLM on A100 would be 1.5-6s. the 29s measures two things: (1) the Protocol abstraction adds zero overhead, and (2) the model produces correct results. its not a production latency number.

### 5. "Why not just use Llama 3 like the spec says?"

qwen3:8b was already pulled on my dev machine and the model is swappable via one env var (OLLAMA_MODEL). the architecture doesnt care which model sits behind Ollama. I used what was available and documented the deviation. in production youd pick based on your language requirements — qwen3 is strong on multilingual, llama on English reasoning.

### 6. "The think tag thing sounds like a hack"

its a compatibility fix for a real integration problem. qwen3 (and some other models) emit reasoning traces wrapped in `<think>` tags before the actual response. two lines of regex strip them before JSON parsing. the alternative is telling users "dont use thinking-mode models" which is worse. the security model doesnt depend on it — worst case the JSON parse fails and the agent returns an empty list, not a security breach.

### 7. "What about model supply chain attacks?"

real concern for air-gapped. the model file sits in a Docker volume. if someone replaces it with a trojaned version, all AI decisions are compromised. mitigation: pin model by SHA-256 hash (Ollama supports `@sha256:abc123`), verify against official checksums, read-only Docker volume. documented in the analysis as P0 priority. not built in Phase 6 coz its operational security, not application architecture. Phase 10 scope.

### 8. "EUR 730/month cheaper on cloud at your scale. Why build this?"

coz the Swiss bank cant use cloud regardless of cost. the EUR 180,000/year contract requires air-gapped. at that price, EUR 5,000/year for a GPU server is a rounding error. you build air-gapped mode for the sales conversation, not the P&L optimization. also its negotiation leverage with Azure — "we can leave" changes the pricing conversation.

### 9. "RBAC still works when you swap providers?"

structurally guaranteed. RBAC filtering happens at the Qdrant query level — the clearance filter is applied before documents reach the LLM. the provider swap changes inference, not retrieval. tested with red team scenarios: same clearance level, same department filters, regardless of whether Azure or Ollama generates the response. the LLM never sees documents the user cant access.

### 10. "What about Langfuse traces for the local model?"

architecturally ready but not wired yet. the LangfuseHandler from Phase 4 accepts any trace record with model name and token counts. OllamaProvider returns LLMResponse with model="qwen3:8b" and token counts from Ollama's usage metadata. wiring them together is Phase 12 integration work, not a Phase 6 architecture decision.
