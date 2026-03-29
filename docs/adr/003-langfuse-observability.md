# ADR-003: Langfuse for LLM Observability

## Status
Accepted

## Context
Need full observability over multi-agent LLM pipelines: token costs, latency per step, prompt/response tracing, evaluation scores. Must be self-hostable for air-gapped deployments (Phase 4).

## Decision
**Langfuse** (self-hosted) as the primary LLM observability platform.

## Rationale

| Criteria | Langfuse | LangSmith | Arize Phoenix |
|----------|----------|-----------|---------------|
| Self-hosted | Yes (Docker) | Cloud only | Yes |
| Cost tracking | Built-in per-model pricing | Yes | Limited |
| Evaluation | Scores, datasets, annotation | Full suite | Traces only |
| LangGraph integration | Via callback handler | Native | Via OTEL |
| EU data residency | Full control (self-hosted) | US-hosted | Self-hosted option |

## Consequences
- Self-hosted = own the infra (Postgres backend, managed via Compose)
- Langfuse callback handler wired into every LangGraph node
- Enables Phase 3 FinOps dashboards (cost per query, cache hit rates)
- Phase 5 compliance logs can reference Langfuse trace IDs
