---
phase: 3
date: "2026-03-08"
selected: A
---

# Phase 3 Implementation Approaches

## Approach A: Layered Bottom-Up (TDD-Friendly)

**Summary**: Build in testable layers: domain models → individual agents (standalone functions) → LangGraph graph wiring → HITL gateway → dynamic delegation → API endpoints → crash recovery. Each layer is independently testable before composing.

**Pros**:
- Each layer has clear RED→GREEN→REFACTOR cycles
- Agents are pure functions first, LangGraph nodes second — easy to unit test
- Dynamic delegation built on proven base graph, not interleaved with it
- Crash recovery tests come last with full confidence in the graph
- Matches Phase 1/2 pattern (unit → integration → e2e)

**Cons**:
- More files touched per "pass" (revisit agents when wiring graph)
- End-to-end demo not visible until layer 5+

**Effort**: L (3-4 sessions)
**Risk**: Layer boundaries may need adjustment as LangGraph quirks emerge

## Approach B: Vertical Slice (Feature-First)

**Summary**: Build one complete vertical slice first — the "happy path" audit (Reader → SQL → Auditor → Report, no HITL, no delegation). Get it working end-to-end. Then add HITL gateway. Then add dynamic delegation. Then add crash recovery.

**Pros**:
- Working demo faster (happy path end-to-end in session 1)
- Each slice adds one capability, easy to demonstrate progress
- Natural commit boundaries (each slice is a complete feature)

**Cons**:
- HITL is retrofitted into existing graph (may require refactoring edges)
- Dynamic delegation is the hardest part and comes last — risk of running out of steam
- Tests may need rewriting when HITL changes the graph structure

**Effort**: L (3-4 sessions)
**Risk**: Retrofitting HITL/delegation may require significant graph restructuring

## Approach C: Graph-First (Architecture-Driven)

**Summary**: Design the full LangGraph state machine first (all nodes, edges, interrupt points, delegation paths). Build stubs for every node. Then implement each node one by one. The graph structure never changes — only the node implementations fill in.

**Pros**:
- Graph architecture is locked early — no retrofitting
- All test scaffolding (graph routing, interrupt behavior) can be written immediately
- HITL and delegation are first-class from day 1
- Crash recovery tests can start early (with stub nodes)
- Clearest separation between "orchestration" and "agent logic"

**Cons**:
- Requires upfront design confidence (graph changes are expensive)
- Stub nodes may mask integration issues until late
- More abstract initial work before visible results

**Effort**: L (3-4 sessions)
**Risk**: Upfront graph design may not account for LangGraph API surprises

## Recommendation

**Approach C (Graph-First)** is the strongest fit for Phase 3. Rationale:

1. **The graph IS the deliverable.** Phase 3's architect value is the orchestration pattern, not the individual agents. Locking the graph first matches the "build vs buy" story — the agents are interchangeable, the graph is the IP.

2. **HITL and delegation must be first-class.** Approaches A and B risk treating them as afterthoughts. The analysis shows clearance escalation is the #1 security risk and crash recovery is the #1 demo moment. Both must be designed into the graph from the start.

3. **TDD works naturally.** Write graph routing tests against stubs → they pass → swap stubs for real implementations → tests still pass. The graph tests never change.

4. **Matches the spec exactly.** The phase spec defines a state machine with explicit nodes and edges. Building graph-first is literally building to spec.

Build order within Approach C:
1. Domain models + mock data (Invoice, Contract, AuditState)
2. Full graph definition with stub nodes (all edges, interrupts, delegation)
3. Graph routing tests (unit: which node follows which, interrupt behavior)
4. Reader agent implementation (uses Phase 1/2 RAG)
5. SQL agent implementation (read-only role, parameterized queries)
6. Auditor agent + discrepancy classifier (4 bands)
7. Dynamic delegation + clearance filter
8. HITL gateway (interrupt_before + approval endpoint)
9. Report generator
10. API endpoints (start, status, approve)
11. Crash recovery tests (kill + resume at each node)
12. Red-team tests (SQL injection, clearance leak, HITL bypass, rate limiting)

## Selected: Approach A (Layered Bottom-Up)

User selected Approach A. Priority: QUALITY over speed. Each layer is independently testable with strict TDD. Build order:

1. Domain models + mock data (Invoice, Contract, DiscrepancyReport, AuditState)
2. Individual agents as standalone pure functions (Reader, SQL, Auditor, Report Generator)
3. LangGraph graph wiring (state machine, edges, entry/exit)
4. HITL gateway (interrupt_before, approval endpoint)
5. Dynamic delegation (compliance sub-agent, clearance filter)
6. PostgreSQL checkpointer + crash recovery
7. API endpoints (start, status, approve)
8. Red-team tests (SQL injection, clearance leak, HITL bypass, rate limiting)

Each layer: RED → GREEN → REFACTOR → commit → update tracker.
