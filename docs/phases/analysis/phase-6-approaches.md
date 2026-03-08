---
phase: 6
date: "2026-03-08"
selected: A
---

# Phase 6 Implementation Approaches

## Context from Analysis

Key findings that shape the approach:
- **LLM generation has NO provider abstraction.** Agents use LangChain's `.ainvoke()` via injected `llm` objects. Only 3 files call LLM generation (reader.py, router.py, audit.py).
- **Embeddings already have BaseEmbedder ABC + factory.** Need to add an Ollama/local embedder.
- **Settings has no LLM_PROVIDER toggle.** Only Azure OpenAI config exists.
- **Local embeddings are a gap the spec missed.** Air-gapped mode can't call Azure for embeddings. Different dimensions (1536 Azure vs 768 local) require separate Qdrant collections.
- **Available local models:** qwen3:8b, qwen3:32b, command-r:35b (already pulled in Ollama).

## Approach A: LLM Provider Protocol + Ollama Embedder (Lean)

**Summary**: Add a thin `LLMProvider` Protocol for generation (wrapping LangChain), add `OllamaEmbedder` to the existing BaseEmbedder hierarchy, add settings toggle, add docker-compose.airgap.yml. Minimal refactoring -- the LLM is already injected everywhere.

**Pros**:
- Smallest blast radius -- 3 call sites already use injected LLMs
- Embeddings already have the right abstraction (BaseEmbedder ABC)
- LangChain's `ChatOllama` handles the Ollama HTTP API
- Tests use MockEmbedder (already exists) -- no new mock needed for embeddings

**Cons**:
- LangChain dependency for both Azure and Ollama (tight coupling to LangChain)
- Protocol wraps LangChain objects -- thin abstraction over thick dependency

**Effort**: M (1-2 weeks)
**Risk**: Low -- additive, no existing code changes beyond settings

## Approach B: Full Provider Abstraction (LangChain-free for generation)

**Summary**: Build our own `LLMProvider` Protocol with `generate()` and `stream()` methods that call Azure OpenAI and Ollama APIs directly via `httpx`. Remove LangChain dependency for generation. Keep LangChain only for LangGraph orchestration.

**Pros**:
- No LangChain coupling for inference -- httpx calls to Azure REST API and Ollama REST API
- Full control over retry, timeout, token counting, cost tracking per provider
- Easier to add new providers (any OpenAI-compatible API)
- Ollama's API is OpenAI-compatible -- can use same httpx client with different base URL

**Cons**:
- Larger refactor -- must replace LangChain chat model usage in agents
- LangGraph still needs LangChain-compatible objects for its node functions
- More code to maintain (retry logic, streaming, error handling)

**Effort**: L (2-3 weeks)
**Risk**: Medium -- LangGraph integration may resist LangChain removal

## Approach C: LangChain-native with ChatOllama + OllamaEmbeddings (Simplest)

**Summary**: Use LangChain's built-in `ChatOllama` and `OllamaEmbeddings` classes. Add a factory function that returns the right LangChain chat model based on `LLM_PROVIDER` setting. The existing agent code stays unchanged -- it already uses `.ainvoke()` on injected LLM objects.

**Pros**:
- Zero refactoring of agent code -- ChatOllama has the same `.ainvoke()` interface
- LangChain handles all Ollama API details
- OllamaEmbeddings integrates directly into the existing embedder pattern
- LangGraph integration is seamless (it expects LangChain objects)

**Cons**:
- Deeper LangChain lock-in
- Less control over Ollama-specific features (model loading, VRAM management)
- OllamaEmbeddings class may not match BaseEmbedder ABC -- needs wrapper

**Effort**: S (3-5 days)
**Risk**: Low -- purely additive, LangChain handles compatibility

## Recommendation

**Approach A** -- the Protocol-based abstraction is the right balance. It:
1. Keeps LangChain for what it's good at (LangGraph integration, chat model interface)
2. Adds our own thin abstraction for provider selection and configuration
3. Extends the existing embedder pattern (BaseEmbedder) with an OllamaEmbedder
4. Doesn't fight LangGraph's expectations

Approach B is over-engineered for this phase -- we'd be rewriting LangChain's chat model for no immediate benefit. Approach C is too simple -- no abstraction layer means provider-specific code leaks into agents.

Key additions regardless of approach:
- `OllamaEmbedder` in embeddings.py (extends BaseEmbedder)
- Settings: `LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`
- `docker-compose.airgap.yml`
- ADR-004: Ollama over vLLM
- Benchmark script: Azure vs Ollama (latency, throughput, quality)
- Red team: zero external calls, RBAC across providers, model-not-pulled error
