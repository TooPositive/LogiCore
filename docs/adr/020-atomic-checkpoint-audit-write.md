# ADR-020: Atomic Checkpoint + Audit Write in Same Transaction

## Status
Accepted

## Context
Phase 8's compliance layer must write an audit log entry every time a LangGraph workflow makes a decision (approve/reject/escalate). LangGraph's checkpointer also writes workflow state to PostgreSQL. If these are separate operations, a crash between the two creates a compliance gap: the workflow resumes (checkpoint exists) but the audit entry was never written. Under EU AI Act Article 12, every AI-assisted decision must be recorded.

## Decision
**Both the checkpoint write and the audit log write happen in the same asyncpg transaction.** Same connection, same `BEGIN`/`COMMIT` — both succeed or both roll back.

## Rationale

| Approach | Crash Window | Consistency | Infrastructure |
|----------|-------------|-------------|---------------|
| **Same transaction (chosen)** | Zero — atomic | Both or neither | Same PostgreSQL (already deployed) |
| Separate writes | Gap between checkpoint and audit | Checkpoint without audit = compliance violation | Same PostgreSQL |
| Event queue (Kafka/SQS) | Eventual consistency gap | Audit entry arrives later | Additional infrastructure |
| Two-phase commit | Zero (with coordinator) | Distributed atomic | External coordinator |

## Consequences
- Both systems must use the same PostgreSQL database — cannot move the audit log to an external SaaS without losing the atomicity guarantee
- Connection injection pattern (not pool injection): methods accept an `asyncpg.Connection`, not an `asyncpg.Pool` — the caller controls the transaction boundary
- 6 lines of code prevent a EUR 3.5M fine (7% of EUR 50M turnover under EU AI Act)
- If the checkpointer moves to a different database, or if a second audit destination is added (e.g., S3 for archival), the guarantee must be re-evaluated
- Write latency increases marginally (~2ms for the combined transaction vs ~1ms each separately) — acceptable for compliance-critical operations
