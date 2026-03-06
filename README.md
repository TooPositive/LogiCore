# LogiCore — Enterprise AI Operating System

AI-native platform for logistics & supply chain. Multi-agent orchestration, secure RAG, real-time streaming, EU AI Act compliance — all in one system.

## Quick Start

```bash
# 1. Clone & configure
cp .env.example .env
# Edit .env with your Azure OpenAI keys

# 2. Start infrastructure
make up

# 3. Verify
curl http://localhost:8080/api/v1/health
open http://localhost:3000      # Web dashboard
open http://localhost:3001      # Langfuse observability
open http://localhost:6333/dashboard  # Qdrant vector DB
```

## Architecture

| Service | Port | Purpose |
|---------|------|---------|
| API (FastAPI) | 8080 | Backend — agents, RAG, orchestration |
| Web (Next.js) | 3000 | Dashboard & operator UI |
| Qdrant | 6333 | Vector database (hybrid search) |
| PostgreSQL | 5432 | Relational data + LangGraph checkpointer |
| Redis | 6379 | Semantic caching |
| Langfuse | 3001 | LLM observability & cost tracking |
| Kafka | 9092 | Event streaming (optional profile) |

## Development

```bash
make api-dev    # FastAPI with hot reload
make web-dev    # Next.js dev server
make up-kafka   # Start with Kafka profile
make test       # Run tests
make lint       # Ruff linting
```

## Tech Stack

Python 3.12 (uv workspaces) | FastAPI | LangGraph | Azure OpenAI | Qdrant | PostgreSQL | Redis | Kafka | Langfuse | Next.js 15 | Tailwind CSS | shadcn/ui | Docker Compose

## Build Phases

| Phase | Codename | Focus |
|-------|----------|-------|
| 1 | Corporate Brain | Hybrid RAG + RBAC |
| 2 | Customs & Finance Engine | Multi-agent orchestration + HITL |
| 3 | Trust Layer | LLMOps, observability, evaluation |
| 4 | Air-Gapped Vault | Local inference, containerization |
| 5 | Regulatory Shield | EU AI Act Article 12 compliance |
| 6 | Fleet Guardian | Real-time streaming + Kafka |
| 7 | LLM Firewall | Security, guardrails, red teaming |

See `docs/phases/` for detailed specs per phase.
