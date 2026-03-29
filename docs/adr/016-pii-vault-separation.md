# ADR-016: PII Vault Separation (GDPR Art.17 vs EU AI Act Art.12)

## Status
Accepted

## Context
GDPR Article 17 (right to erasure) requires deleting personal data on request. EU AI Act Article 12 (record-keeping) requires an immutable audit trail. These directly conflict when the audit trail contains employee queries with PII (e.g., "What is Jan Kowalski's termination procedure?"). Logging the query satisfies the AI Act; storing the PII violates GDPR on erasure request.

## Decision
**Two tables, two lifecycles:**
- `audit_log` — immutable, stores a SHA-256 hash of the query (not the raw text). Hash chain integrity preserved.
- `audit_pii_vault` — encrypted (injectable `encrypt_fn`), supports soft-delete. Raw PII stored here with a foreign key to the audit entry.

## Rationale

| Approach | GDPR Compliance | AI Act Compliance | Integrity |
|----------|----------------|-------------------|-----------|
| **Two tables (chosen)** | Delete from vault, audit entry intact | Immutable hash chain unbroken | Hash of query still verifiable |
| Single table with GDPR exemption | Legally indefensible — no AI Act exemption exists | Compliant | N/A — legal risk |
| Tokenization service | Compliant (revoke token) | Compliant | Adds infrastructure complexity |
| Don't log PII queries | Compliant | NON-COMPLIANT — gaps for exactly the queries regulators care about | N/A |

**Encryption is injectable** — `encrypt_fn: Callable[[str], bytes]`:
- Tests: mock XOR cipher
- Production: Azure Key Vault
- AWS migration: swap to KMS — no code change

## Consequences
- Two write paths: every PII-containing query writes to both tables. Higher write latency for ~5% of queries (those containing PII)
- PII detection uses Unicode-aware regex for Polish diacritics + 11 Polish employment keywords (e.g., "wypowiedzenie", "zwolnienie", "wynagrodzenie")
- On GDPR erasure request: delete from `audit_pii_vault`, `audit_log` entry stays with its hash — regulators can verify the decision happened without seeing the PII
- Both writes happen in the same asyncpg transaction (ADR-015's atomic write pattern) — no compliance gaps
- When to revisit: if PII detection needs semantic understanding beyond regex, add LLM-based detection in Phase 10
