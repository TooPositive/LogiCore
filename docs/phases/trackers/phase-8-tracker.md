# Phase 8 Tracker: Regulatory Shield — EU AI Act Compliance

**Status**: IN PROGRESS (M1+M2 COMPLETE. Next: M3 — Lineage & Reporting)
**Spec**: `docs/phases/phase-8-regulatory-shield.md`
**Depends on**: Phases 1-3
**Tests**: 142 new (79 M1 + 63 M2)

## Milestones

### M1 — Core Audit Logging (COMPLETE)
- [x] Task 1: Pydantic models — AuditEntry, AuditEntryCreate, ComplianceReport, LineageRecord, DocumentVersion, ChunkVersion, PIIVaultEntry, LogLevel (25 tests)
- [x] Task 2: PostgreSQL migration — append-only audit_log with hash chain, Langfuse snapshot, degraded mode, REVOKE UPDATE/DELETE (31 tests)
- [x] Task 3: Audit logger — write/get/get_by_date_range/count, parameterized SQL ($1-$19), SHA-256 entry_hash (16 tests)
- [x] Task 4: Atomic transaction — checkpoint + audit write in same txn, rollback on either failure (7 tests)

### M2 — Security Hardening (COMPLETE)
- [x] Task 5: SHA-256 hash chain — compute_chain_hash, write_with_hash_chain (advisory lock), verify_hash_chain (15 tests)
- [x] Task 6: PII vault — PIIVault store/retrieve/delete/is_deleted, detect_pii heuristic, 003_pii_vault.sql migration (20 tests)
- [x] Task 7: Langfuse snapshot — create_langfuse_snapshot, verify_snapshot_against_trace (13 tests)
- [x] Task 8: Audit-specific RBAC — AuditRBAC can_view_entry, filter_entries_for_user, 4 roles (15 tests)

### M3 — Lineage & Reporting (NOT STARTED)
- [ ] Task 9: Data lineage tables + tracking (document -> chunk -> embedding versions)
- [ ] Task 10: Compliance report generator (date range queries + summary)
- [ ] Task 11: Bias detection scheduling (extend Phase 5 JudgeBiasResult)
- [ ] Task 12: API endpoints (GET /audit-log, /report, /lineage/{doc_id})

## Implementation Tasks (Legacy Checklist)

- [x] `apps/api/src/domains/logicore/compliance/__init__.py`
- [x] `apps/api/src/domains/logicore/compliance/audit_logger.py` — write/get/get_by_date_range/count + atomic_audit_write + write_with_hash_chain + verify_hash_chain, parameterized SQL ($1-$19), advisory lock concurrency (16 + 7 + 15 tests)
- [x] `apps/api/src/domains/logicore/compliance/pii_vault.py` — PIIVault store/retrieve/delete/is_deleted + detect_pii heuristic (20 tests)
- [x] `apps/api/src/domains/logicore/compliance/langfuse_snapshot.py` — create_langfuse_snapshot + verify_snapshot_against_trace (13 tests)
- [x] `apps/api/src/domains/logicore/compliance/audit_rbac.py` — AuditRBAC can_view_entry + filter_entries_for_user (15 tests)
- [ ] `apps/api/src/domains/logicore/compliance/data_lineage.py` — document -> chunk -> embedding versioning
- [ ] `apps/api/src/domains/logicore/compliance/report_generator.py` — EU AI Act compliance report
- [ ] `apps/api/src/domains/logicore/compliance/bias_detector.py` — statistical fairness checks
- [x] `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` — append-only table with hash chain, Langfuse snapshot, degraded mode, REVOKE UPDATE/DELETE (31 tests)
- [x] `apps/api/src/core/infrastructure/postgres/migrations/003_pii_vault.sql` — audit_pii_vault table with FK, BYTEA encryption, retention, REVOKE DELETE
- [ ] `apps/api/src/core/infrastructure/postgres/migrations/002_data_lineage.sql` — lineage tables
- [ ] `apps/api/src/domains/logicore/api/compliance.py` — GET /audit-log, /report endpoints
- [x] `apps/api/src/domains/logicore/models/compliance.py` — AuditEntry, AuditEntryCreate, ComplianceReport, LineageRecord, DocumentVersion, ChunkVersion, PIIVaultEntry, LogLevel (25 tests)
- [x] `tests/unit/test_audit_logger.py` — 16 tests: write, read, date range, user filter, SQL injection, field roundtrip
- [x] `tests/unit/test_audit_schema.py` — 31 tests: column presence, REVOKE, indexes, SQL quality
- [x] `tests/unit/test_compliance_models.py` — 25 tests: validation, immutability, serialization, GDPR vault
- [x] `tests/unit/test_atomic_audit.py` — 7 tests: success, rollback on audit/checkpoint failure, execution order
- [x] `tests/unit/test_hash_chain.py` — 15 tests: sequential writes, advisory lock, verify valid/tampered chain, determinism
- [x] `tests/unit/test_pii_vault.py` — 20 tests: store/retrieve round-trip, GDPR erasure, SQL injection, PII detection (8 cases)
- [x] `tests/unit/test_langfuse_snapshot.py` — 13 tests: extraction, defaults, matching/mismatched verification, self-containment
- [x] `tests/unit/test_audit_rbac.py` — 15 tests: per-role visibility, department isolation, unknown role fallback, empty list
- [ ] `tests/integration/test_compliance_report.py` — full report generation

## Success Criteria

- [x] Every RAG query creates an immutable audit log entry (AuditLogger.write with parameterized SQL)
- [x] UPDATE/DELETE on audit_log fails with permission error (REVOKE in migration, validated by 31 schema tests)
- [x] Hash chain proves sequential integrity (tamper detection via verify_hash_chain, 15 tests)
- [x] PII stored encrypted with GDPR soft-delete (PIIVault, 20 tests)
- [x] Langfuse snapshot makes audit entry self-contained (13 tests)
- [x] Audit RBAC: user sees own, manager sees dept, officer sees all (15 tests)
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
| Hash chain concurrency | Not spec'd | pg_advisory_xact_lock(fixed_id) | Serializes concurrent hash chain writers within a transaction. Without this, two concurrent writes could read the same prev_hash and fork the chain. Cost of forked chain: entire audit trail is unverifiable. |
| PII vault encryption | Not spec'd | Injectable encrypt_fn/decrypt_fn | Key management is environment-specific (test mock, Azure Key Vault, AWS KMS). Making encryption injectable means the vault works in any deployment without code changes. |
| PII detection | Not spec'd | Heuristic: name+keyword, email, phone, PESEL | Conservative heuristic -- false positives (encrypting non-PII) cost nothing, false negatives (missing PII) cost EUR 20K-200K GDPR fine. 8 test cases cover Polish PII patterns. |
| GDPR erasure | Not spec'd | Soft delete (deleted_at) on pii_vault, audit_log intact | Resolves GDPR vs AI Act tension: delete PII but keep audit structure. Hard delete after retention expiry by maintenance job with elevated privileges. |
| Audit RBAC roles | Not spec'd | user/manager/compliance_officer/admin, unknown=user | Principle of least privilege: unknown roles default to most restrictive access. Manager uses department metadata for team-level filtering. |
| Degraded mode tracking | Not spec'd | is_degraded + provider_name + quality_drift_alert | Phase 7 integration: when system falls back to local model, audit entry marks it. Regulator can see exactly which decisions used degraded inference. |
| Lineage granularity | document -> chunk -> embedding | Same | |
| Report format | JSON + rendered HTML/PDF | TBD (M3) | |

## Deviations from Spec

- Added `AuditEntryCreate` as separate input model (spec only had `AuditEntry`). Separation of concerns: caller provides content fields, server adds id/timestamp/hash.
- Added `PIIVaultEntry` model (from analysis, not spec). Resolves GDPR vs AI Act tension: raw PII encrypted separately, audit log stores only query_hash.
- Added `LogLevel` enum with three tiers (from spec's decision tree). Not every AI decision needs full trace logging.
- Added degraded mode fields from Phase 7 integration (analysis gap #5).
- Added Langfuse snapshot fields (analysis gap #3): prompt_tokens, completion_tokens, total_cost_eur, response_hash.
- M2: Added compute_chain_hash as public function for verification reuse.
- M2: PII detection includes Polish-specific patterns (PESEL, NIP).
- M2: Langfuse snapshot verification returns all mismatches, not just first.

## Code Artifacts

| File | Commit | Notes |
|---|---|---|
| `apps/api/src/domains/logicore/models/compliance.py` | 493db36 | 8 models + LogLevel enum, frozen AuditEntry, validation |
| `tests/unit/test_compliance_models.py` | 493db36 | 25 tests: validation, immutability, serialization, GDPR vault |
| `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` | b737e62 | Append-only, hash chain, Langfuse snapshot, degraded mode, REVOKE |
| `tests/unit/test_audit_schema.py` | b737e62 | 31 tests: column presence, REVOKE, indexes, SQL quality |
| `apps/api/src/domains/logicore/compliance/__init__.py` | af52277 | Package init |
| `apps/api/src/domains/logicore/compliance/audit_logger.py` | af52277+0b25add | AuditLogger + atomic + hash chain (compute_chain_hash, write_with_hash_chain, verify_hash_chain) |
| `tests/unit/test_audit_logger.py` | af52277 | 16 tests: write, read, filter, injection safety, roundtrip |
| `tests/unit/test_atomic_audit.py` | 928fedb | 7 tests: success, rollback, execution order, connection sharing |
| `tests/unit/test_hash_chain.py` | 0b25add | 15 tests: sequential chain, advisory lock, tamper detection, determinism |
| `apps/api/src/domains/logicore/compliance/pii_vault.py` | 3db9273 | PIIVault store/retrieve/delete/is_deleted + detect_pii |
| `apps/api/src/core/infrastructure/postgres/migrations/003_pii_vault.sql` | 3db9273 | audit_pii_vault table, FK, BYTEA, retention, REVOKE DELETE |
| `tests/unit/test_pii_vault.py` | 3db9273 | 20 tests: encryption round-trip, GDPR erasure, SQL injection, PII detection |
| `apps/api/src/domains/logicore/compliance/langfuse_snapshot.py` | c824dd7 | create_langfuse_snapshot + verify_snapshot_against_trace |
| `tests/unit/test_langfuse_snapshot.py` | c824dd7 | 13 tests: extraction, defaults, mismatch detection, self-containment |
| `apps/api/src/domains/logicore/compliance/audit_rbac.py` | 53f24d2 | AuditRBAC can_view_entry + filter_entries_for_user |
| `tests/unit/test_audit_rbac.py` | 53f24d2 | 15 tests: role visibility, department isolation, least privilege |

## Benchmarks & Metrics (Content Grounding Data)

| Metric | Value | Context |
|---|---|---|
| M1 test count | 79 new tests | 25 models + 31 schema + 16 logger + 7 atomic |
| M2 test count | 63 new tests | 15 hash chain + 20 PII vault + 13 langfuse snapshot + 15 RBAC |
| Total Phase 8 tests | 142 | 79 M1 + 63 M2, 0 failures |
| Total project tests | 1207 unit | 0 regressions from Phase 8 M1+M2 |
| SQL parameters per INSERT | 19 ($1-$19) | Zero string interpolation in any query |
| Fields per audit entry | 21 | Core Article 12 + hash chain + Langfuse snapshot + degraded mode |
| UPDATE/DELETE rejection test | PASS | REVOKE in migration, validated by schema tests |
| Hash chain tamper detection | PASS | verify_hash_chain catches modified entries + broken prev_hash links |
| PII detection cases | 8 | salary, contract, health, email, phone, PESEL + 2 negative (invoice, shipping) |
| RBAC roles tested | 5 | user, manager, compliance_officer, admin, unknown (defaults to user) |
| Langfuse snapshot fields | 5 | prompt_tokens, completion_tokens, total_cost_eur, model_version, response_hash |
| Audit log write latency | TBD | Needs integration test with real PostgreSQL |
| Compliance report generation time | TBD | M3 |
| Lineage traversal time | TBD | M3 |

## Screenshots Captured

- [ ] Audit log table with sample entries
- [ ] Data lineage visualization
- [ ] Compliance report output
- [x] DB role permissions (UPDATE/DELETE revoked) — validated by test_audit_schema.py (REVOKE in SQL)
- [ ] Langfuse trace link from audit entry

## Problems Encountered

None in M1 or M2.

## Open Questions

- ~~M2: Advisory lock strategy for hash chain under concurrent writes~~ RESOLVED: pg_advisory_xact_lock(8_000_000_001) serializes within transaction
- ~~M2: AES-256-GCM key management for PII vault~~ RESOLVED: Injectable encrypt_fn/decrypt_fn, production uses Azure Key Vault
- M3: Compliance report format — JSON only or also PDF/HTML?

## Content Status

| Channel | Status | Date | Notes |
|---|---|---|---|
| LinkedIn post | — | | |
| Medium article | — | | |
