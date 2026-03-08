# ADR-007: Ollama over vLLM for Local Inference

**Status**: Accepted
**Date**: 2026-03-08
**Context**: Phase 6 -- Air-Gapped Vault

## Decision

Use **Ollama** for local inference in development and single-site deployments. Reserve **vLLM** for production Linux/NVIDIA environments.

## Context

Phase 6 requires a local LLM inference backend that runs entirely within the customer's network -- zero external API calls. Two viable options exist:

| Criteria | Ollama | vLLM |
|---|---|---|
| Apple Silicon (M-series) | Full support | No support (CUDA only) |
| Setup complexity | `brew install ollama` | CUDA toolkit + PyTorch + config |
| Docker deployment | Single container, zero config | Multi-step, GPU passthrough required |
| Model management | `ollama pull model:tag` | Manual download + conversion |
| Throughput (production) | Adequate for single-site | 2-5x higher with batching |
| GGUF quantization | Native | Requires conversion |
| OpenAI-compatible API | Built-in | Built-in |
| GPU memory management | Automatic | Manual configuration |

## Rationale

1. **vLLM has no Apple Silicon support.** Development happens on M4 Pro MacBook. vLLM is Linux+CUDA only. This is a non-starter for the development workflow.

2. **Ollama has zero-config Docker deployment.** `docker compose -f docker-compose.airgap.yml up` and Ollama is running with the model served. vLLM requires CUDA toolkit installation, GPU passthrough configuration, and manual model loading.

3. **Single-site deployment is the air-gapped use case.** The Swiss bank, Polish pharmaceutical manufacturer -- these are single-site deployments where one GPU server handles all inference. Ollama's throughput is sufficient for 2,400 queries/day at one site.

4. **vLLM's advantage is batch throughput.** With continuous batching, vLLM can serve 2-5x more concurrent requests. This matters for multi-tenant SaaS (not the air-gapped use case) or high-volume production (>10K queries/day per GPU).

## When This Decision Changes

Switch to vLLM when:
- **Production deployment on Linux/NVIDIA**: vLLM's continuous batching and PagedAttention provide 2-5x throughput improvement
- **Multi-GPU setups**: vLLM handles tensor parallelism natively; Ollama does not
- **Query volume exceeds 10K/day per GPU**: Ollama's single-request serving becomes a bottleneck
- **Model fine-tuning workflow**: vLLM integrates better with training pipelines

Keep Ollama when:
- **Development on Apple Silicon**: No alternative exists
- **Single-site deployment with <10K queries/day**: Simpler operations, same result
- **Customer IT team has no CUDA expertise**: Ollama's Docker deployment is self-service

## Consequences

- Development and CI use Ollama (works on any machine)
- Production Linux deployments can swap to vLLM by implementing `VLLMProvider` with the same `LLMProvider` Protocol
- The `LLMProvider` Protocol abstraction means zero code changes when switching -- only a settings change
- GPU memory management is handled by Ollama automatically; vLLM requires manual configuration

## Cost of the Wrong Choice

| Wrong Choice | Impact |
|---|---|
| Choosing vLLM for dev | Can't develop locally on Apple Silicon. Requires Linux VM or remote server for every code change. Adds 1-2 weeks to development cycle. |
| Choosing Ollama for high-volume production | At >10K queries/day, Ollama's throughput ceiling means queuing. Latency doubles under load. Switch to vLLM costs 1-2 days (new provider, same Protocol). |
| Not abstracting the provider | Locked to one backend. Switching requires refactoring every agent, every test. Phase 6's Protocol abstraction makes this a config change instead. |
