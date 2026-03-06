# Phase 3: "The Customs & Finance Engine" — Multi-Agent Orchestration

## Business Problem

A truck is stuck at the Swiss border. The driver needs customs clearance. An invoice says one rate, the contract says another. Today, a human clerk spends 3 hours cross-referencing documents, querying the ERP, and drafting a discrepancy report. By then, the cargo is late and the client is furious.

**CTO pain**: "We need AI that doesn't just read documents — it executes multi-step workflows. But autonomous AI making financial decisions without human approval is a non-starter."

## Architecture

```
Trigger (API / scheduled / Kafka event)
  → LangGraph Supervisor
    → State: { invoice_id, status, extracted_rates, actual_billing, discrepancies }
    ├── Node: Reader Agent
    │     → Phase 1 RAG: extract negotiated rates from contract DB
    │     → Updates state.extracted_rates
    ├── Node: SQL Agent
    │     → Read-only SQL against invoice DB
    │     → Updates state.actual_billing
    ├── Node: Auditor Agent
    │     → Compares rates, identifies discrepancies
    │     → Updates state.discrepancies
    ├── Node: HITL Gateway ← BLOCKS HERE
    │     → Exposes approval endpoint
    │     → Waits for human "Approve" / "Reject"
    └── Node: Report Generator
          → Drafts final audit report
          → Stores to PostgreSQL + Langfuse trace
```

**Key design decisions**:
- LangGraph state machine (not CrewAI role-play) — deterministic, auditable routing
- HITL gateway is a hard interrupt, not a soft prompt — state persists in PostgreSQL until human acts
- SQL Agent has READ-ONLY database role — cannot DROP, UPDATE, or DELETE
- Each agent is a single LangGraph node with explicit input/output schema

## Implementation Guide

### Prerequisites
- Phase 1 complete (RAG pipeline operational)
- PostgreSQL running with `logicore` database
- Mock invoice data seeded

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/graphs/__init__.py` | Package init |
| `apps/api/src/graphs/audit_graph.py` | LangGraph graph definition (nodes, edges, state) |
| `apps/api/src/graphs/state.py` | TypedDict state schema for audit workflow |
| `apps/api/src/agents/brain/reader.py` | Reader agent — RAG contract extraction |
| `apps/api/src/agents/auditor/comparator.py` | Auditor agent — rate comparison logic |
| `apps/api/src/tools/sql_query.py` | Safe read-only SQL execution tool |
| `apps/api/src/tools/report_generator.py` | Audit report formatting |
| `apps/api/src/api/v1/audit.py` | POST /api/v1/audit/start, GET /status, POST /approve |
| `apps/api/src/infrastructure/postgres/checkpointer.py` | LangGraph PostgreSQL checkpointer setup |
| `apps/api/src/domain/audit.py` | Audit, Invoice, DiscrepancyReport models |
| `data/mock-invoices/` | 10 mock invoices (some with rate discrepancies) |
| `scripts/seed_invoices.py` | Invoice seeding script |
| `tests/unit/test_audit_graph.py` | Graph routing tests |
| `tests/integration/test_hitl_flow.py` | Full HITL approval flow |

### Technical Spec

**API Endpoints**:

```
POST /api/v1/audit/start
  Request: { "invoice_id": str }
  Response: { "run_id": str, "status": "processing" }

GET /api/v1/audit/{run_id}/status
  Response: { "run_id": str, "status": "awaiting_approval" | "processing" | "completed", "discrepancies": [...] }

POST /api/v1/audit/{run_id}/approve
  Request: { "approved": bool, "reviewer_id": str, "notes": str }
  Response: { "run_id": str, "status": "completed", "report_url": str }
```

**LangGraph State**:
```python
class AuditState(TypedDict):
    invoice_id: str
    run_id: str
    status: Literal["extracting", "querying", "auditing", "awaiting_approval", "approved", "rejected"]
    extracted_rates: list[dict]      # from RAG
    actual_billing: list[dict]       # from SQL
    discrepancies: list[dict]        # auditor output
    approval: dict | None            # HITL response
    report: str | None               # final report
```

**LangGraph Graph**:
```python
graph = StateGraph(AuditState)
graph.add_node("reader", reader_agent)
graph.add_node("sql_agent", sql_query_agent)
graph.add_node("auditor", auditor_agent)
graph.add_node("hitl_gate", hitl_interrupt)  # interrupt_before
graph.add_node("report", report_generator)

graph.add_edge("reader", "sql_agent")
graph.add_edge("sql_agent", "auditor")
graph.add_edge("auditor", "hitl_gate")
graph.add_edge("hitl_gate", "report")
graph.set_entry_point("reader")
```

**SQL Safety**:
```python
# Database role with SELECT-only permissions
CREATE ROLE logicore_reader WITH LOGIN PASSWORD 'readonly';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO logicore_reader;
```

### Success Criteria
- [ ] `POST /api/v1/audit/start` kicks off multi-agent workflow
- [ ] Reader extracts rates from RAG, SQL agent queries invoice DB
- [ ] Auditor identifies discrepancy between contract rate ($0.45/kg) and invoice ($0.52/kg)
- [ ] Workflow BLOCKS at HITL gateway — status shows "awaiting_approval"
- [ ] `POST /approve` resumes workflow, generates final report
- [ ] SQL agent cannot execute write queries (tested with injection attempt)
- [ ] Full workflow visible in Langfuse with per-agent traces
- [ ] PostgreSQL checkpointer survives API restart (state persisted)

## LinkedIn Post Template

### Hook
"Autonomous AI agents are a nightmare for enterprise compliance — unless you build an Orchestration Layer."

### Body
Everyone's building AI agents. Few are building them safely.

I just built a 3-agent financial auditor for logistics:
- Agent A reads contracts (RAG)
- Agent B queries the invoice database (SQL)
- Agent C compares and flags discrepancies

The magic isn't the agents. It's what happens BETWEEN them.

LangGraph state machine with a mandatory Human-in-the-Loop gateway. The AI finds a $50K billing discrepancy? Great. It CANNOT finalize the audit report until a human clicks "Approve."

State persists in PostgreSQL. If the server crashes at 2 AM, the workflow resumes exactly where it stopped when it comes back online.

"But that slows things down!" — Yes. That's the point. You don't want AI making financial decisions without a human in the loop.

### Visual
Architecture diagram: 4-node LangGraph with HITL gateway highlighted. Arrows showing state flow. "BLOCKS HERE" annotation on the approval node.

### CTA
"Building multi-agent workflows? What's your approach to human oversight? Curious to hear what others are doing."

## Key Metrics to Screenshot
- LangGraph execution trace in Langfuse (per-node timing)
- HITL gateway status page showing "awaiting_approval"
- Discrepancy report output comparing contract vs invoice rates
- SQL agent audit log showing only SELECT queries executed
