---
phase: 8
phase_name: "The Regulatory Shield -- EU AI Act Compliance"
date: "2026-03-09"
score: 28/30
verdict: "PROCEED"
---

# Phase 8 Architect Review: The Regulatory Shield -- EU AI Act Compliance

*Re-review after critical fixes. Previous review: 25/30 FIX FIRST.*

## Score: 28/30

| Category | Score | Weight |
|---|---|---|
| Framing Quality | 9/10 | 33% -- are conclusions useful to a CTO? |
| Evidence Depth | 8/10 | 33% -- do benchmarks have enough cases, categories, and boundaries to back the claims? |
| Architect Rigor | 5/5 | 17% -- security model sound, negative tests, benchmarks designed to break things? |
| Spec Compliance | 5/5 | 17% -- was the promise kept? |

## Fix Verification (Re-Review Focus)

### Fix 1: Hash Chain Timestamp Mismatch -- VERIFIED CORRECT

The original bug: `write_with_hash_chain` computed the chain hash using Python `datetime.now(UTC)` but the INSERT relied on PostgreSQL `DEFAULT NOW()`. Since those two clocks can differ by microseconds-to-milliseconds, `verify_hash_chain` would recompute using the DB-stored `created_at` and get a hash mismatch. On real PostgreSQL, every single chain entry would appear tampered.

The fix: A new `_INSERT_WITH_TIMESTAMP_SQL` query accepts `$20` as an explicit `created_at` parameter. `write_with_hash_chain` (line 340) captures `now = datetime.now(UTC)`, passes it both to `compute_chain_hash` (line 342) and as `$20` to the INSERT (line 377). The DB stores exactly the timestamp used in the hash.

Test coverage of the fix: 3 targeted tests in `TestHashChainTimestampConsistency`:
- `test_write_passes_created_at_as_sql_parameter` -- verifies `$20` is in the SQL and the 20th parameter is a datetime.
- `test_hash_uses_same_timestamp_as_stored` -- captures the params, recomputes the hash using the stored `created_at`, asserts match.
- `test_chain_verification_passes_after_write` -- writes 3 entries, simulates the DB returning the exact passed `created_at`, then runs `verify_hash_chain` and confirms valid chain.

Assessment: Correct fix. The root cause was structural (two independent clocks), and the solution eliminates the second clock entirely. The tests catch the exact failure mode. This would have been a showstopper on real PostgreSQL -- catching it before integration testing is good architect discipline.

### Fix 2: PII Detection Polish Diacritics -- VERIFIED CORRECT

The original bug: `_NAME_PATTERN` used `[A-Z][a-z]+` which cannot match Polish names like Lukasz, Zrodlowska, or any name with diacritics (a, c, e, l, n, o, s, z, z and uppercase equivalents). In a Polish logistics company, this means the PII detector fails on most employee names.

The fix: `_NAME_PATTERN` now uses `[A-ZACELNOSZZZ][a-zacelnoszzz]+` (with actual Polish diacritical characters). Polish PII keywords added: pensja, umowa, zatrudnienie, zdrowie, medyczne, osobowe, adres, telefon, zwolnienie, dyscyplina, wynagrodzenie (and their inflected forms via prefix matching).

Test coverage of the fix: 4 new tests:
- `test_detects_polish_diacritics_in_name` -- 3 sub-assertions: Wojciech Jozwiak + pensja, Lukasz Sliwinski + contract, Zaneta Zrodlowska + medical.
- `test_detects_mixed_ascii_diacritics_name` -- Marek Lozinski, Ewa Blaszczyk.
- `test_detects_abbreviated_name_with_keyword` -- email pattern catches j.kowalski@.
- `test_detects_eleven_digit_pesel_standalone` -- PESEL without keyword context.

Assessment: Good fix for the reported issue. The keyword list covers key Polish employment/medical terms with inflection-aware prefix patterns. However, there are edge cases not yet covered (see Evidence Depth).

### Fix 3: Bias Detection Minimum Sample Size -- VERIFIED CORRECT

The original bug: `_detect_proportion_bias` would flag bias on n=5 (e.g., 3 out of 5 in one department). At low n, this is noise, not signal.

The fix: `_MIN_SAMPLE_SIZE = 30` added. When `total < 30`, `_detect_proportion_bias` returns `(False, [], True)` where the third element signals `insufficient_data`. All three callers (routing bias, model preference, degraded correlation) propagate this flag.

Test coverage: 4 new tests:
- `test_small_sample_returns_insufficient_data` -- n=10 returns insufficient_data=True.
- `test_sufficient_sample_enables_detection` -- n=100 detects bias normally.
- `test_boundary_at_30_enables_detection` -- n=30 is the exact boundary.
- `test_model_preference_also_checks_sample_size` -- confirms both detection methods share the threshold.

Assessment: Correct. n=30 is the standard CLT threshold for proportion tests. The `insufficient_data` flag lets the API caller distinguish "no bias" from "not enough data to tell" -- critical for a compliance report that a regulator reads.

## Framing Failures Found

| Where | Junior Framing (current) | Architect Reframe (fix) | Impact |
|---|---|---|---|
| Tracker "PII detection cases: 8" | Reports a count without framing the coverage gap | "PII detection covers 12 patterns (Polish names, emails, PESEL, phones, 11 Polish keywords). False-positive rate: acceptable (encrypting non-PII costs nothing). Remaining gap: obfuscated PII (name split across fields, partial PESEL) -- Phase 10 LLM Firewall adds semantic PII detection." | LOW -- the coverage is actually reasonable, just framed as a count |
| Tracker "RBAC roles tested: 5" | Reports count, not the security model | Already well-framed in audit_rbac.py docstring ("unknown role defaults to user -- principle of least privilege") but tracker line should match | LOW -- docstring is architect-grade, tracker line is just a metric |
| Tracker "Compliance report generation time: TBD" and "Lineage traversal time: TBD" | Deferred metrics without explaining why | "Performance benchmarks deferred to integration testing (Phase 12). At projected 10K entries/day x 10 years = 36.5M records, the `idx_audit_log_created_at` index keeps date-range queries under 100ms. Recommend: add `EXPLAIN ANALYZE` benchmarks when PostgreSQL integration tests are available." | MODERATE -- a CTO would want at least an order-of-magnitude estimate |

## Evidence Depth Failures Found

| Claim | Cases (n) | Credible? | Missing Categories | Boundary Found? | Phase Teaser |
|---|---|---|---|---|---|
| Hash chain tamper detection works | 18 (15 original + 3 fix) | YES -- covers empty, single, multi-entry, tampered data, broken link, timestamp consistency, determinism | Concurrent writes under real Postgres advisory lock | No real-DB boundary test | Phase 12 integration: hash chain at 1K+ entries on real PostgreSQL |
| PII detection catches Polish PII | 12 (8 original + 4 fix) | YES -- covers name+keyword, email, phone, PESEL, Polish diacritics, negatives | Obfuscated PII (name in separate fields), Unicode normalization (NFC vs NFD for diacritics), partial PESEL (10 digits) | No -- heuristic precision/recall not measured | Phase 10 LLM Firewall adds semantic PII detection beyond regex |
| Bias detection >2x threshold is sound | 12 (8 original + 4 fix) | YES -- covers even/biased distributions, 3+ groups, empty period, min sample, degraded correlation | 2-group edge case (2x of 50% = 100%), seasonal variation, time-series drift | Boundary at n=30 found and tested | Phase 12: chi-squared test when n>10K |
| RBAC filters audit entries correctly | 15 | YES -- 5 roles, department isolation, unknown defaults, empty list, own-entry always visible | Role escalation attempt (user passing viewer_role="admin"), JWT spoofing | No -- trusts query param, no server-side verification | Phase 10 JWT middleware replaces query param |
| Audit log immutability | 31 schema + 16 logger + 7 atomic | YES -- comprehensive SQL schema validation, parameterized queries, atomic transactions | Real PostgreSQL REVOKE verification (currently validates SQL text only) | No integration test with real PG | Phase 12 integration |
| Langfuse snapshot self-containment | 13 | YES -- extraction, defaults, all-mismatch detection, none-field handling | Langfuse API format changes over time, snapshot field evolution | No versioning boundary | Phase 12: snapshot schema versioning |
| Data lineage full chain | 13 | YES -- multi-version, multi-chunk, source hash tamper detection, SQL injection | Lineage with re-chunking (same doc, different chunking strategy), embedding model migration | No scale boundary | Phase 12 integration: lineage at 100+ doc versions |
| Compliance report completeness | 11 | YES -- date range, all entries included, model aggregation, degraded count, hash chain, entry_count_hash | Report at 10K+ entries (performance), concurrent report generation | No scale boundary | Phase 12: report generation benchmark at scale |
| API endpoints work with RBAC | 11 | YES -- 403 enforcement, date filtering, lineage, hash chain, bias, input validation | Concurrent API requests, large response payloads, pagination | No load boundary | Phase 9/12: API load testing |

0 out of 9 major claims are backed by fewer than 5 cases. Evidence depth is solid.

## What a CTO Would Respect

The GDPR-vs-AI-Act tension is resolved architecturally, not just documented: PII vault with soft delete preserves audit structure while enabling erasure, and the hash chain proves no entries were silently removed or modified. The atomic audit write pattern (checkpoint + audit in same transaction) closes the compliance gap that exists in every naive "log after the fact" implementation. The three-layer immutability model (DB REVOKE + frozen Pydantic + hash chain) demonstrates defense-in-depth thinking that goes well beyond the spec's requirements. The cost framing (EUR 5,400/year logging vs EUR 3.5M fine) makes the business case impossible to argue against.

## What a CTO Would Question

"You have 196 tests but they all run against mocked asyncpg connections. Has anyone verified that the hash chain actually works on real PostgreSQL? That the REVOKE actually prevents UPDATE?" The answer is honest: no integration tests yet, deferred to Phase 12. A CTO would accept this for a demo but would want an integration test before any production conversation. The viewer_role-via-query-param pattern is explicitly called out as a testing convenience with Phase 10 JWT noted as the replacement -- good transparency, but a CTO might still raise an eyebrow at 5 endpoints where RBAC is enforced by a user-supplied query parameter.

## Architect Rigor Checklist

| Check | Status | Note |
|---|---|---|
| Security/trust model sound | PASS | Three-layer immutability (DB REVOKE + frozen model + hash chain). GDPR/AI Act tension resolved via PII vault separation. Atomic write prevents compliance gaps. Advisory lock prevents chain forking. All queries parameterized ($1-$20). |
| Negative tests | PASS | SQL injection blocked (audit_logger, pii_vault, data_lineage). Tampered entries detected. Broken chain links detected. GDPR-erased entries return None. Unknown roles default to most restrictive. 403 for non-privileged roles. Input validation rejects invalid dates. |
| Benchmarks designed to break | PASS | Hash chain tampering (modify response_text mid-chain). Broken prev_hash links. GDPR erasure + retrieval. PII detection false negatives (invoice without PII, shipping route). Bias detection with insufficient data. Concurrent advisory lock contention. |
| Test pyramid | PASS | 196 unit tests, 0 integration (deferred to Phase 12 with documented rationale), 0 e2e. Pyramid is top-heavy but appropriate for a compliance module where logic correctness matters more than integration at demo stage. |
| Spec criteria met | PASS | All 6 success criteria checked: immutable audit entry (write + schema), UPDATE/DELETE rejection (REVOKE), compliance report (date range + all decisions), data lineage (full chain), Langfuse trace link (langfuse_trace_id field + snapshot), 6-month reconstruction (version tracking + lineage + hash chain). |
| Deviations documented | PASS | 12 deviations documented in tracker's "Deviations from Spec" section, each with rationale. Key additions beyond spec: hash chain, PII vault, Langfuse snapshot, audit RBAC, bias detection, degraded mode tracking. All justified by the phase analysis's gap identification. |

## Benchmark Expansion Needed

These are future-phase items, not blockers.

1. **Hash chain on real PostgreSQL** (Phase 12 integration)
   - Write 100 entries with hash chain via real asyncpg pool
   - Verify chain integrity end-to-end
   - Verify REVOKE actually prevents `UPDATE audit_log SET response_text = 'tampered'`
   - Expected: chain valid, UPDATE raises permission error

2. **PII detection edge cases** (Phase 10 LLM Firewall)
   - Obfuscated names: "J. K-ski" near salary keyword
   - Unicode normalization: NFC vs NFD encoding of Polish diacritics
   - Cross-field PII: name in metadata, salary in query_text
   - Expected: regex heuristic misses these; LLM-based semantic detection catches them

3. **Report generation at scale** (Phase 12 integration)
   - 10K entries in audit_log, generate compliance report
   - Measure: report generation time, memory usage
   - Expected: <5s with `idx_audit_log_created_at` index; flag if >10s

4. **Bias detection with real distributions** (Phase 12 integration)
   - Inject 1000 audit entries with realistic department/model distributions
   - Verify chi-squared test recommendation: current >2x threshold vs statistical test
   - Expected: >2x threshold works for 3-5 groups, needs chi-squared for 10+ groups

5. **RBAC with JWT** (Phase 10 LLM Firewall)
   - Replace viewer_role query param with JWT extraction middleware
   - Test role escalation attempts (modified JWT, expired token)
   - Expected: 401 for invalid JWT, 403 for insufficient role

## Gaps to Close

1. **PROGRESS.md needs Phase 8 sprint summary.** The "Next up: Phase 8" line is still there but no completed sprint section exists. Add the standard "What a CTO Would See" table with the key findings. (Documentation gap, not code gap.)

2. **Tracker test count says 185 but actual count is 196.** The 11 fix-related tests bring the total to 196. Update tracker header to reflect actual count.

3. **Lineage endpoint has no RBAC.** GET `/lineage/{doc_id}` is unrestricted. Noted for Phase 10 JWT middleware -- acceptable as demo-stage deferral but should be tracked.

4. **Hash chain verify endpoint has no RBAC.** GET `/hash-chain/verify` is unrestricted. Same Phase 10 deferral.

## Architect Recommendation: PROCEED

The three critical/moderate issues from the first review are all fixed correctly and tested:

1. **Hash chain timestamp mismatch** -- FIXED. The `created_at` is now passed as `$20` to the INSERT, eliminating the dual-clock bug. 3 targeted tests verify the exact failure mode.

2. **PII detection Polish diacritics** -- FIXED. Name pattern and keyword list now cover Polish characters and employment terms. 4 new tests with real Polish names.

3. **Bias detection minimum sample size** -- FIXED. `_MIN_SAMPLE_SIZE = 30` with `insufficient_data` flag propagated through all callers. Boundary test at exactly n=30.

The compliance module demonstrates architect-level thinking across multiple dimensions:
- **Defense-in-depth** for immutability (3 layers, not 1)
- **GDPR/AI Act tension** resolved architecturally (PII vault separation)
- **Atomic writes** close the compliance gap naive logging ignores
- **Hash chain** provides mathematical tamper evidence beyond access control
- **Self-contained audit entries** eliminate Langfuse as single point of failure
- **Bias detection** with statistical minimum sample discipline

Remaining items (no RBAC on lineage/hash-chain endpoints, no integration tests on real PostgreSQL, performance benchmarks TBD) are all correctly categorized as Phase 10/12 deferrals and do not undermine architect credibility at demo stage.

196 tests, 0 failures, lint clean. The phase is solid.
