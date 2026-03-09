---
title: "I Built an AI That Finds EUR 40,800 in Overcharges — Then Stops and Waits for a Human"
subtitle: "Why the hardest part of multi-agent AI isn't the agents. It's making them stop."
series: "LogiCore AI System — Phase 3/12"
phase: 3
date: 2026-03-08
status: draft
tags: ["multi-agent", "LangGraph", "HITL", "human-in-the-loop", "AI architecture", "enterprise AI", "crash recovery", "state machine"]
---

# I Built an AI That Finds EUR 40,800 in Overcharges — Then Stops and Waits for a Human

## 1. The Invoice Nobody Checked

Marta works in finance at LogiCore Transport, a Polish logistics company. Every morning she opens a spreadsheet of yesterday's invoices. For each one, she opens the contract PDF in another window, finds the negotiated rate, calculates the expected total, compares it to the billed amount, and writes a note if something's off.

Invoice INV-2024-0847 bills PharmaCorp at EUR 0.52/kg for 8,400 kg of pharmaceutical cargo. The contract says EUR 0.45/kg. Thats a EUR 588 overcharge — 15.6% above the negotiated rate.

Marta catches this one because the number is big enough to look wrong. But what about INV-2024-0912, which bills at EUR 0.46/kg instead of EUR 0.45/kg? That 2.2% difference across 6,200 kg is only EUR 62. Marta's eyes slide right past it. She has 47 more invoices to review before lunch.

At 12,000 invoices per year and a 2.5% miss rate on overcharges, LogiCore loses roughly EUR 40,800 annually. Silently. Automatically. Nobody notices until the annual audit, and by then the vendor dispute window has closed on most of them.

This is Phase 3 of a 12-phase AI system im building for a logistics company. Each phase tackles a real business problem. Phase 1 built the RAG pipeline (document search with access control). Phase 2 proved which retrieval models actually work for Polish logistics documents. Phase 3 asks a different question: what happens when search works but you need the AI to DO something with what it finds?

## 2. Why "Just Add AI Agents" Doesn't Work Here

There's a passage in Donella Meadows' "Thinking in Systems" that stuck with me: the most important thing about a system isn't what each part does, it's what happens at the BOUNDARIES between parts. Where does one subsystem end and another begin? Who controls the handoff?

Most multi-agent AI demos skip this question entirely. Agent A calls Agent B, which calls Agent C, and the result appears on screen. It works beautifully in a Jupyter notebook. It works terribly in production finance.

Three reasons:

The data lives in different systems with different access models. Contract rates live in a vector database (Qdrant), accessed through RAG with RBAC-filtered clearance levels. Invoice billing data lives in PostgreSQL, accessed through parameterized SQL queries. You cant just "give the agent access to everything" — thats how you get an AI with read-write access to your financial database, which is roughly the same as giving a smart intern the root password on their first day.

Financial decisions require human approval. This isnt a preference, its a legal requirement. EU AI Act Article 14 mandates human oversight for high-risk AI decisions. Your insurance wont cover fully autonomous financial AI. Your CFO doesnt want an AI autonomously disputing vendor invoices. The system needs to find the problem and then STOP.

Servers crash. The CFO goes on vacation. Network connections drop at 2 AM. Any system that holds financial state in memory is a system that will eventually lose financial state. Martin Kleppmann makes this point repeatedly in "Designing Data-Intensive Applications": if you care about your data, you persist it. If you really care, you persist it transactionally.

## 3. The Architecture: Three Agents That Know Their Boundaries

The audit workflow is a LangGraph state machine with 5 nodes:

```python
graph = StateGraph(AuditGraphState)

graph.add_node("reader", reader_node)      # RAG: extract contract rate
graph.add_node("sql_agent", sql_agent_node) # SQL: fetch invoice billing
graph.add_node("auditor", auditor_node)     # Compare rates, classify
graph.add_node("hitl_gate", hitl_gate_node) # BLOCKS. Waits for human.
graph.add_node("report", report_node)       # Generate final report

graph.add_edge(START, "reader")
graph.add_edge("reader", "sql_agent")
graph.add_edge("sql_agent", "auditor")
graph.add_edge("auditor", "hitl_gate")
graph.add_edge("hitl_gate", "report")
graph.add_edge("report", END)
```

This is real code from the codebase. The graph definition is 5 nodes and 6 edges. Thats it. The complexity isnt in the graph — its in the decisions at each node boundary.

The Reader Agent calls Phase 1's RAG pipeline to extract the negotiated rate from the contract. It sanitizes external content before including it in any LLM prompt (strips "ignore previous instructions" patterns, truncates to 2,000 chars). The rate extraction uses an LLM (gpt-5-mini, ~EUR 0.003 per call) coz contract clauses are unstructured text and you need language understanding to find "EUR 0.45/kg for pharmaceutical cargo, minimum volume 5,000 kg."

The SQL Agent queries the invoice database with parameterized queries. This is where most tutorials go wrong. They give the agent a db.execute() function and let it write SQL. We use asyncpg with `$1` parameter binding:

```python
row = await conn.fetchrow(
    "SELECT invoice_id, vendor, contract_id, issue_date, "
    "total_amount, currency FROM invoices WHERE invoice_id = $1",
    invoice_id,  # passed as data, never as SQL
)
```

The injection text `'; DROP TABLE invoices; --` is literally passed as a string parameter. It becomes `WHERE invoice_id = '; DROP TABLE invoices; --'` which just returns zero rows. The defense is structural, not pattern matching. We tested 5 injection patterns (DROP, UNION, boolean blind, stacked queries, comment injection) but the test count is irrelevant — parameterized queries make the entire CLASS of attack impossible. On top of that, the SQL agent uses a `logicore_reader` database role with SELECT-only permissions. Two independent defense layers, either sufficient alone.

The Auditor Agent is the one that surprised me the most during development. I initially planned to use an LLM for the rate comparison. Then I looked at what the comparison actually is: `(actual_rate - contract_rate) / contract_rate * 100`. Thats arithmetic. The CPU does it for EUR 0.00 per comparison, deterministically, without hallucination risk, and the result is idempotent (same inputs always produce same outputs). Using GPT for subtraction would cost EUR 0.02 per invoice, introduce non-determinism, and break crash recovery guarantees.

Gene Kim has this concept in "The Phoenix Project" about identifying the actual constraint in a system. The constraint in invoice auditing isnt rate comparison — its rate EXTRACTION from unstructured contract text. Thats where the LLM adds value. Everything downstream is deterministic data flow.

## 4. The Hard Part: Making It Stop

The HITL gateway is the most important node in the graph and it does almost nothing:

```python
async def hitl_gate_node(state: AuditGraphState) -> dict[str, Any]:
    return {"status": "approved"}
```

Thats the pass-through version for unit tests. In production, the graph is compiled with `interrupt_before=["hitl_gate"]`. LangGraph's state machine stops execution before this node runs. The workflow state is checkpointed to PostgreSQL. The API returns status `"awaiting_approval"`. Nothing else happens until a human calls `POST /api/v1/audit/{run_id}/approve`.

I chose `interrupt_before` over `interrupt()` inside the node for a specific reason. With `interrupt_before`, the hitl_gate node is completely unaware that it blocks. Its a pure pass-through. This means changing the approval UX later (adding multi-reviewer approval, adding timeout escalation, adding a Slack notification) never requires touching node code. Its the open-closed principle applied to workflow orchestration — open for extension in the approval mechanism, closed for modification in the node logic.

The alternative (interrupt() inside the node, which is what you see in most LangGraph tutorials) couples HITL logic to business logic. Every workflow change becomes a regression risk in the node that handles blocking.

This was also the deciding factor for LangGraph over CrewAI. CrewAI excels at creative agent collaboration — agents that brainstorm, iterate, delegate dynamically. Thats genuinely useful for research workflows and content generation. But for financial audit workflows you need three things CrewAI doesnt provide natively:

| Requirement | LangGraph | CrewAI |
|---|---|---|
| Deterministic routing (A→B→C, never B→A) | State machine enforcement | Non-deterministic delegation |
| Hard HITL interrupt (blocks until human acts) | First-class `interrupt_before` | Not built in |
| PostgreSQL checkpointing (survives crashes) | Built-in checkpointer | Manual implementation |

This isnt "LangGraph is better." Its "LangGraph is correct for this problem." If I were building a research assistant that explores topics and generates reports, CrewAI's dynamic delegation would be a feature, not a liability.

## 5. Crash Recovery: The Demo That Changes Minds

Nassim Taleb's concept of antifragility applies directly to workflow systems. A fragile system fails when stressed. A robust system survives. An antifragile system gets stronger. Most multi-agent demos are fragile — kill the process and all state is lost.

The PostgreSQL checkpointer makes the system robust. After every node executes, the full state (extracted rates, invoice data, discrepancies, approval status) is written to PostgreSQL in a transaction. If the server dies between the auditor node and the HITL gate, the restart re-runs only the auditor node (which is idempotent — same inputs, same outputs). The reader and SQL agent dont re-execute.

The HITL gate is where this matters most. The CFO reviews a EUR 588 discrepancy at 5 PM on Friday. She wants to check something with the vendor before approving. She closes the tab. The server restarts overnight for maintenance. On Monday morning she opens the dashboard, and the workflow is still sitting there at "awaiting_approval" with the same discrepancy data she saw on Friday. No re-processing. No "please re-review."

We verified this at every node boundary: crash after reader (resumes at sql_agent), crash after sql_agent (resumes at auditor), crash after auditor (resumes at hitl_gate), crash during indefinite HITL wait (resumes at hitl_gate with state intact). Every node transition is crash-safe — the system never loses work and never asks you to re-review.

The prerequisite is idempotency. Every agent must produce the same output when given the same input. The SQL query for invoice INV-2024-0847 always returns the same rows (the DB doesnt change during an audit). The rate comparison math is deterministic. The reader agent uses temperature=0 for extraction. One caveat: real LLMs at temperature > 0 could produce slightly different rate extractions on re-run. This is mitigated by temperature=0 in production and result-hash verification (if the re-run produces different rates, we log the divergence instead of silently proceeding). Mapped to Phase 4's observability layer for systematic tracking.

## 6. The Cost Model: Why CTOs Actually Listen

Daniel Kahneman's research on loss aversion suggests losses are felt roughly 2x as strongly as equivalent gains. In enterprise AI, I've found the ratio is even higher. A CTO who hears "AI costs EUR 5.56/month" nods politely. A CTO who hears "youre losing EUR 40,800/year in undetected overcharges" leans forward.

The cost model breaks down by discrepancy band:

| Band | Volume (est.) | Model | Cost/Decision | Monthly |
|---|---|---|---|---|
| <1% (auto-approve) | ~600/mo (60%) | Classification only | EUR 0.00002 | EUR 0.012 |
| 1-5% (AI investigate) | ~250/mo (25%) | gpt-5-mini | EUR 0.003 | EUR 0.75 |
| 5-15% (HITL escalation) | ~120/mo (12%) | gpt-5.2 | EUR 0.02 | EUR 2.40 |
| >15% (CFO alert) | ~30/mo (3%) | gpt-5.2 + multi-agent | EUR 0.08 | EUR 2.40 |
| **Total** | **1,000/mo** | | | **EUR 5.56** |

Using GPT-5.2 for everything would cost ~EUR 20/month. 3.6x more with zero quality benefit on the 60% of invoices that are rounding errors or FX fluctuations. The auditor agent being a pure function (no LLM) saves another ~EUR 240/year at 12,000 invoices.

The comparison that closes the conversation: one human clerk at EUR 45/hour doing 50 manual audits per month costs EUR 6,750. The AI costs EUR 5.56 for the same 1,000 invoices. ROI: 1,214x. Break-even in month 3 including development costs.

## 7. Dynamic Delegation: When the Agent Needs Help

Sometimes the auditor finds a discrepancy that doesnt make sense. The invoice says EUR 0.52/kg, the contract says EUR 0.45/kg, but a description mentions "temporary surcharge." Was the contract amended?

The auditor cant answer this. It compares rates, it doesnt read legal amendments. So it delegates — spawns a compliance sub-agent that searches for contract amendments with temporarily elevated clearance (the amendment might be in a confidential legal document the auditor doesnt normally have access to).

The trigger is keyword-based, not LLM-based. This was a deliberate recall-over-precision tradeoff. If the description contains any of 11 keywords (amendment, surcharge, penalty, annex, rider, modification, protocol, etc.), the compliance check fires.

False positive: unnecessary compliance check, costs ~500ms and one RAG query. False negative: missed contract amendment, costs EUR 136-588 per invoice in undetected overcharges. At 270-1176x cost asymmetry, you optimize for recall. The switching condition: move to LLM-based trigger when false positive rate exceeds 30% and the 500ms penalty starts causing latency SLA violations.

The security angle is the part I spent the most time on. The compliance sub-agent operates at clearance level 3. The parent auditor operates at clearance level 2. The sub-agent's findings go through a ClearanceFilter before they enter the parent's state:

```python
class ClearanceFilter:
    @staticmethod
    def filter(findings: list[dict], parent_clearance: int) -> list[dict]:
        return [
            f for f in findings
            if f.get("clearance_level", 1) <= parent_clearance
        ]
```

This runs in Python, not in the LLM prompt. A prompt injection cant bypass it. Missing clearance_level defaults to 1 (most restrictive assumption, not most permissive). The filter is the LAST step before data enters the parent state — enforced by the graph structure, not by agent instructions.

Without this filter, a legitimate workflow produces a data leak. The sub-agent retrieves confidential contract terms at clearance 3, returns them to the clearance-2 parent, and a clearance-2 user sees confidential data in the audit report. No attacker needed. No exploit. Just a missing architectural guard. The analysis priced this at EUR 25,000-250,000 per incident under RODO (Polish GDPR).

## 8. What Breaks

Single currency assumption. Every invoice comparison assumes the invoice currency matches the contract currency. A Swiss franc invoice compared against a euro contract produces a meaningless discrepancy percentage. This is a real scenario — LogiCore does cross-border transport through Switzerland. Mapped to Phase 7/8 for currency normalization.

Polish-language delegation keywords. The 11 keywords are English. A contract amendment written in Polish ("aneks do umowy", "dopłata", "klauzula karnej") wont trigger the compliance sub-agent. For a Polish logistics company this is a real gap. Mapped to Phase 10.

Concurrent approval race. Two approvers clicking "approve" and "reject" simultaneously — our test is sequential, not truly concurrent. In-memory state transitions are not atomic under real async concurrency. Production PostgreSQL provides real atomicity. Mapped to Phase 4.

I find honesty about boundaries more useful than claims about capability. Every reader can evaluate whether these boundaries matter for their use case.

## 9. What I'd Do Differently

I'd design the discrepancy classifier accuracy requirements upfront. We have 4 bands (<1%, 1-5%, 5-15%, >15%) and the boundaries are tested with 22 invoices. But there's no formal accuracy threshold for the classifier. A misclassification that sends a 12% overcharge to auto-approve (the <1% band) costs EUR 588 per incident. The 98% accuracy requirement on the <1% vs >=1% boundary should have been a design constraint from day 1, not something discovered during review.

I'd also implement the HITL timeout escalation chain from the start. Right now if the CFO doesnt approve, the workflow waits forever. In production you need 24h → email reminder, 48h → backup approver notification, 72h → auto-reject with full audit trail. The architecture supports it (the hitl_gate node is a pass-through, so adding escalation logic is orthogonal to the node) but the escalation logic itself isnt built. Vendor dispute windows are typically 30 days, so a workflow blocked for a week directly costs money.

Peter Drucker's principle — "what gets measured gets managed" — applies here too. Without Langfuse tracing (Phase 4), I cant answer "what percentage of audits trigger dynamic delegation?" or "whats the average time from audit start to human approval?" I have the architecture to track it but not the observability layer yet.

## 10. Vendor Lock-In & Swap Costs

| Component | Current | Swap to | Swap Cost | When |
|---|---|---|---|---|
| LLM (rate extraction) | Azure OpenAI gpt-5-mini | Any LangChain-compatible LLM | ~1 day (change config) | If Azure pricing changes or data residency requires on-prem |
| LLM (classification) | Azure OpenAI gpt-5.2 | Ollama + local model | ~1 week (accuracy validation) | Phase 6 air-gapped deployment |
| Orchestration | LangGraph | Custom asyncio | ~3-4 weeks (rebuild checkpointer, HITL, state machine) | If LangGraph pricing/licensing changes |
| Vector DB | Qdrant (for reader agent) | Any compatible vector DB | ~2 days (adapter pattern from Phase 1) | If Qdrant pricing changes |
| Checkpointer | PostgreSQL | Redis or SQLite | ~1 day (LangGraph supports multiple backends) | If PostgreSQL is unavailable |
| Re-ranker | BGE-m3 (local) | Cohere API | ~1 day (BaseReranker ABC) | If latency SLA requires faster re-ranking |

The highest lock-in risk is LangGraph itself. The state machine pattern, checkpointer integration, and HITL interrupt mechanism are LangGraph-specific. Swapping to custom asyncio would mean rebuilding the checkpointer, state management, and interrupt mechanism from scratch. At current pricing (LangGraph is open source) this isnt a concern, but if LangSmith/LangGraph Cloud becomes required, the swap cost is real. Mitigation: the graph definition is 136 lines. The node functions are framework-agnostic pure functions.

## 11. Series Close

Phase 3/12 of LogiCore. The system finds overcharges, stops, waits for humans, survives crashes, and costs EUR 5.56/month for 1,000 invoices. Every claim in this article is backed by a test that proves what the system REFUSES to do, not just what it can.

Next up: you cant trace why your AI answered what it answered. When the auditor says "15.6% overcharge," can you show which contract clause it extracted the rate from, which embedding model found that clause, and how much that extraction cost? Without observability, every AI decision is a black box — and black boxes are liabilities, not features. Thats Phase 4: the trust layer.
