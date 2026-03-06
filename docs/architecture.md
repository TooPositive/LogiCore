# LogiCore Architecture

## Service Map

```
                    ┌─────────────┐
                    │   Web UI    │ :3000
                    │  (Next.js)  │
                    └──────┬──────┘
                           │ HTTP
                    ┌──────▼──────┐
                    │  FastAPI    │ :8080
                    │  (Python)   │
                    └──┬──┬──┬───┘
                       │  │  │
          ┌────────────┘  │  └────────────┐
          │               │               │
   ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐
   │   Qdrant    │ │ PostgreSQL │ │    Redis    │
   │  (vectors)  │ │  (state)   │ │  (cache)   │
   │  :6333      │ │  :5432     │ │  :6379     │
   └─────────────┘ └────────────┘ └─────────────┘

   ┌─────────────┐ ┌────────────┐
   │   Langfuse  │ │   Kafka    │  (optional)
   │  (traces)   │ │ (streams)  │
   │  :3001      │ │  :9092     │
   └─────────────┘ └────────────┘
```

## Data Flow

1. **User query** → Web UI → FastAPI → LangGraph agent
2. **RAG retrieval** → Qdrant hybrid search (BM25 + dense vectors)
3. **LLM call** → Azure OpenAI (or local Ollama in Phase 4)
4. **Caching** → Redis semantic cache (hit = skip LLM)
5. **Tracing** → Every step logged to Langfuse
6. **State** → LangGraph checkpointer in PostgreSQL
7. **Events** → Kafka topics for real-time streaming (Phase 6)

## Security Model

| Layer | Mechanism |
|-------|-----------|
| API auth | JWT tokens (Phase 2+) |
| Document access | RBAC via Qdrant metadata filtering |
| LLM safety | Input/output guardrails (Phase 7) |
| SQL agents | Read-only roles, sandboxed execution |
| Compliance | Immutable audit logs (Phase 5) |
| Network | Docker network isolation per service |

## Port Reference

| Port | Service | Profile |
|------|---------|---------|
| 3000 | Next.js web | default |
| 3001 | Langfuse | default |
| 5432 | PostgreSQL | default |
| 6333 | Qdrant HTTP | default |
| 6334 | Qdrant gRPC | default |
| 6379 | Redis | default |
| 8080 | FastAPI | default |
| 9092 | Kafka | kafka |
| 8090 | Kafka UI | kafka |
