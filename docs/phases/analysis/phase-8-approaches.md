---
phase: 8
date: "2026-03-09"
selected: C
---

# Phase 8 Implementation Approaches

## Approach A: Full Compliance Stack (Spec + Analysis Gaps)

**Summary**: Implement everything in the phase spec PLUS the critical gaps identified in analysis: PII vault (GDPR/AI Act resolution), SHA-256 hash chain (tamper evidence), Langfuse snapshot fields, atomic transactions, audit-specific RBAC, and bias detection scheduling.

**Pros**:
- Addresses GDPR vs AI Act tension architecturally (PII vault)
- Hash chain provides mathematical proof of non-tampering (648:1 ratio story holds)
- Langfuse snapshot makes audit entries self-contained (no single point of failure)
- Atomic transaction prevents the #1 compliance gap (crash between checkpoint + audit write)
- Most complete architect story for content — every CTO concern is addressed

**Cons**:
- Largest scope (~12-14 tasks vs spec's 11)
- PII vault adds encryption complexity (AES-256-GCM + key management)
- Hash chain serialization under concurrency needs careful testing
- Document versioning in Qdrant requires ingestion pipeline changes

**Effort**: L (4-5 days)
**Risk**: Hash chain concurrency and document versioning are the complexity bombs. Both need thorough TDD.

## Approach B: Spec-Faithful + Selective Hardening

**Summary**: Implement exactly what the spec says, plus only the CRITICAL gaps: atomic transactions and Langfuse snapshots. Defer PII vault (GDPR), hash chain, and bias detection to future hardening.

**Pros**:
- Faster delivery (3-4 days)
- Covers the core EU AI Act Article 12 requirements
- Atomic transaction (the highest-impact gap) is included
- Less encryption complexity

**Cons**:
- No GDPR/AI Act resolution — raw query text in immutable log creates liability
- No mathematical tamper evidence — REVOKE is necessary but not sufficient
- Weaker architect story: "we built compliance logging" vs "we solved the GDPR paradox"
- Deferred items will need to be retrofitted later (more expensive)

**Effort**: M (3-4 days)
**Risk**: GDPR liability from storing raw PII in append-only table. A content-reviewer or CTO would flag this immediately.

## Approach C: Modular Build with Milestone Commits

**Summary**: Same full scope as Approach A, but organized into 3 clear milestones with commits between each. M1: Core audit logging (immutable table, atomic writes, basic API). M2: Security hardening (hash chain, PII vault, RBAC). M3: Lineage + reporting (document versioning, compliance reports, bias detection).

**Pros**:
- Same completeness as Approach A
- Natural stopping points if session runs long — each milestone is independently valuable
- Easier to review: 3 focused PRs or commit groups
- M1 alone satisfies minimum Article 12 compliance

**Cons**:
- Slightly more overhead from milestone planning
- Same total effort as Approach A

**Effort**: L (4-5 days, same as A but better structured)
**Risk**: Same as Approach A, but mitigated by milestone structure — if M2 takes longer than expected, M1 is already committed and working.

## Selected: Approach C — Modular Build with Milestone Commits

User selected Approach C. Quality is top priority — full compliance stack with milestone structure.

## Recommendation (original)

**Approach C** (Modular Build). Same scope as A (we need the full compliance stack for the architect story), but the milestone structure means:
1. If we stop after M1, we have working Article 12 compliance
2. If we stop after M2, we have GDPR + tamper evidence
3. M3 adds the lineage + reporting cherry on top

The milestone boundaries also create natural commit points for the tracker.

### Proposed Milestones

**M1 — Core Audit Logging** (Tasks 1-4):
- Pydantic models (AuditEntry, ComplianceReport, LineageRecord)
- PostgreSQL migration (audit_log table, append-only enforcement)
- Audit logger (async writer with parameterized queries)
- Atomic transaction integration (checkpoint + audit in same txn)

**M2 — Security Hardening** (Tasks 5-8):
- SHA-256 hash chain (prev_entry_hash + entry_hash + advisory lock)
- PII vault (separate table, AES-256-GCM, query hash in audit log)
- Langfuse snapshot fields (model version, tokens, cost, response hash)
- Audit-specific RBAC (own entries / compliance officer roles)

**M3 — Lineage & Reporting** (Tasks 9-12):
- Data lineage tables + tracking (document → chunk → embedding versions)
- Compliance report generator (date range queries + summary)
- Bias detection scheduling (extend Phase 5 JudgeBiasResult)
- API endpoints (GET /audit-log, /report, /lineage/{doc_id})
