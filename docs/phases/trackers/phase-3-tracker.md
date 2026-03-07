# Phase 3 Tracker: Customs & Finance — Multi-Agent Orchestration

**Status**: NOT STARTED
**Spec**: `docs/phases/phase-3-customs-finance.md`
**Depends on**: Phase 1

## Implementation Tasks

- [ ] `apps/api/src/graphs/__init__.py`
- [ ] `apps/api/src/graphs/audit_graph.py` — LangGraph graph definition
- [ ] `apps/api/src/graphs/state.py` — TypedDict state schema
- [ ] `apps/api/src/agents/brain/reader.py` — RAG contract extraction
- [ ] `apps/api/src/agents/auditor/comparator.py` — rate comparison logic
- [ ] `apps/api/src/tools/sql_query.py` — safe read-only SQL execution
- [ ] `apps/api/src/tools/report_generator.py` — audit report formatting
- [ ] `apps/api/src/api/v1/audit.py` — POST /start, GET /status, POST /approve
- [ ] `apps/api/src/infrastructure/postgres/checkpointer.py` — LangGraph PostgreSQL checkpointer
- [ ] `apps/api/src/domain/audit.py` — Audit, Invoice, DiscrepancyReport models
- [ ] `data/mock-invoices/` — 10 mock invoices (some with discrepancies)
- [ ] `scripts/seed_invoices.py` — invoice seeding
- [ ] `tests/unit/test_audit_graph.py` — graph routing tests
- [ ] `tests/integration/test_hitl_flow.py` — full HITL approval flow
- [ ] PostgreSQL read-only role setup (`logicore_reader`)

### Agentic: Dynamic Delegation

- [ ] `apps/api/src/graphs/compliance_subgraph.py` — compliance check sub-agent graph
- [ ] `apps/api/src/agents/auditor/comparator.py` — MODIFY: add `needs_legal_context()` + dynamic sub-agent spawn
- [ ] `apps/api/src/graphs/state.py` — MODIFY: add `compliance_findings` field to AuditState
- [ ] Scoped temporary clearance mechanism (elevated clearance per-run, expires on completion)
- [ ] `tests/unit/test_dynamic_delegation.py` — delegation trigger, sub-agent return, state merge
- [ ] `tests/integration/test_delegation_e2e.py` — full flow: auditor → compliance sub-agent → re-evaluation

### Agentic: Crash-Safe State Persistence

- [ ] Verify idempotency of all agent nodes (Reader, SQL, Auditor, Report Generator)
- [ ] `tests/integration/test_crash_recovery.py` — kill at each node, verify resume
- [ ] Sub-agent crash recovery (parent + child checkpoints both persist)
- [ ] HITL indefinite wait recovery (checkpoint at gate survives days-long wait)
- [ ] Transaction rollback safety (DB connection lost mid-checkpoint)

## Success Criteria

- [ ] `POST /api/v1/audit/start` kicks off multi-agent workflow
- [ ] Reader extracts rates from RAG, SQL agent queries invoice DB
- [ ] Auditor identifies discrepancy (€0.45/kg contract vs €0.52/kg invoice)
- [ ] Workflow BLOCKS at HITL gateway — status shows "awaiting_approval"
- [ ] `POST /approve` resumes workflow, generates final report
- [ ] SQL agent cannot execute write queries (injection attempt fails)
- [ ] Full workflow visible in Langfuse with per-agent traces
- [ ] PostgreSQL checkpointer survives API restart
- [ ] Dynamic delegation: auditor spawns compliance sub-agent when unknown clause found
- [ ] Sub-agent returns finding, auditor recalculates with new context
- [ ] Crash at any node → restart resumes from last checkpoint (no re-processing)
- [ ] Sub-agent crash → both parent and child checkpoints survive

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| LangGraph checkpointer | PostgreSQL | | |
| HITL mechanism | interrupt_before | | |
| SQL safety | read-only role | | |
| State schema fields | 8 fields | | |
| Dynamic delegation | conditional sub-agent spawn | | |
| Clearance escalation | scoped, temporary, per-run | | |
| Crash recovery | idempotent nodes + PostgreSQL checkpointer | | |

## Deviations from Spec

## Code Artifacts

| File | Commit | Notes |
|---|---|---|

## Test Results

| Test | Status | Notes |
|---|---|---|

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| Audit workflow total time | | start to report |
| Reader agent latency | | RAG lookup time |
| SQL agent latency | | invoice query time |
| Auditor agent latency | | comparison time |
| HITL wait → approval | | human response time |
| Discrepancy detection accuracy | | true positives vs false |
| Crash recovery time | | kill + restart → resume |
| Langfuse trace cost (per audit) | | total tokens + cost |
| SQL injection attempts blocked | | count |
| Dynamic delegation trigger rate | | % of audits needing sub-agent |
| Sub-agent latency overhead | | ms added by delegation |
| Crash recovery per-node | | time to resume at each node |

## Screenshots Captured

- [ ] LangGraph execution trace in Langfuse
- [ ] HITL gateway status page ("awaiting_approval")
- [ ] Discrepancy report output
- [ ] SQL agent audit log (SELECT only)
- [ ] Crash recovery demo (kill + resume)
- [ ] Dynamic delegation trace in Langfuse (parent → child span)
- [ ] Auditor re-evaluation after sub-agent returns (before/after)

## Problems Encountered

## Open Questions

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
