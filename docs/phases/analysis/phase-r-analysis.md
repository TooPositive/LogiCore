---
phase: R
date: "2026-03-08"
type: structural-refactor
---

# Phase R: Core Extraction — Codebase Analysis

## Goal

Split `apps/api/src/` into domain-agnostic `core/` and domain-specific `domains/logicore/` so the retrieval pipeline, agent orchestration, LLMOps, security, and telemetry can be reused for any domain by swapping config.

## Current State

- 867 tests across unit/integration/e2e/evaluation/red-team
- 5 completed phases of mixed core + domain code
- Import root: `apps.api.src.*`

## File Classification

### Pure CORE (move unchanged)

| Directory | Files | Rationale |
|-----------|-------|-----------|
| `rag/` | retriever, embeddings, reranker, chunking, sparse, query_transform, ingestion | All parameterized, no domain references |
| `telemetry/` | langfuse_handler, cost_tracker, quality_pipeline, drift_detector, model_registry, judge_config, prompt_optimizer | Generic LLMOps infrastructure |
| `infrastructure/llm/` | cache, router | RBAC-aware but parameterized |
| `infrastructure/qdrant/` | client | Generic Qdrant wrapper |
| `infrastructure/postgres/` | checkpointer | LangGraph state persistence |
| `config/` | settings | Pydantic BaseSettings |
| `domain/document.py` | Document, Chunk, UserContext, SearchRequest, SearchResult | Generic retrieval models |
| `domain/telemetry.py` | TraceRecord, CostSummary, EvalScore, etc. | Generic telemetry models |
| `api/v1/health.py` | Health endpoint | Generic |
| `api/v1/search.py` | Search endpoint | Wires retriever + RBAC |
| `api/v1/ingest.py` | Ingestion endpoint | Wires ingestion pipeline |
| `api/v1/analytics.py` | Analytics endpoint | Wires cost/quality |

### Pure DOMAIN (move to domains/logicore/)

| File | Rationale |
|------|-----------|
| `agents/brain/reader.py` | Contract rate extraction with logistics prompts |
| `agents/auditor/comparator.py` | Invoice discrepancy comparison with cargo types |
| `tools/report_generator.py` | Audit report with logistics terminology |
| `data/benchmark-corpus/` | Polish logistics documents |
| `data/golden-set/` | LogiCore-specific Q&A pairs |
| `tests/evaluation/corpus.py` | Polish benchmark corpus |
| `tests/evaluation/ground_truth.py` | Polish ground truth queries |

### MIXED (needs splitting)

| File | Core Part | Domain Part |
|------|-----------|-------------|
| `security/rbac.py` | `build_qdrant_filter()`, `RBACFilter` class | `DEFAULT_USER_STORE` with hardcoded LogiCore users |
| `domain/audit.py` | `DiscrepancyBand`, generic Invoice/Discrepancy models | cargo_type fields, LogiCore thresholds (1/5/15%) |
| `tools/sql_query.py` | Parameterized query pattern | Hardcoded invoice table/column names |
| `graphs/audit_graph.py` | StateGraph topology, routing | Node implementations calling domain agents |
| `graphs/clearance_filter.py` | Filter logic | Clearance level semantics |
| `graphs/compliance_subgraph.py` | Subgraph pattern | Compliance-specific nodes |
| `api/v1/audit.py` | Endpoint wiring | Imports domain-specific graph |

### Data Files

| Path | Classification |
|------|---------------|
| `data/benchmark-corpus/*.json` | DOMAIN — Polish logistics |
| `data/golden-set/*.json` | DOMAIN — LogiCore Q&A |
| `scripts/benchmark_*.py` | DOMAIN — LogiCore benchmarks |
| `scripts/generate_corpus*.py` | DOMAIN — Polish corpus generators |

## Risk Assessment

1. **Import path breakage**: Every `from apps.api.src.X` import must be updated. ~200+ import statements across code and tests.
2. **Circular dependencies**: core/ must NOT import domains/. domains/ depends on core/. Must enforce this direction.
3. **Test fixtures**: Many tests use LogiCore-specific test data (Polish users, invoices). The test DATA is domain-specific even when testing core logic.
4. **conftest.py**: Shared fixtures create `UserContext` with LogiCore users — these become domain test fixtures.

## Key Design Questions

1. **Where does core/ live?** Options: `apps/api/src/core/` (inside existing), `core/` (top-level), `apps/core/` (parallel to api)
2. **Where does domains/logicore/ live?** Options: `apps/api/src/domains/logicore/`, `domains/logicore/`, `apps/domains/logicore/`
3. **How do tests map?** Mirror structure? Flat? Keep in tests/ with subdirs?
4. **How does domain registration work?** Config file? Plugin pattern? Simple import?
