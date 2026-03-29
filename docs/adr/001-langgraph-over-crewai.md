# ADR-001: LangGraph over CrewAI

## Status
Accepted

## Context
Need a multi-agent orchestration framework for enterprise logistics workflows (financial audits, customs processing, anomaly response). Key requirements: deterministic routing, human-in-the-loop gates, state persistence, observability.

## Decision
**LangGraph** as the primary orchestration framework.

## Rationale

| Criteria | LangGraph | CrewAI |
|----------|-----------|--------|
| Control flow | Explicit state machine — deterministic | Role-play delegation — non-deterministic |
| HITL support | First-class interrupt/resume | Bolt-on, limited |
| State persistence | Built-in checkpointer (Postgres) | Manual |
| Enterprise fit | Strict routing, auditable | Creative tasks, research |
| Observability | Native Langfuse/LangSmith integration | Limited |

## Consequences
- Steeper learning curve vs CrewAI's "just give agents roles"
- More boilerplate for graph definition
- Full control over execution order — critical for compliance logging (Phase 5)
- Checkpointer enables crash recovery and long-running workflows
