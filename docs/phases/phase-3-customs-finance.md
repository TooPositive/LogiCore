# Phase 3: "The Customs & Finance Engine" — Multi-Agent Orchestration

## Business Problem

A truck is stuck at the Swiss border. The driver needs customs clearance. An invoice says one rate, the contract says another. Today, a human clerk spends 3 hours cross-referencing documents, querying the ERP, and drafting a discrepancy report. By then, the cargo is late and the client is furious.

**CTO pain**: "We need AI that doesn't just read documents — it executes multi-step workflows. But autonomous AI making financial decisions without human approval is a non-starter."

## Real-World Scenario: LogiCore Transport

**Feature: Automated Invoice Audit Workflow**

Invoice INV-2024-0847 arrives. It bills PharmaCorp at €0.52/kg for 8,400 kg of pharmaceutical cargo. But contract CTR-2024-001 specifies €0.45/kg. That's a €588 overcharge.

Today, a human clerk spends 3 hours cross-referencing the contract PDF, the invoice database, and the ERP system. With LogiCore's multi-agent workflow:

1. **Reader Agent** searches the contract database via RAG → extracts the negotiated rate: €0.45/kg, minimum volume 5,000 kg, clearance level 3 (confidential)
2. **SQL Agent** queries the invoice DB (read-only!) → actual billing: €0.52/kg × 8,400 kg = €4,368 billed, vs €3,780 expected
3. **Auditor Agent** compares → flags €588 discrepancy (15.6% overcharge)
4. **HITL Gateway** → workflow STOPS. Dashboard shows "Awaiting Approval" with the discrepancy report. CFO Martin Lang reviews, adds a note: "Verified. Vendor overcharged. Dispute and request credit note."
5. **Report Generator** → produces final audit report, stored in PostgreSQL with full Langfuse trace

**The crash-recovery moment**: During the demo, kill the API server while the workflow is at step 4 ("awaiting approval"). Restart it. The workflow resumes exactly at step 4 — state persisted in PostgreSQL via LangGraph's checkpointer. Nothing lost.

**The SQL safety moment**: Try injecting `"; DROP TABLE invoices; --"` through the SQL agent. It fails — the agent uses a read-only database role that can only SELECT. Even compromised AI can't delete data.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Multi-agent orchestration (LangGraph) | 3 specialized AIs work as a team: one reads contracts, one queries invoices, one compares | 3-hour manual audit → 8 seconds automated |
| HITL Gateway | Workflow pauses with "Approve / Reject" button | AI finds problems, humans make decisions. Compliance-safe. |
| State persistence (PostgreSQL checkpointer) | Workflow survives server crashes | No lost work, no repeated steps, resumable 24/7 |
| Read-only SQL role | SQL Agent can query but never modify data | Even if AI is compromised, your data is safe |
| LangGraph state machine | Deterministic workflow: A → B → C → approval → report | Auditable, predictable, no "AI went rogue" surprises |

## Architecture

```
Trigger (API / scheduled / Kafka event)
  → LangGraph Supervisor
    → State: { invoice_id, status, extracted_rates, actual_billing, discrepancies }
    ├── Node: Reader Agent (GPT-5 mini — summarize contract clauses)
    │     → Phase 1 RAG: extract negotiated rates from contract DB
    │     → Updates state.extracted_rates
    ├── Node: SQL Agent (GPT-5 nano — classify & route SQL queries)
    │     → Read-only SQL against invoice DB
    │     → Updates state.actual_billing
    ├── Node: Auditor Agent (GPT-5.2 — complex comparison reasoning)
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

## AI Decision Tree: Invoice Audit Workflow

How does the system decide what to do with a discrepancy? Not every mismatch needs a CFO alert. The decision tree routes by discrepancy magnitude, with cost-per-decision at each branch.

```
Invoice Arrives
│
├── Reader Agent extracts contract rate (GPT-5 mini, ~€0.003)
├── SQL Agent queries invoice DB (GPT-5 nano, ~€0.00004)
├── Auditor Agent calculates discrepancy % (GPT-5.2, ~€0.02)
│
▼
Discrepancy Classification
│
├── < 1% discrepancy (rounding, FX fluctuation)
│   → AUTO-APPROVE
│   │  Model: GPT-5 nano classifies as "within tolerance"
│   │  Cost: €0.00002 (classification only)
│   │  Action: Log to audit trail, no human involved
│   │  Latency: ~2s total pipeline
│   │  Example: Invoice says €3,784, contract says €3,780 → €4 diff (0.1%)
│
├── 1-5% discrepancy (possible data entry error)
│   → AI INVESTIGATION
│   │  Model: GPT-5 mini generates investigation report
│   │  Cost: €0.003 (summarize findings + recommend action)
│   │  Action: Flag for finance team review (next business day)
│   │  Latency: ~5s total pipeline
│   │  Example: Invoice says €0.47/kg, contract says €0.45/kg → 4.4% over
│
├── 5-15% discrepancy (significant overcharge or error)
│   → ESCALATE TO HITL with AI-prepared brief
│   │  Model: GPT-5.2 prepares detailed comparison brief
│   │  Cost: €0.02 (multi-hop reasoning across contract + invoice + history)
│   │  Action: Workflow BLOCKS. Dashboard alert. Human must approve/reject.
│   │  Latency: ~8s pipeline + human review time
│   │  Example: Invoice says €0.52/kg, contract says €0.45/kg → 15.6% over (€588)
│
└── > 15% discrepancy (potential fraud or major contract violation)
    → CFO ALERT + FULL AUDIT
    │  Model: GPT-5.2 + multi-agent deep investigation
    │  Cost: €0.08 (auditor re-checks all line items, cross-references history)
    │  Action: Immediate CFO notification. Full audit trail. Vendor flagged.
    │  Latency: ~15s pipeline + immediate human escalation
    │  Example: Invoice says €0.85/kg, contract says €0.45/kg → 88.9% over (€3,360)
```

### Cost-Per-Decision Summary

| Discrepancy Band | Model(s) Used | Cost/Decision | Volume (est.) | Monthly Cost |
|---|---|---|---|---|
| < 1% (auto-approve) | GPT-5 nano | €0.00002 | ~600/mo (60%) | €0.012 |
| 1-5% (AI investigate) | GPT-5 mini | €0.003 | ~250/mo (25%) | €0.75 |
| 5-15% (HITL escalation) | GPT-5.2 | €0.02 | ~120/mo (12%) | €2.40 |
| > 15% (CFO alert) | GPT-5.2 + multi-agent | €0.08 | ~30/mo (3%) | €2.40 |
| **Total** | | | **1,000 invoices/mo** | **~€5.56/mo** |

**Key insight**: 60% of invoices auto-resolve for €0.012/month total. The expensive models only fire on genuinely complex cases. A flat "use GPT-5.2 for everything" approach would cost €20/month for the same 1,000 invoices — 3.6x more with no quality benefit on the simple cases.

**Air-gapped fallback**: For clients requiring on-premise processing (Swiss regulations), replace GPT-5 nano/mini with Llama 4 Scout or Qwen 3 running on local Ollama. Classification and summarization quality is comparable. Complex reasoning (5-15% band) degrades ~10-15% — acceptable with HITL as backstop.

## Agentic Architecture: Dynamic Delegation

Most "multi-agent" demos are fixed pipelines — A → B → C. That's an orchestrated workflow, not agentic architecture. The harder pattern: **an agent discovers it needs help mid-execution and spawns a specialist**.

### The Problem

The Auditor Agent finds a discrepancy on INV-2024-0847. While investigating, it discovers the contract was amended 3 months ago with a temporary surcharge clause — but the amendment is in German, in a separate legal document. The Auditor Agent doesn't have access to legal docs (clearance level 3, it operates at level 2). It can't just ignore the clause.

### Dynamic Delegation Pattern

```
Auditor Agent (running, hit an unknown clause)
  └─ Spawns: Compliance Check sub-agent
       ├─ Elevated clearance (temporary, scoped to this run)
       ├─ RAG search: "CTR-2024-001 amendments surcharge" (clearance 3)
       ├─ Result: "Amendment dated 2024-09-15: temporary +€0.07/kg surcharge for Q4"
       └─ Returns finding to Auditor Agent
Auditor Agent (resumes with new context)
  └─ Recalculates: €0.52/kg - (€0.45 + €0.07) = €0.00 discrepancy
  └─ Verdict: "No discrepancy. Contract amendment accounts for rate difference."
```

### LangGraph Implementation

```python
# Dynamic subgraph injection — auditor conditionally spawns compliance agent
def auditor_agent(state: AuditState) -> AuditState:
    discrepancies = compare_rates(state)

    if discrepancies and needs_legal_context(discrepancies):
        # Spawn compliance sub-agent dynamically
        compliance_result = await compliance_subgraph.ainvoke({
            "contract_id": state["invoice"]["contract_id"],
            "query": f"amendments affecting rate for {state['invoice']['cargo_type']}",
            "elevated_clearance": 3,  # temporary, scoped to this run
        })
        # Re-evaluate with new context
        discrepancies = compare_rates_with_amendments(state, compliance_result)

    state["discrepancies"] = discrepancies
    return state
```

**Key decisions**:
- Sub-agent gets **scoped, temporary** elevated clearance — not permanent. Expires when the parent run completes.
- The delegation is **conditional** — 90% of audits never need it. Don't pay the cost when you don't need the capability.
- Parent agent **resumes with context** — the sub-agent's finding is injected into the parent's state, not returned as a separate workflow.
- Full trace in Langfuse — the sub-agent call appears as a child span under the auditor node.

**When NOT to delegate dynamically**:
- If you know upfront which agents are needed, use a fixed graph. Dynamic delegation adds ~500ms and complexity.
- If the delegation would require clearance the system can't grant (e.g., financial write access), fail explicitly rather than escalating.

### Crash-Safe State Persistence

The PostgreSQL checkpointer isn't just "nice to have" — it's the difference between a demo and production.

**What's persisted**:
- Full `AuditState` after every node execution
- Sub-agent state (compliance check) as a nested checkpoint
- HITL approval status (survives indefinite wait times)
- Dynamic delegation chain (parent → child relationship)

**Recovery scenarios**:
| Failure | What Happens | Recovery |
|---|---|---|
| Server crash during Reader Agent | Checkpoint at graph entry exists | Restart: re-runs Reader from scratch (idempotent) |
| Server crash during SQL Agent | Checkpoint after Reader exists | Restart: skips Reader, re-runs SQL Agent |
| Server crash during HITL wait | Checkpoint at HITL gate exists | Restart: immediately re-exposes approval endpoint. No re-processing. |
| Server crash during dynamic sub-agent | Parent checkpoint + sub-agent checkpoint both exist | Restart: resumes sub-agent from its last checkpoint, then returns to parent |
| Database connection lost mid-checkpoint | Transaction rolled back | Restart: re-runs current node (safe because nodes are idempotent) |

**The architect insight**: every agent node must be **idempotent**. If the Reader Agent runs twice on the same invoice, it returns the same result. This is what makes crash recovery possible without data corruption.

### Success Criteria
- [ ] `POST /api/v1/audit/start` kicks off multi-agent workflow
- [ ] Reader extracts rates from RAG, SQL agent queries invoice DB
- [ ] Auditor identifies discrepancy between contract rate ($0.45/kg) and invoice ($0.52/kg)
- [ ] Workflow BLOCKS at HITL gateway — status shows "awaiting_approval"
- [ ] `POST /approve` resumes workflow, generates final report
- [ ] SQL agent cannot execute write queries (tested with injection attempt)
- [ ] Full workflow visible in Langfuse with per-agent traces
- [ ] PostgreSQL checkpointer survives API restart (state persisted)

## Cost of Getting It Wrong

The multi-agent workflow costs EUR 5.56/month. The errors cost 7,350x more.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **False positive (flags valid invoice)** | System flags EUR 588 discrepancy but contract amendment accounts for the surcharge. Vendor receives unwarranted dispute. | EUR 200 (review time) + vendor relationship damage | 30/month at 3% false positive rate |
| **False negative (misses overcharge)** | Auto-approves 4.2% overcharge as "within tolerance" because wrong contract version retrieved. | EUR 136/invoice unrecovered | 25/month at 2.5% rate = EUR 40,800/year |
| **Alert fatigue** | Too many false positives → CFO starts ignoring alerts → real fraud case ignored | EUR 3,360+ (one missed major fraud) | Inevitable at >5% false positive rate |
| **HITL timeout** | CFO on vacation. Workflow blocks for 5 days. Vendor dispute window closes. | EUR 588+ (lost dispute opportunity) | 1-2/quarter |
| **Delegation clearance leak** | Compliance sub-agent returns clearance-3 data into clearance-2 parent state. Report shown to clearance-2 user. | EUR 25,000-250,000 (data leak via legitimate workflow) | Silent until discovered |

**The CTO line**: "We process 12,000 invoices/year. A 2.5% false negative rate means EUR 40,800 walking out the door annually — silently, automatically, with nobody noticing."

### Degraded Mode Governance

When the system runs in degraded mode (fallback LLM, re-ranker down, or circuit breaker open):

| Normal Mode | Degraded Mode | Why |
|---|---|---|
| <1% discrepancy → auto-approve | <1% discrepancy → **flag for review** | Can't trust rate extraction at degraded quality |
| Reader uses GPT-5.2 | Reader uses Llama 4 Scout (88% accuracy) | 12% quality gap on complex contract analysis |
| Re-ranker active | Re-ranker down | 38% wrong retrieval rate → can't trust any rate |

**Rule**: When ANY component in the audit chain is degraded, disable the auto-approve band entirely. All discrepancies require HITL review. False negatives in degraded mode are the most expensive errors in the system.

## Cross-Phase Dependencies (Failure Cascade)

Phase 3 is only as accurate as the data it consumes. The audit workflow depends on:

| Dependency | Phase | What Fails | Business Impact |
|---|---|---|---|
| Contract retrieval | Phase 1+2 | Wrong clause → wrong rate extraction | EUR 136-588 per invoice |
| Re-ranking quality | Phase 2 | Degraded re-ranker → 38% wrong results | System-wide financial unreliability |
| Semantic cache | Phase 4 | Stale cached rate → wrong comparison | False dispute with vendor |
| Cache RBAC | Phase 4 | Cache serves cross-clearance answer | Data leak |
| Model routing | Phase 7 | Complex query → nano model | Incomplete rate extraction |
| Audit logging | Phase 8 | Logger crash → gap in audit trail | EU AI Act violation |

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
