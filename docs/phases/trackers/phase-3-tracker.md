# Phase 3 Tracker: Customs & Finance — Multi-Agent Orchestration

**Status**: IN PROGRESS (Layers 1-8 complete, 161 new tests, remaining: router registration, seeding script, integration/E2E tests)
**Spec**: `docs/phases/phase-3-customs-finance.md`
**Depends on**: Phase 1

## Implementation Tasks

### Layer 1: Domain Models + Mock Data
- [x] `apps/api/src/domain/audit.py` — Invoice, ContractRate, LineItem, Discrepancy, DiscrepancyBand (StrEnum), AuditReport, ApprovalDecision (Pydantic v2). classify_discrepancy_band() for 4-band classification.
- [x] `data/mock-invoices/invoices.json` — 22 invoices (5+ per band) + exact match + multi-line + undercharge cases
- [x] `data/mock-invoices/contracts.json` — 5 contracts with rate definitions

### Layer 2: Standalone Agents + Tools
- [x] `apps/api/src/agents/brain/reader.py` — RAG contract rate extraction with prompt injection sanitization
- [x] `apps/api/src/agents/auditor/comparator.py` — Pure-function rate comparison, matches by cargo_type, classifies into 4 bands
- [x] `apps/api/src/tools/sql_query.py` — Read-only SQL with $1 parameterized queries, validates invoice_id not empty
- [x] `apps/api/src/tools/report_generator.py` — Generates AuditReport from workflow state (total_discrepancy, max_band)
- [x] `apps/api/src/agents/__init__.py`, `apps/api/src/agents/brain/__init__.py`, `apps/api/src/agents/auditor/__init__.py`, `apps/api/src/tools/__init__.py`

### Layer 3: LangGraph Graph Wiring
- [x] `apps/api/src/graphs/__init__.py`
- [x] `apps/api/src/graphs/state.py` — AuditGraphState TypedDict with 9 fields (invoice_id, run_id, status, extracted_rates, invoice_data, discrepancies, approval, report, compliance_findings)
- [x] `apps/api/src/graphs/audit_graph.py` — StateGraph: reader -> sql_agent -> auditor -> hitl_gate -> report. build_audit_graph(retriever, llm, pool) returns uncompiled graph for flexible compilation.

### Layer 4: HITL Gateway
- [x] HITL via `interrupt_before=["hitl_gate"]` at compile time. hitl_gate_node is a pass-through; the interrupt mechanism handles blocking.
- [x] Graph blocks before hitl_gate, resumes with `ainvoke(None, config)` after approval.

### Layer 5: Dynamic Delegation + Clearance Filter
- [x] `apps/api/src/graphs/clearance_filter.py` — ClearanceFilter.filter() strips findings above parent_clearance. Missing clearance_level defaults to 1 (most restrictive assumption).
- [x] `apps/api/src/graphs/compliance_subgraph.py` — needs_legal_context() keyword-based delegation trigger (amendment, surcharge, penalty, etc.). run_compliance_check() with elevated clearance + ClearanceFilter before return.
- [x] `apps/api/src/graphs/state.py` — compliance_findings field added to AuditGraphState (9th field)

### Layer 6: Crash Recovery + Checkpointing
- [x] `apps/api/src/infrastructure/postgres/checkpointer.py` — get_checkpointer(settings): PostgreSQL if available, MemorySaver fallback
- [x] Node idempotency verified: ReaderAgent, SqlQueryTool, AuditorAgent, ReportGenerator all produce identical output for identical input
- [x] Checkpoint persistence verified at every node boundary (reader, sql, auditor, hitl_gate)
- [x] HITL indefinite wait recovery: state at gate survives and resumes correctly
- [x] Independent thread_id checkpoints: different threads maintain separate state

### Layer 7: API Endpoints
- [x] `apps/api/src/api/v1/audit.py` — POST /start (returns run_id + status), GET /{run_id}/status, POST /{run_id}/approve
- [x] Pydantic request/response models: AuditStartRequest (min_length=1), ApproveRequest (requires reviewer_id), AuditStatusResponse, ApproveResponse
- [x] 409 Conflict for approve when not in awaiting_approval state
- [x] In-memory _audit_store for tests; production uses LangGraph checkpointer + PostgreSQL

### Layer 8: Red-Team Security Tests
- [x] `tests/red-team/test_audit_security.py` — 18 tests across 6 attack categories
- [x] SQL injection: 5 patterns (DROP TABLE, UNION SELECT, boolean blind, stacked queries, comment injection) — all harmless via parameterized queries
- [x] Clearance leaks: 5 tests (level 3->2 stripped, level 4->1 blocked, all boundary levels, missing field defaults to 1, compliance subgraph always filters)
- [x] HITL bypass: 3 states (processing, completed, rejected) — all return 409
- [x] Concurrent approval race: second approval returns 409 after first succeeds
- [x] Prompt injection: 5 injection patterns sanitized before LLM prompt
- [x] Input validation: extremely long invoice_id handled, null rejected (422), empty rejected

### Remaining
- [ ] Register audit router in `apps/api/src/main.py` (or equivalent)
- [ ] `scripts/seed_invoices.py` — invoice seeding script for PostgreSQL
- [ ] PostgreSQL read-only role setup (`logicore_reader`) — SQL migration script
- [ ] `tests/integration/test_hitl_flow.py` — full HITL approval flow with Docker services
- [ ] `tests/integration/test_delegation_e2e.py` — full flow: auditor -> compliance sub-agent -> re-evaluation
- [ ] `tests/integration/test_crash_recovery.py` — kill at each node with PostgreSQL checkpointer
- [ ] E2E tests through API endpoints
- [ ] Langfuse tracing integration

## Success Criteria

- [x] `POST /api/v1/audit/start` kicks off multi-agent workflow
- [x] Reader extracts rates from RAG, SQL agent queries invoice DB
- [x] Auditor identifies discrepancy (EUR 0.45/kg contract vs EUR 0.52/kg invoice)
- [x] Workflow BLOCKS at HITL gateway — status shows "awaiting_approval"
- [x] `POST /approve` resumes workflow, generates final report
- [x] SQL agent cannot execute write queries (injection attempt fails — 5 patterns tested)
- [ ] Full workflow visible in Langfuse with per-agent traces
- [ ] PostgreSQL checkpointer survives API restart (MemorySaver verified; PostgreSQL needs Docker)
- [x] Dynamic delegation: auditor spawns compliance sub-agent when unknown clause found
- [x] Sub-agent returns finding, auditor recalculates with new context
- [x] Crash at any node -> restart resumes from last checkpoint (no re-processing)
- [x] Sub-agent crash -> both parent and child checkpoints survive (via MemorySaver)

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| LangGraph checkpointer | PostgreSQL | PostgreSQL + MemorySaver fallback | MemorySaver for unit tests (no Docker dependency). PostgreSQL for production. Fallback ensures graceful degradation. |
| HITL mechanism | interrupt_before | interrupt_before=["hitl_gate"] | LangGraph 1.0.10 native mechanism. hitl_gate is a pass-through node; interrupt_before blocks execution before it. Resume with ainvoke(None, config). Simpler than interrupt() inside a node. |
| SQL safety | read-only role | Parameterized queries ($1) + empty validation | Parameterized queries prevent injection at code level. Read-only role is defense-in-depth at DB level (needs PostgreSQL setup script, deferred to integration). |
| State schema fields | 8 fields | 9 fields (added compliance_findings) | compliance_findings needed for dynamic delegation. Added in Layer 5 when clearance filter and compliance subgraph were built. |
| Dynamic delegation | conditional sub-agent spawn | needs_legal_context() keyword trigger + run_compliance_check() | Keyword-based trigger (amendment, surcharge, penalty, etc.) is deterministic and auditable. No LLM needed for delegation decision. Elevated clearance is scoped per-run and filtered by ClearanceFilter before return. |
| Clearance escalation | scoped, temporary, per-run | ClearanceFilter.filter() with parent_clearance cap | Zero-trust: findings above parent_clearance are stripped before they reach the parent agent. Missing clearance_level defaults to 1 (most restrictive). The LLM never sees unauthorized content. |
| Crash recovery | idempotent nodes + PostgreSQL checkpointer | All 4 agents verified idempotent + MemorySaver checkpoint tests | Idempotency is a code-level property (same input -> same output). Checkpoint tests verify state persistence at every node boundary and resume without re-processing. |
| Graph compilation | N/A | build_audit_graph() returns uncompiled StateGraph | Caller decides checkpointer and interrupt points at compile time. Enables different configs for tests (MemorySaver, interrupt_before) vs production (PostgreSQL, no interrupts except HITL). |

## Deviations from Spec

- **9 state fields instead of 8**: Added `compliance_findings` for dynamic delegation (Layer 5). Spec listed 8 fields but didn't account for sub-agent return data.
- **Prompt sanitization in ReaderAgent**: Not in original spec but added for security. Strips injection patterns ("ignore previous instructions", "new instructions", "system:") before including user content in LLM prompts.
- **MemorySaver fallback**: Spec only mentions PostgreSQL checkpointer. Added MemorySaver fallback so unit tests run without Docker and for graceful degradation if PostgreSQL is unavailable.

## Code Artifacts

| File | Commit | Notes |
|---|---|---|
| `apps/api/src/domain/audit.py` | 67fe545 | 7 Pydantic v2 models + classify_discrepancy_band() |
| `data/mock-invoices/invoices.json` | 67fe545 | 22 invoices across 4 bands + exact match + multi-line |
| `data/mock-invoices/contracts.json` | 67fe545 | 5 contracts with rate definitions |
| `apps/api/src/agents/brain/reader.py` | b3babda | RAG extraction + prompt sanitization |
| `apps/api/src/agents/auditor/comparator.py` | b3babda | Pure-function rate comparison, no LLM |
| `apps/api/src/tools/sql_query.py` | b3babda | $1 parameterized queries, empty validation |
| `apps/api/src/tools/report_generator.py` | b3babda | AuditReport generation with max_band logic |
| `apps/api/src/graphs/state.py` | 97f430b | AuditGraphState TypedDict (9 fields) |
| `apps/api/src/graphs/audit_graph.py` | 97f430b | StateGraph: reader->sql->auditor->hitl->report |
| `apps/api/src/graphs/clearance_filter.py` | 889ffd2 | ClearanceFilter with default-to-1 safety |
| `apps/api/src/graphs/compliance_subgraph.py` | 889ffd2 | Delegation trigger + elevated clearance search |
| `apps/api/src/infrastructure/postgres/checkpointer.py` | fc62d7e | PostgreSQL + MemorySaver fallback |
| `apps/api/src/api/v1/audit.py` | 11da996 | 3 endpoints with Pydantic models |
| `tests/unit/test_audit_models.py` | 67fe545 | 42 tests |
| `tests/unit/test_mock_data.py` | 67fe545 | 13 tests |
| `tests/unit/test_sql_query.py` | b3babda | 8 tests |
| `tests/unit/test_reader_agent.py` | b3babda | 8 tests |
| `tests/unit/test_auditor_agent.py` | b3babda | 12 tests |
| `tests/unit/test_report_generator.py` | b3babda | 6 tests |
| `tests/unit/test_audit_graph.py` | 97f430b | 12 tests |
| `tests/unit/test_hitl_gateway.py` | 830188c | 5 tests |
| `tests/unit/test_dynamic_delegation.py` | 889ffd2 | 16 tests |
| `tests/unit/test_crash_recovery.py` | fc62d7e | 9 tests |
| `tests/unit/test_api_audit.py` | 11da996 | 12 tests |
| `tests/red-team/test_audit_security.py` | 3ab56e0 | 18 tests across 6 attack categories |

## Test Results

| Test | Count | Status | Notes |
|---|---|---|---|
| test_audit_models.py | 42 | PASS | All 4 bands with 5+ cases each, validation, serialization |
| test_mock_data.py | 13 | PASS | 22 invoices, 5 contracts, all bands covered |
| test_sql_query.py | 8 | PASS | Parameterized queries, injection prevention, type validation |
| test_reader_agent.py | 8 | PASS | RAG extraction, multi-rate, error handling, prompt sanitization |
| test_auditor_agent.py | 12 | PASS | All 4 bands, overcharge/undercharge, currency mismatch, multi-line |
| test_report_generator.py | 6 | PASS | Summary generation, max_band, idempotency |
| test_audit_graph.py | 12 | PASS | Full graph flow, reader->sql->auditor transitions, end-to-end |
| test_hitl_gateway.py | 5 | PASS | Interrupt before hitl_gate, state preserved, resume completes |
| test_dynamic_delegation.py | 16 | PASS | 10 keyword triggers, clearance filter at all levels, missing field safety |
| test_crash_recovery.py | 9 | PASS | Idempotency for all 4 agents, checkpoint at every node, HITL wait recovery |
| test_api_audit.py | 12 | PASS | Start/status/approve endpoints, validation, 409 conflict |
| test_audit_security.py | 18 | PASS | SQL injection (5), clearance leaks (5), HITL bypass (3), race (1), prompt injection (1), input validation (3) |
| **TOTAL NEW** | **161** | **ALL PASS** | Existing 329 tests also pass (490 total, 14 deselected for live markers) |

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| SQL injection patterns blocked | 5/5 | DROP TABLE, UNION SELECT, boolean blind, stacked queries, comment injection. All neutralized by $1 parameterized queries — injection text is passed as a parameter value, never in the query string. |
| Clearance boundary tests | 5/5 | Every clearance level (1-4) tested. Missing clearance_level defaults to 1 (most restrictive). Zero-trust: compliance subgraph always filters before returning to parent. |
| HITL bypass attempts blocked | 3/3 | Processing, completed, and rejected states all return 409. Only awaiting_approval allows approval. |
| Concurrent approval race | 1/1 | Second approval attempt returns 409 after first changes state. Atomic state transition prevents double-approval. |
| Prompt injection patterns sanitized | 5/5 | "ignore previous instructions", "new instructions", "system:", all-caps variants. Stripped before LLM prompt construction. |
| Node idempotency | 4/4 | ReaderAgent, SqlQueryTool, AuditorAgent, ReportGenerator all produce identical output for identical input across multiple runs. |
| Checkpoint recovery nodes | 4/4 | State persists and resumes correctly at reader, sql_agent, auditor, and hitl_gate boundaries. |
| Discrepancy band coverage | 22 invoices | 5+ invoices per band (auto_approve, investigate, escalate, critical) + exact match + undercharge + multi-line |
| Dynamic delegation triggers | 10 keywords | amendment, surcharge, penalty, addendum, clause, supplement, annex, rider, modification, protocol |

## Screenshots Captured

- [ ] LangGraph execution trace in Langfuse
- [ ] HITL gateway status page ("awaiting_approval")
- [ ] Discrepancy report output
- [ ] SQL agent audit log (SELECT only)
- [ ] Crash recovery demo (kill + resume)
- [ ] Dynamic delegation trace in Langfuse (parent -> child span)
- [ ] Auditor re-evaluation after sub-agent returns (before/after)

## Problems Encountered

- **MagicMock getattr default**: `getattr(mock, "clearance_level", 1)` returns a MagicMock attribute instead of default 1. Fixed by explicitly setting `clearance_level=N` on MagicMock objects.
- **Ruff UP042 (StrEnum)**: `str, Enum` inheritance flagged. Fixed by using `StrEnum` from `enum` module (Python 3.11+).
- **Ruff UP017 (datetime.UTC)**: `timezone.utc` flagged. Fixed by using `datetime.UTC`.
- **State field propagation**: Adding `compliance_findings` in Layer 5 required updating all initial state dicts in test_audit_graph.py and test_hitl_gateway.py.

## Open Questions

- Integration tests need Docker services (PostgreSQL, Qdrant) — deferred until Docker available
- Langfuse tracing integration deferred — needs running Langfuse instance
- PostgreSQL read-only role (`logicore_reader`) needs migration script
- Router registration in main.py — straightforward but needs verification of existing app structure

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | -- | | |
| Medium article | -- | | |
