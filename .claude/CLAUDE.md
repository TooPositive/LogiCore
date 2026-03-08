# LogiCore — Claude Code Project Instructions

## What This Is

Enterprise AI OS for logistics — 12-phase capstone project demonstrating AI Solution Architect skills. Python 3.12, FastAPI, LangGraph, Qdrant, PostgreSQL, Redis, Kafka, Langfuse, Next.js 15, Rust simulator.

## The Architect Mindset (MANDATORY)

This project exists to prove AI Solution Architect capability to CTOs. The question is NEVER "does it work?" The question is always: **"What should the business DO, and why this over the alternatives?"**

### The Core Rule

> Every conclusion must be ACTIONABLE. If a CTO reads it and doesn't know what decision to make, it's junior framing. Rewrite it.

### Junior Framing vs Architect Framing

| Junior (NEVER write this) | Architect (ALWAYS write this) | Why it matters |
|---|---|---|
| "It works" | "It works, AND here's why this over 3 alternatives" | "It works" is a developer's finish line. An architect's finish line is a recommendation. |
| "BM25 is fine if users know exact terms" | "BM25 alone is NOT viable for human-facing search. Users never use document terminology. Period." | When does a warehouse worker search "termination procedures pursuant to BetrVG Section 102"? Never. Treating a 50%-failure mode as "viable" is junior cope. |
| "Dense is better than BM25" | "Embeddings are mandatory. BM25's only role: supplementing dense search with code/ID precision." | "Better" is a comparison. The architect frames the DECISION: what's mandatory, what's optional, what's each component's role. |
| "Latency is 3ms vs 151ms" | "The 50x latency gap is irrelevant — you can't ship a mode that returns garbage for half your queries to save 148ms." | Juniors are impressed by speed. Architects dismiss irrelevant metrics. |
| "The expensive model costs 6.5x more" | "text-embedding-3-large adds zero value at this corpus scale. Recommend upgrading only when corpus exceeds 1000 semantically similar docs." | Juniors report numbers. Architects make recommendations with conditions for when they change. |
| "We tested 3 search modes" | "We proved that skipping embeddings saves $0.02/1M tok but breaks 50% of real queries. That 'savings' makes the system unusable." | Juniors count what was tested. Architects quantify the cost of the wrong decision. |
| "RBAC works" | "RBAC is zero-trust at DB level — docs are filtered before retrieval, not after. The LLM never sees unauthorized content." | Juniors confirm functionality. Architects explain the security model. |
| "Model X is more accurate" | "Model X finds 0 additional results at 6.5x cost. Recommend only when semantic overlap in corpus causes retrieval ambiguity (>1000 similar docs)." | Juniors pick a winner. Architects define the decision boundary. |

### Rules for Every Phase

1. **Every conclusion must answer "so what?"** Not "BM25 scores 8/12" but "BM25 fails 50% of natural-language queries — for a company with 200 daily searches, that's 100 unanswered questions per day."

2. **Every recommendation needs a "when this changes" condition.** Not "use hybrid" but "use hybrid; switch to dense-only when your corpus has no alphanumeric codes and BM25 indexing becomes a maintenance burden."

3. **Kill irrelevant metrics.** If a metric doesn't change the decision, it's noise. BM25's speed advantage is noise when it fails half the queries. Large model's dimensions are noise when it finds 0 more results. Don't highlight metrics that distract from the story.

4. **Frame the REAL decision, not the obvious one.** The question was never "BM25 or Dense?" — it was "Dense alone or Dense+BM25?" Reframe every choice to show you understood what the actual decision was.

5. **Quantify the cost of the wrong choice.** Not "BM25 misses synonyms" but "choosing BM25 alone means 50% of queries return zero results. That's a support ticket or a wrong decision for every missed query."

6. **Security is a model, not a checkbox.** Not "RBAC works" but "zero-trust at DB level — unauthorized docs never reach the LLM, they're excluded at query time, not filtered after retrieval."

7. **Tests must break things, not just confirm things.** Design queries that FAIL. Test users who SHOULDN'T have access. Feed inputs that SHOULD be rejected. The tests that prove architect thinking are the ones that prove what the system REFUSES to do.

8. **Always run `/phase-review` before marking a phase complete.** It catches junior framing. Fix framing BEFORE writing content — the tracker feeds the content agents.

### The Content Chain

Tracker conclusions → `/phase-review` catches junior framing → fixed tracker → content agents read tracker → LinkedIn/Medium posts. If the tracker says "BM25 is viable for small corpora," the LinkedIn post will say it too — and every CTO reading it will think "this person doesn't understand enterprise search." Fix it at the source.

## Quick Reference

```bash
make up           # Start infrastructure (qdrant, postgres, redis, langfuse)
make up-full      # Start everything including Kafka + simulator
make test         # Run all tests: uv run pytest tests/ -v
make lint         # Lint: ruff check + format
make api-dev      # FastAPI dev server (port 8080)
make sim-dev      # Rust simulator (port 8081)
make web-dev      # Next.js dashboard (port 3000)
```

## TDD-First Development (MANDATORY)

Every feature follows Red-Green-Refactor. No exceptions.

1. **RED**: Write failing test first. Run it. Confirm it fails.
2. **GREEN**: Write minimum code to make it pass. Nothing more.
3. **REFACTOR**: Clean up while tests stay green.

```
# The loop
uv run pytest tests/unit/test_{module}.py -v    # RED: should fail
# ... write implementation ...
uv run pytest tests/unit/test_{module}.py -v    # GREEN: should pass
# ... refactor ...
uv run pytest tests/ -v                          # ALL: nothing broken
```

### Test Structure

```
tests/
├── unit/           # Fast, no external deps, mocked
├── integration/    # Needs Docker services (postgres, qdrant, redis)
├── e2e/            # Full workflow tests (API → agents → DB)
├── red-team/       # Security & adversarial tests
└── evaluation/     # LLM quality evals (precision, recall, cost)
```

### Test Naming

```python
def test_{what}_{condition}_{expected}():
    """Example: test_rbac_filter_user_without_clearance_returns_empty"""
```

### Fixtures (conftest.py)

- `tests/conftest.py` — shared fixtures (settings, httpx client)
- `tests/integration/conftest.py` — Docker service fixtures (postgres, qdrant, redis connections)
- `tests/e2e/conftest.py` — full app fixtures (FastAPI TestClient, seeded data)

## Phase-by-Phase Workflow

Use `/next-phase` to run the full pipeline. It handles all steps with 3 human checkpoints:

1. **Analyze** → spawn `phase-analyzer` agent → saves `docs/phases/analysis/phase-{N}-analysis.md`
2. **Propose approaches** → saves `docs/phases/analysis/phase-{N}-approaches.md` → **HUMAN: pick approach**
3. **Build** → spawn `tdd-phase-builder` (reads analysis + selected approach)
4. **Test** → spawn `e2e-tester` + run tests
5. **Review** → spawn `phase-reviewer` agent → saves `docs/phases/reviews/phase-{N}-review.md`
6. **Gate check** → PROCEED/REFRAME/DEEPEN BENCHMARKS/FIX → **HUMAN: confirm gate**
7. **Content** → spawn `write-phase-post` (reads analysis + review) → **HUMAN: approve content**
8. **Update** → PROGRESS.md + tracker status

Pipeline is resumable — each step checks if its output file exists and skips if already done.

## Slash Commands

| Command | When |
|---------|------|
| `/next-phase` | Full pipeline: analyze → approach → build → test → review → gate → content (3 human checkpoints, resumable) |
| `/phase-analysis {N}` | Deep 4-perspective analysis (business, cascades, CTO, safety) — saves to `docs/phases/analysis/` |
| `/phase-review {N}` | Architect-level framing audit — saves to `docs/phases/reviews/` |
| `/run-tests` | Run tests, report results, update trackers |
| `/write-phase-post {N}` | Generate LinkedIn + Medium content (reads analysis + review for grounding) |

## Project Structure

```
apps/api/src/
├── core/                    # Domain-agnostic infrastructure
│   ├── api/v1/              # Core endpoints (health, search, ingest, analytics)
│   ├── config/              # Pydantic settings
│   ├── domain/              # Core models (document, telemetry)
│   ├── graphs/              # Core graph patterns (clearance_filter)
│   ├── infrastructure/      # External service clients (llm, postgres, qdrant)
│   ├── rag/                 # RAG pipeline (retrieval, embeddings, chunking, reranking)
│   ├── security/            # RBAC framework
│   └── telemetry/           # LLMOps (Langfuse, cost, drift, quality, judge config)
├── domains/
│   └── logicore/            # LogiCore-specific code
│       ├── agents/          # Brain reader, auditor comparator
│       ├── api/             # Audit endpoints
│       ├── graphs/          # Audit workflow (state, graph, compliance subgraph)
│       ├── models/          # Audit domain models (Invoice, ContractRate, etc.)
│       └── tools/           # SQL query, report generator
└── main.py                  # Wires core + domain routers
```

## Code Placement Guide (MANDATORY for all phases)

Every new file must go in either `core/` or `domains/logicore/`. Never create files directly under `apps/api/src/` (except `main.py`).

### Goes in `core/` (domain-agnostic)

| Category | Examples | Rule |
|----------|----------|------|
| Infrastructure clients | Qdrant, Postgres, Redis, Kafka, LLM providers | Generic service wrappers, no business logic |
| RAG pipeline | Retrieval, embeddings, chunking, reranking, sparse | Configurable, works for any corpus |
| Security framework | RBAC filter builder, input sanitizer, guardrails, SQL sandbox | Generic security patterns |
| Telemetry/LLMOps | Langfuse, cost tracker, drift detector, quality pipeline | Generic observability |
| Config | Pydantic settings | Environment-driven |
| Core models | Document, Chunk, UserContext, SearchResult, TraceRecord, EvalScore | Shared across all domains |
| Core API | Health, search, ingest, analytics, security endpoints | Domain-agnostic endpoints |
| Core patterns | ClearanceFilter, circuit breaker, MCP auth | Reusable architectural patterns |

### Goes in `domains/logicore/` (LogiCore-specific)

| Category | Examples | Rule |
|----------|----------|------|
| Agents | Reader (contract rates), Auditor (invoice comparison), Guardian (fleet) | Business logic with domain prompts |
| Domain models | Invoice, ContractRate, Discrepancy, FleetAlert, ComplianceReport | LogiCore-specific Pydantic models |
| Graphs | Audit workflow, fleet response, compliance subgraph | Domain-specific LangGraph state machines |
| Tools | SQL query (invoice tables), report generator | Domain-specific tool implementations |
| Domain API | Audit, fleet, compliance endpoints | Business-specific routes |
| MCP servers | Invoice SQL, fleet status, compliance tools | Domain-specific MCP wrappers |
| Test data | Polish corpus, ground truth queries, mock invoices | LogiCore benchmark data |

### The test: "Could someone swap `domains/logicore/` for `domains/healthcare/` and have core work unchanged?"

If yes → `core/`. If no → `domains/logicore/`.

### Dependency direction

```
domains/logicore/ ──imports──► core/
core/ ──NEVER imports──► domains/
main.py ──wires──► both
```

## Pipeline Persistence

Artifacts saved by the pipeline — each step saves to a file so downstream agents can read it.

| Artifact | Path | Created By | Read By |
|----------|------|------------|---------|
| Phase analysis | `docs/phases/analysis/phase-{N}-analysis.md` | `phase-analyzer` agent | tdd-phase-builder, write-phase-post, content agents |
| Approaches | `docs/phases/analysis/phase-{N}-approaches.md` | `/next-phase` step 3 | tdd-phase-builder |
| Architect review | `docs/phases/reviews/phase-{N}-review.md` | `phase-reviewer` agent | `/next-phase` gate check, write-phase-post, content-reviewer |
| LinkedIn draft | `docs/content/linkedin/phase-{N}-post.md` | write-phase-post | content-reviewer |
| Medium draft | `docs/content/medium/phase-{N}-{slug}.md` | write-phase-post | content-reviewer |

## Key Docs

| Doc | What |
|-----|------|
| `docs/PROGRESS.md` | Overall status, dependency graph, current sprint |
| `docs/phases/phase-{N}-*.md` | Phase specs (business problem, architecture, implementation guide) |
| `docs/phases/trackers/phase-{N}-tracker.md` | Per-phase tracking (tasks, benchmarks, decisions, content status) |
| `docs/content/CONTENT-STRATEGY.md` | LinkedIn/Medium content strategy, framing rules |
| `docs/adr/` | Architecture Decision Records (LangGraph, Qdrant, Langfuse) |
| `docs/architect-notes/` | Migration strategy, vendor lock-in analysis |
| `docs/architecture.md` | Service map, data flow, ports |

## Claude Code Agents

| Agent | When |
|-------|------|
| `phase-analyzer` | Deep 4-perspective analysis → saves to `docs/phases/analysis/phase-{N}-analysis.md` |
| `phase-reviewer` | Architect framing audit → saves to `docs/phases/reviews/phase-{N}-review.md` |
| `tdd-phase-builder` | TDD implementation (reads analysis + selected approach) |
| `linkedin-architect` | Write LinkedIn post for a phase |
| `medium-architect` | Write Medium deep-dive for a phase |
| `content-reviewer` | Review any draft before publishing (reads review for framing check) |
| `e2e-tester` | Comprehensive E2E verification |

## Security Rules

- **SQL**: Parameterized queries only (`asyncpg` with `$1` params, SQLAlchemy with `:param`)
- **LLM prompts**: Sanitize all external content before including in prompts
- **Secrets**: Environment variables only, never hardcode, `.env` in `.gitignore`
- **Qdrant**: Read-only roles for agents that shouldn't write
- **PostgreSQL**: `logicore_reader` role for SQL agents (SELECT only)

## Docker Services (ports)

| Service | Port | Purpose |
|---------|------|---------|
| Qdrant | 6333 | Vector DB (hybrid search) |
| PostgreSQL | 5432 | State, checkpoints, audit logs |
| Redis | 6379 | Semantic cache, agent memory |
| Langfuse | 3001 | LLM observability |
| API | 8080 | FastAPI backend |
| Web | 3000 | Next.js dashboard |
| Simulator | 8081 | Rust fleet simulator |
| Kafka | 9092 | Event streaming (profile: kafka) |
| Kafka UI | 8082 | Kafka management (profile: kafka) |

## Conventions

- Python 3.12, type hints everywhere
- Pydantic v2 for all models (domain + settings)
- `async/await` throughout (asyncpg, httpx, FastAPI)
- Ruff for linting + formatting
- pytest with async support (`pytest-asyncio`)
- LangGraph for agent orchestration (not CrewAI)
- All costs in EUR, all timestamps in UTC
