# Phase 6 Tracker: Air-Gapped Vault — Local Inference

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-6-air-gapped-vault.md`
**Depends on**: Phases 1-3

## Implementation Tasks

- [ ] `apps/api/src/infrastructure/llm/__init__.py`
- [ ] `apps/api/src/infrastructure/llm/provider.py` — abstract LLM provider interface
- [ ] `apps/api/src/infrastructure/llm/azure_openai.py` — Azure OpenAI implementation
- [ ] `apps/api/src/infrastructure/llm/ollama.py` — Ollama implementation
- [ ] `apps/api/src/config/settings.py` — MODIFY: add LLM_PROVIDER toggle
- [ ] `docker-compose.airgap.yml` — full air-gapped compose with Ollama
- [ ] `scripts/benchmark_local.py` — latency + throughput: Azure vs local
- [ ] `tests/integration/test_local_inference.py` — Ollama integration tests
- [ ] `docs/adr/004-ollama-over-vllm.md`

## Success Criteria

- [ ] `LLM_PROVIDER=ollama` — full RAG pipeline works with Llama 3
- [ ] `LLM_PROVIDER=azure` — same pipeline works with Azure OpenAI
- [ ] Air-gapped compose starts all services including Ollama
- [ ] Benchmark shows latency/throughput comparison
- [ ] Zero external API calls in air-gapped mode
- [ ] Langfuse traces local inference

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Local model | Llama 3 8B | | |
| Quantization | Q4_K_M | | |
| Provider abstraction | Protocol-based | | |
| vLLM vs Ollama | Ollama (Apple Silicon) | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Azure OpenAI latency (p50) | | ms |
| Ollama latency (p50) | | ms |
| Azure throughput | | queries/sec |
| Ollama throughput | | queries/sec |
| Azure cost per query | | EUR |
| Ollama cost per query | | EUR (amortized) |
| Ollama RAM usage | | GB |
| Model download size | | GB |
| RAG quality (Azure) | | precision@5 |
| RAG quality (Ollama) | | precision@5 |
| Break-even queries/day | | cloud vs local |

## Screenshots Captured

- [ ] Benchmark results table (Azure vs Ollama)
- [ ] `docker compose ps` (air-gapped mode)
- [ ] Network monitor (zero external calls)
- [ ] Langfuse trace (local model name)

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
