# ADR-015: Hash Chain over Blockchain for Audit Tamper Evidence

## Status
Accepted

## Context
Phase 8 (EU AI Act compliance) requires an immutable audit trail for all AI-assisted decisions. Each audit entry must be tamper-evident — if any entry is modified after the fact, the modification must be detectable. The trail must survive regulatory inspection under EU AI Act Article 12 (record-keeping).

## Decision
**SHA-256 hash chain** where each entry stores `prev_entry_hash` + `entry_hash`. Concurrency protected by PostgreSQL `pg_advisory_xact_lock`.

## Rationale

| Criteria | Hash Chain (chosen) | Private Blockchain (Hyperledger) | Managed Audit Platform (Splunk) | REVOKE-Only |
|----------|--------------------|---------------------------------|-------------------------------|-------------|
| Trust model | SHA-256 tamper evidence | SHA-256 tamper evidence (identical) | Vendor-controlled | No tamper evidence |
| Writers | Single (LogiCore) | Multi-writer consensus | N/A | N/A |
| Cost | EUR 0/year | EUR 8,000-15,000/year (managed node) | EUR 12,000-25,000/year | EUR 0/year |
| Verification | `SELECT` + recompute chain | Blockchain explorer | Vendor dashboard | Cannot verify |
| Infrastructure | PostgreSQL (already deployed) | Hyperledger Fabric cluster | SaaS dependency | PostgreSQL |

**Three-layer immutability (defense in depth):**
1. `REVOKE UPDATE, DELETE` on audit table (DB-level)
2. Frozen Pydantic models (application-level)
3. SHA-256 hash chain (mathematical verification)

## Consequences
- No multi-writer consensus — if LogiCore ever needs 5+ independent audit writers, blockchain becomes justified
- Advisory lock (`pg_advisory_xact_lock(8_000_000_001)`) serializes hash chain writes — prevents two concurrent writes from forking the chain by reading the same `prev_hash`
- At 10K decisions/day (~0.1 writes/second), serialization overhead is negligible
- Critical bug prevented: `created_at` is passed as an explicit parameter (Python `datetime.now(UTC)`) to both the hash computation and the INSERT — not `DEFAULT NOW()`. Two clocks (Python vs PostgreSQL) differ by microseconds, which would make every entry appear tampered during verification
- When to revisit: at >1,000 writes/second or with multiple independent writers
