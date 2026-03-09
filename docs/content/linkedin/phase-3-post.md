# Phase 3 LinkedIn Post: Multi-Agent Orchestration

**Mode**: Builder Update | **Accuracy**: Accurate-but-exciting (95% true)
**Date**: 2026-03-08 | **Status**: draft

---

A clerk at a logistics company spends 3 hours cross-referencing an invoice against a contract PDF. She finds a EUR 588 overcharge. It took 3 hours coz the contract rate was in one system, the invoice in another, and the rate comparison required mentally converting per-kg pricing across 8,400 kg of pharmaceutical cargo.

She catches this one coz the number is big enough to look wrong. But what about the invoice that bills EUR 0.46/kg instead of EUR 0.45/kg? That 2.2% across 6,200 kg is only EUR 62. Her eyes slide right past it. At 12,000 invoices per year and a 2.5% miss rate, thats roughly EUR 40,800 walking out the door annually. Silently. Nobody notices until the annual audit.

So I built 3 AI agents. One reads contracts via RAG. One queries the invoice database (read-only SQL, parameterized queries). One compares the rates. Together they find the EUR 588 overcharge in about 8 seconds instead of 3 hours.

But heres the part nobody talks about when they demo multi-agent AI: what happens AFTER the agents find the problem.

In most demos the agent just... acts. Generates a report, sends an email, updates a database. In enterprise finance thats a non-starter. You cant have AI autonomously disputing vendor invoices. EU AI Act Article 14 requires human oversight for high-risk decisions. Your CFO wants to see the discrepancy before anyone contacts the vendor.

So the system finds EUR 588 and then it STOPS. Hard stop. State machine interrupt. The LangGraph workflow blocks at a HITL (human-in-the-loop) gateway and waits. Could be 5 minutes, could be 3 days if the CFO is on vacation. The state is persisted in PostgreSQL. If the server crashes at 2 AM and comes back at 6 AM, the workflow is still sitting there waiting for approval. No re-processing, no lost work.

This was actually the hardest engineering decision. Not the agents (those are just functions with injected dependencies). The hard part is making the system STOP reliably and RESUME correctly.

I chose LangGraph over CrewAI specifically for this. CrewAI is great for creative agent collaboration — agents that brainstorm, research, iterate. But for financial workflows you need deterministic routing (A always goes to B, never randomly to C), first-class HITL interrupts, and PostgreSQL checkpointing. CrewAI doesnt have any of those built in.

The cost model is probably my favorite part. The auditor agent that compares rates? Its a pure function. No LLM call. Deterministic math. EUR 0.00 per comparison. I couldve used GPT for this (and most tutorials would) but why spend EUR 0.02 per invoice on arithmetic the CPU can do for free? The LLM only fires for rate extraction from contract text (gpt-5-mini, ~EUR 0.003) and complex discrepancy classification.

Total AI cost for 1,000 invoices per month: EUR 5.56. One human clerk doing 50 manual audits per month costs EUR 6,750. The ROI math is not subtle.

What breaks: the system currently assumes single-currency invoices. A Swiss franc invoice compared against a euro contract would produce a meaningless discrepancy number. Thats a real scenario for a Polish logistics company doing cross-border transport. Not ignored — just not solved yet.

The delegation trigger (when the auditor needs to check if a contract was amended) uses keyword matching, not an LLM. "Amendment", "surcharge", "penalty" etc. False positive costs 500ms. False negative costs EUR 136-588 in missed overcharges. At that asymmetry you want high recall even if it means occasionally checking amendments that dont exist.

SQL injection against the invoice database? Structurally impossible. The injection text is literally passed as a data parameter via $1 binding — it never becomes SQL. The database role is SELECT-only on top of that. Two independent defense layers, either sufficient alone.

Post 3/12 in the LogiCore series. Next up: you cant trace why your AI answered what it answered. When something goes wrong in a financial audit, "the AI said so" is not an acceptable answer 😅

---

## Reply Ammo

### 1. "3 agents for a rate comparison seems overengineered"

yeah if all your data lived in one database youd just write a SQL JOIN. the problem is the contract rate lives in a vector database (retrieved via RAG with RBAC filtering), the invoice lives in PostgreSQL, and comparing them requires understanding which cargo type maps to which contract clause. three agents is actually three data sources with three access patterns. you could collapse the SQL and auditor into one but then your agent needs both DB read access AND rate comparison logic which violates single-responsibility and makes the security model harder to audit.

### 2. "Why not just use GPT for everything including the rate comparison?"

coz rate comparison is arithmetic, not reasoning. EUR 0.52 minus EUR 0.45 equals EUR 0.07. you dont need a language model for subtraction. using GPT for this adds EUR 0.02/invoice, introduces non-determinism (LLMs occasionally get math wrong), and makes crash recovery harder coz the auditor node is no longer idempotent. the LLM is for extracting rates from unstructured contract text where you actually need language understanding.

### 3. "EUR 5.56/month sounds too cheap to be real"

its tiered routing. 60% of invoices have <1% discrepancy (rounding, FX fluctuation) and get classified by the cheapest model for EUR 0.00002 each. 25% need investigation (gpt-5-mini at EUR 0.003). only 15% hit the expensive model (gpt-5.2 at EUR 0.02). flat gpt-5.2 for everything would be ~EUR 20/month. still cheap, but 3.6x more than necessary.

### 4. "CrewAI has improved a lot recently"

probably true, havent checked in a while. but for financial workflows the decision framework is: do you need deterministic routing (A->B->C, never B->A), hard HITL interrupts (state machine blocks, not soft prompts), and PostgreSQL checkpointing? if yes, LangGraph. if youre building research agents, brainstorming workflows, or creative tools where non-deterministic delegation is a feature not a bug, CrewAI is probably better.

### 5. "Human-in-the-loop slows everything down"

yes. thats the point. for financial decisions the speed limit is human judgment, not compute. the system goes from 3 hours (manual) to 8 seconds (AI audit) + human review time. even if the CFO takes 2 days to click approve, thats still faster than the old process. and you get a compliance-safe audit trail.

### 6. "What about the EUR 40,800/year in false negatives?"

thats the scariest number. 2.5% false negative rate on 12,000 invoices/year means 300 overcharges slip through at avg EUR 136 each. silently, automatically, nobody notices. the mitigation: when any upstream component is degraded (re-ranker down, RAG quality dipping), the auto-approve band disables entirely and everything goes through human review. you trade speed for safety.

### 7. "Why keyword-based delegation instead of asking the LLM?"

cost asymmetry. false positive (unnecessary compliance check): 500ms + 1 RAG query. false negative (missed contract amendment): EUR 136-588 per invoice. at 270-1176x cost asymmetry you optimize for recall not precision. the switching condition: move to LLM-based trigger when false positive rate exceeds 30% and the 500ms penalty starts hitting your latency SLA.

### 8. "How do you handle the security of elevated clearance for the sub-agent?"

the compliance sub-agent temporarily gets clearance level 3 to check contract amendments. but its return value goes through a ClearanceFilter (runs in Python, not in the LLM prompt) that strips anything above the parent agents clearance level before the data enters the parent state. the filter is enforced by the graph structure, not by agent instructions. a prompt injection cant bypass Python code.

### 9. "PostgreSQL checkpointing has overhead"

yes, a few ms per node transition. for a workflow that blocks for hours waiting on human approval, checkpoint overhead is irrelevant. the alternative is losing the entire workflow state on server restart and asking the CFO to re-review a discrepancy she already reviewed yesterday. the overhead is worth it even at 10x the actual cost.

### 10. "What happens when the CFO doesnt approve for a week?"

Right now the workflow waits indefinitely. In production you'd want a 24h email reminder, 48h backup approver notification, 72h auto-reject with full audit trail. The architecture supports it — the HITL gate is a pass-through node, so adding escalation logic is orthogonal to the workflow. But vendor dispute windows are typically 30 days under Polish commercial law. A blocked workflow directly costs money.
