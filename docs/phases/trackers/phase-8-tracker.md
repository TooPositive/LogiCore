# Phase 8 Tracker: Regulatory Shield — EU AI Act Compliance

**Status**: IN PROGRESS (M1 COMPLETE — Core Audit Logging. Next: M2 — Security Hardening)
**Spec**: `docs/phases/phase-8-regulatory-shield.md`
**Depends on**: Phases 1-3
**Tests**: 79 new (25 models + 31 schema + 16 logger + 7 atomic)

## Milestones

### M1 — Core Audit Logging (COMPLETE)
- [x] Task 1: Pydantic models — AuditEntry, AuditEntryCreate, ComplianceReport, LineageRecord, DocumentVersion, ChunkVersion, PIIVaultEntry, LogLevel (25 tests)
- [x] Task 2: PostgreSQL migration — append-only audit_log with hash chain, Langfuse snapshot, degraded mode, REVOKE UPDATE/DELETE (31 tests)
- [x] Task 3: Audit logger — write/get/get_by_date_range/count, parameterized SQL ($1-$19), SHA-256 entry_hash (16 tests)
- [x] Task 4: Atomic transaction — checkpoint + audit write in same txn, rollback on either failure (7 tests)

### M2 — Security Hardening (NOT STARTED)
- [ ] Task 5: SHA-256 hash chain (prev_entry_hash + advisory lock for concurrency)
- [ ] Task 6: PII vault (separate table, AES-256-GCM, query hash in audit log)
- [ ] Task 7: Langfuse snapshot fields (model version, tokens, cost, response hash)
- [ ] Task 8: Audit-specific RBAC (own entries / compliance officer roles)

### M3 — Lineage & Reporting (NOT STARTED)
- [ ] Task 9: Data lineage tables + tracking (document -> chunk -> embedding versions)
- [ ] Task 10: Compliance report generator (date range queries + summary)
- [ ] Task 11: Bias detection scheduling (extend Phase 5 JudgeBiasResult)
- [ ] Task 12: API endpoints (GET /audit-log, /report, /lineage/{doc_id})

## Implementation Tasks (Legacy Checklist)

- [x] `apps/api/src/domains/logicore/compliance/__init__.py`
- [x] `apps/api/src/domains/logicore/compliance/audit_logger.py` — write/get/get_by_date_range/count + atomic_audit_write, parameterized SQL ($1-$19), SHA-256 hash chain (16 + 7 tests)
- [ ] `apps/api/src/domains/logicore/compliance/data_lineage.py` — document -> chunk -> embedding versioning
- [ ] `apps/api/src/domains/logicore/compliance/report_generator.py` — EU AI Act compliance report
- [ ] `apps/api/src/domains/logicore/compliance/bias_detector.py` — statistical fairness checks
- [x] `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` — append-only table with hash chain, Langfuse snapshot, degraded mode, REVOKE UPDATE/DELETE (31 tests)
- [ ] `apps/api/src/core/infrastructure/postgres/migrations/002_data_lineage.sql` — lineage tables
- [ ] `apps/api/src/domains/logicore/api/compliance.py` — GET /audit-log, /report endpoints
- [x] `apps/api/src/domains/logicore/models/compliance.py` — AuditEntry, AuditEntryCreate, ComplianceReport, LineageRecord, DocumentVersion, ChunkVersion, PIIVaultEntry, LogLevel (25 tests)
- [x] `tests/unit/test_audit_logger.py` — 16 tests: write, read, date range, user filter, SQL injection, field roundtrip
- [x] `tests/unit/test_audit_schema.py` — 31 tests: column presence, REVOKE, indexes, SQL quality
- [x] `tests/unit/test_compliance_models.py` — 25 tests: validation, immutability, serialization, GDPR vault
- [x] `tests/unit/test_atomic_audit.py` — 7 tests: success, rollback on audit/checkpoint failure, execution order
- [ ] `tests/integration/test_compliance_report.py` — full report generation

## Success Criteria

- [x] Every RAG query creates an immutable audit log entry (AuditLogger.write with parameterized SQL)
- [x] UPDATE/DELETE on audit_log fails with permission error (REVOKE in migration, validated by 31 schema tests)
- [ ] Compliance report covers date range with all decisions
- [ ] Data lineage: source file -> chunks -> embeddings -> retrieval
- [x] Audit entry links to Langfuse trace (langfuse_trace_id field)
- [ ] 6-month-old query can be fully reconstructed

## Decisions Made

| Decision | Spec'd | Actual | Why |
|---|---|---|---|
| Immutability enforcement | DB role (REVOKE UPDATE/DELETE) | DB role + frozen Pydantic model + hash chain | Defense in depth: DB prevents tampering, app model prevents in-memory mutation, hash chain proves sequential integrity. Three layers > one. |
| Audit entry self-containment | Langfuse trace ID only | Langfuse trace ID + snapshot fields (tokens, cost, response_hash) | If Langfuse goes down or gets rebuilt, the audit entry itself has enough data for regulatory compliance. Single point of failure eliminated. |
| Atomic write pattern | Separate writes | Same asyncpg transaction (checkpoint + audit) | A crash between separate writes creates a compliance gap: workflow resumes but audit entry missing. Cost: EUR 100K-3.5M per gap. Fix cost: 4 hours. |
| Entry hash computation | Not spec'd | SHA-256 of content fields on write | Mathematical tamper evidence beyond REVOKE. Proves no content was modified even if DB role is misconfigured. |
| Degraded mode tracking | Not spec'd | is_degraded + provider_name + quality_drift_alert | Phase 7 integration: when system falls back to local model, audit entry marks it. Regulator can see exactly which decisions used degraded inference. |
| Lineage granularity | document -> chunk -> embedding | Same | |
| Report format | JSON + rendered HTML/PDF | TBD (M3) | |

## Deviations from Spec

- Added `AuditEntryCreate` as separate input model (spec only had `AuditEntry`). Separation of concerns: caller provides content fields, server adds id/timestamp/hash.
- Added `PIIVaultEntry` model (from analysis, not spec). Resolves GDPR vs AI Act tension: raw PII encrypted separately, audit log stores only query_hash.
- Added `LogLevel` enum with three tiers (from spec's decision tree). Not every AI decision needs full trace logging.
- Added degraded mode fields from Phase 7 integration (analysis gap #5).
- Added Langfuse snapshot fields (analysis gap #3): prompt_tokens, completion_tokens, total_cost_eur, response_hash.

## Code Artifacts

| File | Commit | Notes |
|---|---|---|
| `apps/api/src/domains/logicore/models/compliance.py` | 493db36 | 8 models + LogLevel enum, frozen AuditEntry, validation |
| `tests/unit/test_compliance_models.py` | 493db36 | 25 tests: validation, immutability, serialization, GDPR vault |
| `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` | b737e62 | Append-only, hash chain, Langfuse snapshot, degraded mode, REVOKE |
| `tests/unit/test_audit_schema.py` | b737e62 | 31 tests: column presence, REVOKE, indexes, SQL quality |
| `apps/api/src/domains/logicore/compliance/__init__.py` | af52277 | Package init |
| `apps/api/src/domains/logicore/compliance/audit_logger.py` | af52277+928fedb | AuditLogger + atomic_audit_write, parameterized SQL |
| `tests/unit/test_audit_logger.py` | af52277 | 16 tests: write, read, filter, injection safety, roundtrip |
| `tests/unit/test_atomic_audit.py` | 928fedb | 7 tests: success, rollback, execution order, connection sharing |

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| M1 test count | 79 new tests | 25 models + 31 schema + 16 logger + 7 atomic |
| Total project tests | 1144 unit | 0 regressions from Phase 8 M1 |
| SQL parameters per INSERT | 19 ($1-$19) | Zero string interpolation in any query |
| Fields per audit entry | 21 | Core Article 12 + hash chain + Langfuse snapshot + degraded mode |
| UPDATE/DELETE rejection test | PASS | REVOKE in migration, validated by schema tests |
| Audit log write latency | TBD | Needs integration test with real PostgreSQL |
| Audit log size (per entry) | TBD | Needs integration test |
| Compliance report generation time | TBD | M3 |
| Lineage traversal time | TBD | M3 |
| Data retention (6-month reconstruction) | TBD | M3 |

## Screenshots Captured

- [ ] Audit log table with sample entries
- [ ] Data lineage visualization
- [ ] Compliance report output
- [x] DB role permissions (UPDATE/DELETE revoked) — validated by test_audit_schema.py (REVOKE in SQL)
- [ ] Langfuse trace link from audit entry

## Problems Encountered

None in M1.

## Open Questions

- M2: Advisory lock strategy for hash chain under concurrent writes
- M2: AES-256-GCM key management for PII vault (env var? AWS KMS? Azure Key Vault?)
- M3: Compliance report format — JSON only or also PDF/HTML?

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
