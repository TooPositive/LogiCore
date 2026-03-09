---
phase: 8
phase_name: "The Regulatory Shield -- EU AI Act Compliance"
date: "2026-03-09"
agents: [business-critical, cascade-analysis, cto-framework, safety-adversarial]
---

# Phase 8 Deep Analysis: The Regulatory Shield -- EU AI Act Compliance

## Top 5 Architect Insights

1. **Atomic audit writes are the single most critical engineering decision in this phase.** The LangGraph checkpointer (`AsyncPostgresSaver`) already uses PostgreSQL. The audit log MUST write in the same `asyncpg` transaction as the checkpoint save. A crash between separate writes creates a compliance gap: the workflow resumes (checkpoint survived) but the audit entry is missing. One gap discovered during a regulatory audit = EUR 100,000-3,500,000 fine. The fix costs 4 hours of engineering to pass a shared `connection` object through the checkpointer + audit logger. The risk of NOT doing it: unbounded.

2. **The GDPR-vs-AI-Act tension is the real architectural problem, not logging itself.** Article 12 of the EU AI Act mandates full trace logging for high-risk AI decisions. GDPR Article 17 (right to erasure) requires deletion on request. These directly conflict when audit logs contain PII (user queries like "Show me Jan Kowalski's employment history"). The architect decision: log user_id + query hash + chunk IDs (not raw query text) for PII-containing queries, with the full text stored in a separate PII vault with its own retention policy. This lets you delete PII on GDPR request while keeping the audit structure intact for AI Act compliance. Estimated effort: 2 extra days. Cost of ignoring it: EUR 20,000-200,000 GDPR fine per incident.

3. **Langfuse trace ID is a single point of failure for audit reconstruction -- and nobody is protecting it.** Every audit log entry references a Langfuse trace ID for "full reconstruction." But Langfuse self-hosted (Phase 4) stores traces in its own PostgreSQL instance. If Langfuse's database is rebuilt, restored from backup, or migrated, those trace IDs become dead links. Six months later, a regulator asks to reconstruct a decision -- the audit log entry exists, but the trace is gone. Solution: snapshot critical Langfuse trace data (token counts, model version, prompt/response hashes) INTO the audit log entry itself. The Langfuse trace ID is a convenience link for deep-dive, not the sole source of truth. Estimated storage overhead: ~2KB per entry. At 10,000 decisions/day, that is 20MB/day or 7.3GB/year -- negligible.

4. **The 648:1 cost ratio (EUR 5,400/year logging vs EUR 3,500,000 fine) is the most powerful CTO-facing number in this entire project.** No other phase has a ratio this stark. This is the LinkedIn hook. But the ratio only holds if the logging is genuinely immutable. A `REVOKE UPDATE, DELETE` on the application role is necessary but insufficient -- a DBA with superuser access can still modify rows. For true immutability, implement a SHA-256 hash chain: each audit entry includes the hash of the previous entry. Tampering with any row breaks the chain, and the break is detectable in O(n) time. This transforms the audit log from "we promise we didn't change it" to "here is mathematical proof we didn't change it."

5. **Document versioning is the hidden complexity bomb.** The phase spec says "old chunks preserved" when documents are re-ingested. But Qdrant has no native versioning -- you overwrite points or create new ones with different IDs. The current ingestion pipeline (`apps/api/src/core/rag/`) does not version chunk IDs. Retrofitting version-tagged chunk IDs (e.g., `contract-CTR-2024-001-v2.3-chunk-47`) into the existing Qdrant collection requires either: (a) a migration that re-IDs all existing points (risky, breaks existing audit references if any exist), or (b) a new collection schema that supports versioned point IDs alongside the existing unversioned ones. Option (b) is safer but doubles Qdrant storage for versioned documents. At 57 docs x 50 chunks x 1536 dims x 4 bytes = ~17MB, this is irrelevant at current scale but becomes meaningful at 10,000+ documents (~3GB duplicated).

## Gaps to Address Before Implementation

| Gap | Category | Impact | Effort to Fix |
|---|---|---|---|
| Atomic transaction between checkpointer and audit logger | Architecture | CRITICAL -- compliance gap on crash = EUR 100K-3.5M fine | 4 hours -- pass `conn` through `get_checkpointer()` and `audit_logger.write()` |
| PII in audit logs (GDPR vs AI Act conflict) | Compliance | HIGH -- full query text logging creates GDPR liability (EUR 20K-200K) | 2 days -- PII vault with separate retention, query hashing for audit log |
| Langfuse trace data not snapshotted in audit entry | Reliability | HIGH -- Langfuse rebuild orphans all trace IDs (EUR 50K-500K compliance violation) | 1 day -- add 5-6 fields to audit_log schema for critical trace data |
| No hash chain for tamper detection | Security | MEDIUM -- DB-level REVOKE is bypassable by superuser; no proof of non-tampering | 1 day -- SHA-256 chain linking each entry to its predecessor |
| Qdrant chunk IDs are not versioned | Architecture | HIGH -- cannot reconstruct "what the AI saw 6 months ago" for versioned docs | 3 days -- version-tagged chunk IDs in ingestion pipeline + lineage table |
| No audit log retention/archival strategy implemented | Operations | MEDIUM -- 36.5M rows after 10 years degrades report generation from 10min to 45min | 1 day -- partitioned tables by month, archive to cold storage after retention window |
| `InMemoryFallbackStore` in `langfuse_handler.py` loses traces on restart | Reliability | HIGH -- process crash loses all pending traces; reconciliation becomes impossible | 4 hours -- replace with PostgreSQL-backed fallback (same DB as audit log) |
| No bias detection baseline for Phase 8's scheduled bias checks | Architecture | LOW -- bias detection listed in spec but has no implementation detail or threshold | 1 day -- define fairness metrics, connect to Phase 5's `JudgeBiasResult` model |
| Degraded mode governance not wired to audit logging | Architecture | MEDIUM -- Phase 7's `is_degraded` flag should trigger elevated audit level | 4 hours -- check `ProviderChainResponse.is_degraded` in audit logger |

## Content Gold

- **"The 648:1 Ratio"** -- Full trace compliance logging costs EUR 5,400/year. A single unlogged decision costs up to EUR 3,500,000. That ratio is 648:1. If you are building AI systems in the EU and you are not logging immutably, you are not saving money -- you are buying a lottery ticket for the world's most expensive fine. (LinkedIn hook: works as a standalone post with the ratio as the headline number.)

- **"GDPR vs AI Act: The Compliance Paradox Nobody Talks About"** -- Article 12 says log everything. Article 17 says delete on request. Both carry fines. The architectural answer: separate the PII from the audit structure. Hash the query, store the hash in the immutable log, store the raw text in a deletable PII vault. Now you can delete PII on GDPR request while keeping the audit chain intact for the AI Act. (Medium deep-dive: 2,500+ words on the architectural pattern.)

- **"Why Database-Level Immutability is Not Enough"** -- `REVOKE UPDATE, DELETE` stops application code. It does not stop a DBA. A hash chain where each audit entry includes the SHA-256 of the previous entry creates mathematical proof of non-tampering. A regulator does not need to trust your word -- they can verify the chain themselves. (LinkedIn hook: "Your audit log is only as trustworthy as your weakest database admin.")

- **"The Audit Log That Survives a Langfuse Outage"** -- Most teams link their AI audit trail to their observability platform. When that platform has an outage or data loss, the audit trail has holes. Snapshot critical trace data (model version, token counts, cost, response hash) into the audit entry itself. Use the observability platform for convenience, not as a dependency. (Medium subsection: portable audit entries.)

- **"Document Versioning: The Boring Problem That Costs EUR 3.5M"** -- Your AI gave an answer 6 months ago based on contract v2.3. The contract is now v3.0. A regulator asks to reconstruct the decision. If you only kept the latest version, you cannot prove what the AI saw. Version-tagged chunk IDs + SHA-256 content hashes = complete reconstruction at any point in time. (LinkedIn carousel: 4-slide visual showing the versioning chain.)

## Recommended Phase Doc Updates

### 1. Add "PII Vault" section after the Audit Log Schema

```markdown
### PII-Aware Logging Architecture

The audit log stores query_hash (SHA-256) instead of raw query_text for PII-containing queries.
Raw query text is stored in a separate `audit_pii_vault` table with its own retention policy
(default: 2 years for non-regulated, 5 years for regulated queries).

GDPR right-to-erasure requests delete from `audit_pii_vault` only -- the audit_log entry
(with query_hash, chunk IDs, model version) remains intact for AI Act compliance.

```sql
CREATE TABLE audit_pii_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_entry_id UUID NOT NULL REFERENCES audit_log(id),
    query_text_encrypted BYTEA NOT NULL,  -- AES-256-GCM encrypted
    encryption_key_id VARCHAR(100) NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ  -- soft delete for GDPR
);
```
```

### 2. Add hash chain to Audit Log Schema

Add `prev_entry_hash VARCHAR(64)` and `entry_hash VARCHAR(64)` to the `audit_log` table. Each entry's hash is computed from `SHA-256(prev_hash || created_at || user_id || query_hash || response_hash || model_version)`. This creates a tamper-evident chain -- modifying any entry breaks the hash of all subsequent entries.

### 3. Replace Langfuse dependency with snapshot fields

Add to audit_log: `model_temperature FLOAT`, `prompt_tokens INT`, `completion_tokens INT`, `total_cost_eur DECIMAL`, `response_hash VARCHAR(64)`. The Langfuse trace_id remains as a convenience link, but reconstruction does not depend on Langfuse availability.

### 4. Add atomic transaction code example

Replace the current code example with one that shows the actual `asyncpg` integration:

```python
async with pg_pool.acquire() as conn:
    async with conn.transaction():
        # LangGraph checkpoint (uses same connection)
        await checkpointer.aput(config, checkpoint, metadata, conn=conn)
        # Audit log entry (same transaction)
        await conn.execute(
            "INSERT INTO audit_log (user_id, query_hash, ...) VALUES ($1, $2, ...)",
            user_id, query_hash, ...
        )
        # Both succeed or both roll back
```

### 5. Add retention/archival section

```markdown
### Retention & Archival Strategy

| Data Category | Hot Storage (PostgreSQL) | Warm Archive | Cold Archive | Total Retention |
|---|---|---|---|---|
| High-risk decisions (financial, HR) | 2 years | 3 years (partitioned) | 5 years (Azure Blob Archive) | 10 years |
| Standard decisions | 1 year | 2 years | 2 years | 5 years |
| PII vault | 2 years | -- | -- | 2 years (then purge) |
| Metadata-only entries | 1 year | -- | -- | 1 year |

Estimated storage costs:
- Hot: 10,000 decisions/day x 5KB/entry = 50MB/day = 18.25GB/year @ EUR 0.115/GB/mo = EUR 25/year
- Cold archive (Azure Blob Archive): EUR 0.002/GB/mo = EUR 0.44/year per 18.25GB
- Total 10-year cost: ~EUR 300 (storage is negligible vs EUR 5,400/year compute for logging)
```

## Red Team Tests to Write

### 1. Audit Log Immutability Bypass

```python
def test_audit_log_update_blocked():
    """Verify UPDATE on audit_log table is denied for application role."""
    # INSERT an entry
    # Attempt UPDATE -> expect permission denied
    # Attempt DELETE -> expect permission denied
    # Verify entry unchanged via SELECT

def test_audit_log_superuser_tamper_detected_by_hash_chain():
    """Even if superuser modifies a row, hash chain detects tampering."""
    # Insert 5 entries with hash chain
    # Modify entry #3 directly (simulating superuser bypass)
    # Run chain verification -> expect failure at entry #4
```

### 2. PII Leakage in Audit Logs

```python
def test_pii_query_logs_hash_not_plaintext():
    """Queries containing PII patterns store SHA-256 hash, not raw text."""
    # Submit query: "Show me Jan Kowalski's salary"
    # Read audit log entry
    # Verify query_text is SHA-256 hash, not plaintext
    # Verify PII vault contains encrypted plaintext

def test_gdpr_erasure_preserves_audit_structure():
    """Deleting PII vault entry does not break audit log integrity."""
    # Create audit entry with PII vault link
    # Delete PII vault entry (simulating GDPR request)
    # Verify audit log entry still exists with hash intact
    # Verify hash chain is not broken
```

### 3. Langfuse Trace ID Orphaning

```python
def test_audit_entry_reconstructable_without_langfuse():
    """Audit entry contains enough data to reconstruct decision without Langfuse."""
    # Create audit entry with snapshot fields
    # Simulate Langfuse unavailability
    # Reconstruct decision from audit entry alone
    # Verify: model version, token counts, cost, chunk IDs all present

def test_langfuse_fallback_store_survives_restart():
    """PostgreSQL-backed fallback store persists pending traces across restarts."""
    # Write 3 traces to fallback store
    # Simulate process restart (new store instance, same DB)
    # Verify 3 traces still pending
```

### 4. Atomic Transaction Failure Modes

```python
def test_audit_write_fails_rolls_back_checkpoint():
    """If audit log INSERT fails, checkpoint save also rolls back."""
    # Start transaction
    # Save checkpoint
    # Inject audit log failure (e.g., violate NOT NULL constraint)
    # Verify both checkpoint and audit entry are absent

def test_checkpoint_fails_rolls_back_audit():
    """If checkpoint save fails, audit log INSERT also rolls back."""
    # Start transaction
    # Write audit entry
    # Inject checkpoint failure
    # Verify both are absent
```

### 5. Document Version Tampering

```python
def test_document_version_hash_mismatch_detected():
    """Modifying a document after ingestion changes its SHA-256, breaking lineage."""
    # Ingest document with SHA-256 hash
    # Modify document content
    # Re-verify hash -> mismatch detected
    # Lineage query shows version discrepancy

def test_old_chunk_versions_preserved_after_reingestion():
    """Re-ingesting a document creates new version; old chunks remain queryable."""
    # Ingest document v1 -> get chunk IDs
    # Modify and re-ingest as v2 -> get new chunk IDs
    # Verify v1 chunks still exist in Qdrant
    # Verify audit entries referencing v1 chunks still resolve
```

### 6. Compliance Report Manipulation

```python
def test_compliance_report_cannot_exclude_entries():
    """Report generator cannot be tricked into omitting audit entries."""
    # Create 10 audit entries for a date range
    # Generate compliance report for that range
    # Verify all 10 entries appear -- no filtering by content or user

def test_compliance_report_includes_degraded_mode_decisions():
    """Decisions made during degraded mode (Phase 7) are flagged in report."""
    # Create audit entry with is_degraded=True
    # Generate report
    # Verify degraded decisions are prominently flagged
```

### 7. Timing Side-Channel on Audit Log Queries

```python
def test_audit_log_query_timing_does_not_leak_existence():
    """Querying audit logs for unauthorized entries should not reveal their existence."""
    # User with clearance 1 queries audit logs
    # Measure response time for existing clearance-4 entries vs nonexistent entries
    # Verify timing difference < 5ms (no statistically significant leak)
```

---

<details>
<summary>Business-Critical AI Angles (full report)</summary>

## Business-Critical Angles for Phase 8

### High-Impact Findings (top 3, ranked by EUR cost of failure)

1. **Audit trail gap from non-atomic writes: EUR 100,000-3,500,000 per incident.** The phase spec correctly identifies this risk but the current checkpointer implementation (`apps/api/src/core/infrastructure/postgres/checkpointer.py`) uses `AsyncPostgresSaver.from_conn_string()` which manages its own connection pool. The audit logger would need its own connection. Two separate connections = two separate transactions = crash between them creates a gap. The fix: both must share a single `asyncpg` connection within one transaction. LangGraph's `AsyncPostgresSaver` supports passing an external connection -- this needs verification and potentially a thin wrapper. If it does not support external connections, the alternative is a custom checkpointer that accepts `conn` as a parameter.

2. **Over-logging PII creates GDPR liability: EUR 20,000-200,000 per incident.** The audit log schema in the spec stores `query_text TEXT NOT NULL` -- raw user queries in plaintext. At LogiCore, users query about employees ("Show me Jan Kowalski's contract"), salary data, health records (pharmaceutical cargo handlers have medical clearance requirements). Every one of these queries stored in plaintext is a GDPR data processing record. Under RODO (Polish GDPR implementation), the UODO (Polish DPO) has issued fines ranging from PLN 100,000 to PLN 2,830,410 (EUR ~22,000 to EUR ~630,000) for unnecessary PII retention. The audit log's immutability makes this worse -- you cannot delete PII from an append-only table. Solution: encrypt PII in a separate vault table with a DELETE-capable retention policy.

3. **Langfuse trace ID becomes dead link after infrastructure change: EUR 50,000-500,000 compliance violation.** Langfuse self-hosted (Phase 4) runs in Docker with its own PostgreSQL database. Docker volume corruption, a Langfuse version upgrade that resets the database, or a migration to a different observability platform all orphan every trace ID in the audit log. At 10,000 decisions/day, after 6 months that is 1.8 million audit entries with broken reconstruction links. A regulator asking to reconstruct any of them gets "trace not found." The fix costs 1 day of engineering (snapshot 5-6 fields from the trace into the audit entry). The risk of not fixing it: losing the ability to comply with Article 12 reconstruction requirements.

### Technology Choice Justifications

| Choice | Alternatives Considered | Why This One | Why NOT the Others |
|---|---|---|---|
| PostgreSQL append-only table | TimescaleDB, InfluxDB, Kafka log, dedicated audit DB (Oracle Audit Vault) | Same DB as LangGraph checkpointer = atomic transactions possible. No new infrastructure. Team already knows PostgreSQL. | TimescaleDB adds hypertable complexity for a write-heavy, rarely-queried table (report generation is batch, not real-time). InfluxDB is for time-series metrics, not structured audit records. Kafka log is append-only but lacks SQL query capability for compliance reports. Oracle Audit Vault costs EUR 17,500/year/core -- 3.2x the entire logging budget for a feature PostgreSQL handles natively. |
| `REVOKE UPDATE, DELETE` + hash chain | Application-level immutability (ORM checks), blockchain-backed audit log, Write-Once-Read-Many (WORM) storage | Database-level REVOKE is enforceable regardless of application code bugs. Hash chain adds tamper evidence. Both are zero-cost (no additional infrastructure). | Application-level checks are bypassable by any code path that uses raw SQL. Blockchain is theater -- a private chain with one writer has the same trust model as a hash chain, at 1000x the infrastructure cost (estimated EUR 8,000-15,000/year for a managed blockchain node). WORM storage (Azure Immutable Blob) works for archival but cannot be queried with SQL for report generation. |
| Separate PII vault table | Column-level encryption in audit_log, tokenization service (e.g., Vault by HashiCorp), no PII storage (hash only) | Allows GDPR deletion without breaking audit chain. AES-256-GCM encryption at rest. Key rotation via key_id field. | Column-level encryption in an append-only table means you cannot re-encrypt on key rotation without rewriting rows (violates immutability). HashiCorp Vault tokenization adds a network hop per audit write (3-8ms latency) and a new infrastructure dependency (EUR 1,200-3,600/year for managed Vault). Hash-only loses the ability to reconstruct the original query for Article 12 compliance -- you need the plaintext somewhere, just not in the immutable log. |
| Monthly table partitioning | No partitioning (single table), daily partitioning, yearly partitioning | 10,000 entries/day x 365 = 3.65M rows/year. Monthly partitions (~300K rows each) keep queries fast. Archive old partitions to cold storage. Partition pruning makes date-range report queries O(months) not O(total_rows). | No partitioning hits performance wall at ~10M rows (year 3). Daily partitioning creates 365 partitions/year -- too many for PostgreSQL's partition management overhead. Yearly partitioning (3.65M rows per partition) is too coarse for efficient date-range queries in compliance reports. |

### Metrics That Matter to a CTO

| Technical Metric | Business Translation | Who Cares |
|---|---|---|
| Audit write latency: ~2ms per INSERT (PostgreSQL) | Zero perceptible impact on user experience -- the compliance logger adds 2ms to an 800ms RAG query | CTO: "Will compliance slow down the AI?" No. 0.25% overhead. |
| Storage growth: 50MB/day at 10K decisions/day | EUR 25/year for hot storage. EUR 0.44/year for cold archive per year of data. Total 10-year storage: ~EUR 300. | CFO: "What does compliance storage cost?" Less than one hour of a developer's time. |
| Report generation time: <10 minutes for quarterly report | Regulator asks for Q3 data, you generate it while they wait. Without this: 3 engineers x 2 weeks = EUR 6,000 per audit query. | Legal: "How fast can we respond to a regulatory audit?" 10 minutes, not 2 weeks. |
| Hash chain verification time: O(n), ~30 seconds for 1M entries | Prove to a regulator that no audit entry has been tampered with in under a minute | Compliance officer: "Can we prove the logs weren't altered?" Yes, mathematically. |
| 648:1 cost ratio (EUR 5,400/year vs EUR 3,500,000 fine) | For every EUR 1 spent on compliance logging, you avoid EUR 648 in potential fines | Board: "Is this worth the investment?" The question is whether you can afford NOT to invest. |

### Silent Failure Risks

1. **Langfuse trace reconciliation never runs.** The `InMemoryFallbackStore` in `langfuse_handler.py` accumulates traces when Langfuse is down. If `reconcile_fallback()` is never called (no cron job, no health check trigger), traces accumulate in memory indefinitely, then are lost on process restart. Blast radius: every trace during every Langfuse outage is permanently lost. Detection gap: no monitoring on fallback store size.

2. **Audit log and checkpointer drift silently.** If someone modifies the checkpointer to use a different connection pool (or a future LangGraph update changes the connection management), the atomic transaction guarantee breaks silently. No test currently verifies that both writes use the same transaction. Blast radius: every decision during a crash window has a compliance gap. Detection gap: only discoverable during an actual crash + regulatory audit.

3. **Document version garbage collection deletes referenced chunks.** A future cleanup job that removes old Qdrant points could delete chunks referenced by audit entries within the retention window. Blast radius: all audit entries referencing those chunks become non-reconstructible. Detection gap: only discoverable when a specific old decision is queried months later.

4. **Clock skew between audit log and Langfuse timestamps.** If the API server and Langfuse server have different NTP configurations, audit log `created_at` and Langfuse trace timestamps diverge. A regulator comparing the two sees inconsistencies. Blast radius: every audit entry. Detection gap: only visible during manual cross-referencing.

### Missing Angles

1. **No mention of audit log access control.** Who can READ the audit log? The compliance report endpoint exposes audit entries. Without RBAC on audit log queries, any authenticated user could see what other users queried. The audit log itself becomes a confidentiality leak.

2. **No mention of audit log for audit log access.** Meta-auditing: if a compliance officer accesses the audit log, is THAT access logged? Recursive, but required by some interpretations of Article 14 (human oversight must itself be auditable).

3. **No mention of data residency.** LogiCore is a Polish company. Under RODO, PII must stay within the EU (or adequate jurisdictions). If Azure Blob Archive for cold storage is configured to a non-EU region, the archival itself violates RODO. Must enforce `westeurope` or `northeurope` Azure regions.

4. **No mention of audit log backup strategy.** An immutable audit log that is not backed up is a single point of failure. PostgreSQL WAL archiving + periodic base backups to a separate storage account (different from the primary) should be specified.

5. **No test for concurrent audit writes.** At 10,000 decisions/day (peak: ~20/second during business hours), the audit logger must handle concurrent INSERTs without deadlocking or losing entries. The hash chain ordering under concurrency needs careful design (sequence generator + advisory lock, or accept unordered hashes).

</details>

<details>
<summary>Cross-Phase Failure Cascades (full report)</summary>

## Cross-Phase Cascade Analysis for Phase 8

### Dependency Map

```
Phase 1 (RBAC + RAG) ───────────────────────┐
  - UserContext (user_id, clearance, depts)   |
  - Retrieved chunk IDs from Qdrant           |
                                              v
Phase 3 (Multi-Agent) ──────────────────> PHASE 8 (Regulatory Shield)
  - AuditGraphState (run_id, status)          |  - Audit log entries
  - LangGraph checkpointer (PostgreSQL)       |  - Data lineage records
  - HITL approval decisions                   |  - Compliance reports
                                              |  - Bias detection results
Phase 4 (Trust Layer / LLMOps) ──────────┘   |
  - Langfuse trace IDs                        |
  - Cost tracker data (per-query EUR)         |
  - TraceRecord model                         |
                                              v
Phase 7 (Resilience) ──────────────────> Downstream Consumers
  - is_degraded flag                          |
  - ProviderChainResponse metadata            |
  - Which provider served (fallback info)     |
                                              v
                                    Phase 9 (Fleet Guardian)
                                      - Real-time decisions need audit logging
                                      - 10K GPS pings/day, only anomalies logged
                                    Phase 10 (LLM Firewall)
                                      - Security events feed audit log
                                      - Blocked attacks = audit entries
                                    Phase 12 (Full Stack Demo)
                                      - End-to-end compliance report
                                      - Regulator scenario walkthrough
```

### Cascade Scenarios (ranked by total EUR impact)

| Trigger | Path | End Impact | EUR Cost | Mitigation |
|---|---|---|---|---|
| PostgreSQL connection pool exhaustion | Phase 3 audit workflow starts -> checkpointer acquires conn -> audit logger needs conn from same pool -> pool exhausted during peak (20 concurrent audits) -> deadlock | All audit workflows freeze. No decisions processed. HITL queue stalls. | EUR 12,000-45,000/day in delayed invoice processing (15 invoices/hour x EUR 45/hour clerk cost x 8 hours) | Separate connection for audit writes within the same transaction (not a separate pool). Max pool size >= 2x max concurrent workflows. |
| Langfuse outage during audit workflow | Phase 4 LangfuseHandler falls back to InMemoryFallbackStore -> Process restarts during outage -> All pending traces lost -> Audit log entries have trace_ids but no corresponding Langfuse data | 6-month-old decisions cannot be fully reconstructed. Compliance report has gaps. | EUR 50,000-500,000 (Article 12 violation) | Replace InMemoryFallbackStore with PostgreSQL-backed store in same DB as audit log. Snapshot critical trace fields into audit entry. |
| Qdrant chunk overwrite on re-ingestion | Phase 1 ingestion pipeline re-ingests document -> overwrites Qdrant point IDs (no versioning) -> Audit log references old point IDs -> Old chunks no longer exist | Cannot reconstruct "what the AI saw" for any decision made before re-ingestion. Lineage chain broken. | EUR 100,000-3,500,000 (cannot satisfy Article 12 reconstruction) | Version-tagged chunk IDs. Re-ingestion creates new points; old points preserved with TTL matching audit retention. |
| Phase 7 degraded mode + audit logger failure | Azure goes down -> ProviderChain falls back to Ollama -> is_degraded=True -> Audit logger attempts write in same transaction -> Ollama response is lower quality -> Audit entry records degraded response but no flag | Financial decisions made on degraded AI quality are audited as normal. No flag for reviewer. | EUR 500-5,000 per undetected degraded decision (wrong freight rate applied) | Audit entry MUST include `is_degraded` boolean and `provider_name` from ProviderChainResponse. |
| RBAC bypass through audit log query | Phase 1 RBAC filters Qdrant queries -> Clearance-2 user cannot see clearance-4 docs -> BUT audit log stores ALL queries -> User queries audit log API -> Sees clearance-4 user's queries about executive compensation | Confidential information leaked via audit log metadata (what was queried, even if not the response content). | EUR 10,000-100,000 (GDPR + internal confidentiality breach) | RBAC on audit log API: users can only see their own audit entries. Compliance officers get full access via separate role. |
| Phase 5 judge bias drift + audit logging | Phase 5 drift detector fires RED alert (>5% quality drift) -> Quality gate halts -> But existing audit entries were logged during the drift period -> Compliance report includes decisions made with degraded quality | Regulator sees decisions made during quality regression. No flag distinguishing them from normal-quality decisions. | EUR 20,000-200,000 (regulatory credibility damage) | Cross-reference drift alerts with audit entries. Flag entries in the drift window. Include drift status in compliance report. |
| Hash chain breaks under concurrent writes | Two audit entries written simultaneously -> Both read the same prev_entry_hash -> Both write with the same prev hash -> Chain forks -> Verification fails | Hash chain integrity compromised. Tamper evidence is unreliable. | EUR 0 direct, but destroys the trust model for immutability proof | Serialize hash chain writes with PostgreSQL advisory lock or sequence-gated INSERT. Accept ~1ms serialization overhead at 20 writes/second. |

### Security Boundary Gaps

1. **Audit log API inherits Phase 1 RBAC but needs finer granularity.** Phase 1 RBAC operates on clearance levels (1-4) and departments. Audit log access needs a different model: users see their own entries, managers see their team's entries, compliance officers see all entries. The current RBAC model does not support "own entries only" -- it is document-centric, not user-centric. A new `audit_log_access` permission model is needed.

2. **Semantic cache (Phase 4) could serve stale compliance data.** If a user queries "compliance report for Q3" and the cache serves a stale version from last week, the user sees outdated compliance data. Compliance endpoints MUST bypass the semantic cache entirely -- stale compliance data is worse than slow compliance data.

3. **Phase 3 HITL approval is not linked to audit log entry.** The `hitl_gate_node` in `audit_graph.py` currently returns `{"status": "approved"}` but does not record WHO approved, WHEN, or with what notes. The audit log entry needs `hitl_approver_id`, `hitl_approved_at`, and `hitl_notes` -- all from the HITL gateway state, which currently does not capture them.

4. **Phase 7 ProviderChain metadata is not propagated to audit context.** `ProviderChainResponse` includes `provider_name`, `is_fallback`, `is_cache`, `is_degraded`, and `disclaimer`. None of these are currently passed to the audit logger. A decision served by Ollama during an Azure outage should be audited differently from a decision served by GPT-5.2 under normal conditions.

### Degraded Mode Governance

| Dependency State | This Phase Behavior | Recommended Action |
|---|---|---|
| PostgreSQL down | Audit logger cannot write. Checkpoint also fails (same DB). Entire workflow halts. | Accept the halt -- a workflow without audit logging MUST NOT proceed. Queue incoming requests in Redis with 5-minute TTL. Alert ops immediately. |
| Langfuse down | Audit entry written without Langfuse trace ID. InMemoryFallbackStore accumulates traces. | Write audit entry with `langfuse_trace_id=NULL` and `langfuse_status='pending_reconciliation'`. Snapshot critical trace data into audit entry. |
| Qdrant down | RAG retrieval fails -> no chunks retrieved -> audit entry has empty `retrieved_chunk_ids` | Log the failure explicitly: `retrieved_chunk_ids=[]` with metadata `{"retrieval_error": "qdrant_unavailable"}`. Do NOT skip the audit entry. |
| Phase 7 all providers down, cache served | Response served from cache with disclaimer. `is_degraded=True`. | Audit entry with `is_degraded=True`, `provider_name='cache'`, `disclaimer` text. Compliance report flags these entries. |
| Phase 5 quality drift RED alert | Quality below threshold. Decisions may be unreliable. | Audit entries during drift period flagged with `quality_drift_alert=True`. Compliance report includes separate section for drift-period decisions. |

</details>

<details>
<summary>CTO Decision Framework (full report)</summary>

## CTO Decision Framework for Phase 8

### Executive Summary

EU AI Act compliance logging for high-risk AI decisions is not optional -- it is a legal requirement with fines up to 7% of global turnover (EUR 3.5M for a EUR 50M company). The build cost is 3-4 developer-weeks. The annual operational cost is EUR 5,400. The ROI is immediate: the first time a regulator asks to reconstruct a decision, you either generate a report in 10 minutes or spend EUR 6,000 in engineering time per query (at 10 queries/year = EUR 60,000 saved). Break-even: month 1.

### Build vs Buy Analysis

| Component | Build Cost | SaaS Alternative | SaaS Cost | Recommendation |
|---|---|---|---|---|
| Immutable audit log | 1 week (PostgreSQL table + REVOKE + hash chain) | Splunk Audit Trail, Datadog Compliance Logs, IBM OpenPages | EUR 12,000-48,000/year (Splunk: EUR 2,000/GB/year at ~18GB/year = EUR 36,000; Datadog: EUR 12,000/year for compliance tier; IBM OpenPages: EUR 48,000/year) | **BUILD.** PostgreSQL handles this natively at EUR 25/year storage cost. SaaS solutions cost 200-900x more and introduce data residency complexity (must verify EU hosting). The audit log MUST be in the same database as the LangGraph checkpointer for atomic transactions -- no SaaS product supports this. |
| Data lineage tracking | 1 week (PostgreSQL tables + Qdrant version-tagged IDs) | Apache Atlas, Atlan, Collibra | EUR 24,000-120,000/year (Atlan: EUR 24,000/year starter; Collibra: EUR 60,000-120,000/year enterprise) | **BUILD.** Lineage is simple: document version -> chunk -> embedding -> retrieval event. Four PostgreSQL tables. No graph database needed at this scale. SaaS lineage tools are designed for enterprise data lakes with 10,000+ tables -- overkill for 4 tables tracking document versions. |
| Compliance report generator | 3 days (SQL queries + Jinja2 template) | OneTrust AI Governance, TrustArc, Vanta | EUR 18,000-72,000/year (OneTrust: EUR 36,000/year; TrustArc: EUR 18,000/year; Vanta: EUR 24,000/year) | **BUILD.** The report is a SQL query over the audit log + a template. No ML, no complex logic. SaaS tools add value for companies with 50+ AI systems across multiple teams. For a single AI system, they are overhead. Switch to SaaS when LogiCore scales to 5+ independent AI systems. |
| Bias detection | 2 days (extend Phase 5 JudgeBiasResult + scheduled job) | Holistic AI, Credo AI, Arthur AI | EUR 36,000-96,000/year (Holistic AI: EUR 48,000/year; Credo AI: EUR 36,000/year; Arthur AI: EUR 96,000/year) | **BUILD.** Phase 5 already has `JudgeBiasResult` with position, verbosity, and self-preference bias detection. Phase 8 adds a scheduled job that runs this weekly and stores results. 2 days of work vs EUR 36,000/year minimum. Switch to SaaS only if you need bias detection across 10+ model families with regulatory reporting templates you do not want to maintain. |
| PII vault | 2 days (PostgreSQL table + AES-256-GCM encryption) | HashiCorp Vault, AWS KMS + DynamoDB, Azure Key Vault | EUR 1,200-3,600/year (HashiCorp Cloud: EUR 1,200/year starter; AWS KMS: EUR 3,600/year at 10K keys) | **CONSIDER BUY for key management only.** Build the PII vault table (simple PostgreSQL). Use Azure Key Vault (EUR 0.03/10K operations = EUR 10/year at LogiCore scale) for key management. Do not build your own key rotation -- it is one of the few areas where SaaS is both cheaper and more secure than DIY. |

### Scale Ceiling

| Component | Current Limit | First Bottleneck | Migration Path |
|---|---|---|---|
| Audit log (PostgreSQL) | ~50M rows per partition before query degradation | Sequential scan on unindexed metadata JSONB column during compliance report generation | Add GIN index on metadata JSONB. Partition by month (already recommended). At 100M+ rows, consider TimescaleDB for automatic partition management. |
| Hash chain verification | O(n) = ~30 seconds at 1M entries | Full-chain verification at 36.5M entries (10 years) takes ~18 minutes | Checkpoint hashes: store a "known-good" hash at monthly boundaries. Verification only needs to check from last checkpoint. Reduces O(n) to O(entries_since_last_checkpoint). |
| Data lineage (PostgreSQL) | Millions of chunk_versions rows | JOIN between document_versions and chunk_versions on large tables | Index on document_version_id (foreign key). Materialized view for frequently accessed lineage chains. |
| Compliance report generation | ~10 minutes for 1 quarter (900K entries) | Sequential read of 3.65M entries for annual report | Pre-aggregate monthly summaries. Annual report = 12 monthly summaries + cross-referencing. |
| Qdrant versioned chunks | Doubles storage for each versioned document | At 10,000 documents with avg 3 versions = 30,000 effective documents | Qdrant sharding (multi-node) at 10M+ vectors. Or: move archived versions to cold collection with lower replication factor. |

### Team Requirements

| Component | Skill Level | Bus Factor | Documentation Quality |
|---|---|---|---|
| PostgreSQL audit table + REVOKE | Junior (SQL + role management) | Low risk -- standard PostgreSQL patterns | High -- well-documented in PostgreSQL docs |
| Hash chain implementation | Mid-level (cryptographic hashing, concurrency) | Medium risk -- custom code, needs test coverage | Medium -- design doc needed, not a standard pattern |
| Atomic transaction with checkpointer | Senior (asyncpg internals, LangGraph checkpointer API) | High risk -- deep integration with LangGraph internals | Low -- LangGraph checkpointer docs are sparse on connection sharing |
| PII vault + encryption | Senior (AES-256-GCM, key rotation, GDPR compliance) | High risk -- encryption bugs = data loss or compliance failure | Medium -- Azure Key Vault docs are good, integration is custom |
| Compliance report generator | Junior (SQL queries, Jinja2 templates) | Low risk -- straightforward query + template | High -- output format is well-defined by phase spec |
| Bias detection (scheduled) | Mid-level (statistics, Phase 5 codebase familiarity) | Medium risk -- reuses Phase 5 patterns | Medium -- Phase 5 tracker documents the bias detection approach |

### Compliance Gaps (what legal would flag)

1. **No Data Protection Impact Assessment (DPIA) mentioned.** Under RODO Article 35, processing PII at scale (which audit logging does) requires a DPIA BEFORE implementation. The phase spec jumps to implementation without mentioning the DPIA. Legal will ask for it.

2. **No data processing agreement (DPA) for Azure Key Vault.** If using Azure for key management, a DPA must be in place. Microsoft provides standard DPAs, but they must be explicitly accepted and filed.

3. **Retention periods not aligned with Polish regulatory requirements.** The spec mentions "10 years minimum (financial), 5 years (other)." Polish tax law (Ordynacja podatkowa, Art. 86) requires 5-year retention for tax-related documents. The EU AI Act's Article 12 does not specify a retention period -- it says "for the duration of the AI system's use and for an appropriate period thereafter." Legal needs to define "appropriate period" for LogiCore's specific use cases.

4. **No mention of right-to-explanation (GDPR Article 22).** When an AI system makes automated decisions affecting individuals (e.g., flagging an employee's expense report), GDPR Article 22 gives the individual the right to an explanation. The audit log must support generating human-readable explanations, not just technical trace data.

5. **No cross-border data transfer assessment.** If any component of the audit trail (Langfuse traces, Azure Key Vault keys, cold storage archives) resides outside the EU, a Transfer Impact Assessment (TIA) is required under RODO. Must verify all Azure regions are `westeurope` or `northeurope`.

### ROI Model

| Line Item | Month 1 | Monthly (2-12) | Year 1 Total | Year 2+ Annual |
|---|---|---|---|---|
| **Costs** | | | | |
| Development (3-4 dev-weeks x EUR 6,000/week) | EUR 24,000 | EUR 0 | EUR 24,000 | EUR 0 |
| Infrastructure (PostgreSQL storage + Azure Key Vault) | EUR 5 | EUR 5 | EUR 60 | EUR 60 |
| Logging compute (Langfuse + audit writes) | EUR 450 | EUR 450 | EUR 5,400 | EUR 5,400 |
| Maintenance (4 hours/month senior dev) | EUR 0 | EUR 240 | EUR 2,640 | EUR 2,880 |
| **Total costs** | **EUR 24,455** | **EUR 695** | **EUR 32,100** | **EUR 8,340** |
| | | | | |
| **Savings** | | | | |
| Audit response time (10 queries/year x EUR 6,000 each) | EUR 5,000 | EUR 5,000 | EUR 60,000 | EUR 60,000 |
| Fine avoidance (expected value: 2% probability x EUR 3.5M) | EUR 5,833 | EUR 5,833 | EUR 70,000 | EUR 70,000 |
| Compliance officer time (20 hours/month x EUR 80/hour) | EUR 1,600 | EUR 1,600 | EUR 19,200 | EUR 19,200 |
| **Total savings** | **EUR 12,433** | **EUR 12,433** | **EUR 149,200** | **EUR 149,200** |
| | | | | |
| **Net** | **-EUR 12,022** | **+EUR 11,738** | **+EUR 117,100** | **+EUR 140,860** |

**Break-even: Month 3.** Development cost is recouped by month 3 through audit response time savings and compliance officer productivity gains alone -- before counting fine avoidance.

</details>

<details>
<summary>Safety & Adversarial Analysis (full report)</summary>

## Safety & Adversarial Analysis for Phase 8

### Attack Surface Map

```
                    [Audit Log API]
                         |
            GET /compliance/audit-log
            GET /compliance/report
            GET /compliance/lineage/{doc_id}
                         |
                    +---------+
                    | Phase 8 |
                    | Audit   |
                    | Logger  |
                    +---------+
                   /     |     \
                  /      |      \
    [PostgreSQL]  [Langfuse]  [Qdrant]
    audit_log     trace data   chunk versions
    pii_vault     (trace IDs)  (lineage)
    doc_versions
    chunk_versions
         |
    +----------+
    | Hash     |  <-- ATTACK POINT 1: Break the chain
    | Chain    |
    +----------+
         |
    +----------+
    | PII      |  <-- ATTACK POINT 2: Extract encrypted PII
    | Vault    |
    +----------+

ATTACK POINT 3: Compliance report manipulation
  - Inject false entries to hide real discrepancies
  - Exclude entries from report via parameter manipulation

ATTACK POINT 4: Timing side-channel on audit queries
  - Determine existence of high-clearance entries via response time

ATTACK POINT 5: Langfuse trace poisoning
  - Modify Langfuse traces to contradict audit log entries

ATTACK POINT 6: Concurrent hash chain race condition
  - Fork the chain via simultaneous writes
```

### Critical Vulnerabilities (ranked by impact x exploitability)

| # | Attack | Vector | Impact | Exploitability | Mitigation |
|---|---|---|---|---|---|
| 1 | Audit log entry injection via SQL injection in metadata JSONB | Craft a query that injects malicious JSON into the `metadata` field. If audit logger does not parameterize the JSONB insert, attacker controls audit content. | CRITICAL -- false audit entries undermine the entire compliance system. A fabricated entry could hide a real discrepancy or create a false one. | Medium -- requires finding an unparameterized SQL path. Current codebase uses asyncpg with `$N` params, but metadata JSONB construction may use string formatting. | Verify ALL audit log INSERTs use parameterized queries for EVERY field including JSONB. Test with `'; DROP TABLE audit_log; --` in metadata values. |
| 2 | Hash chain fork via race condition | Two simultaneous audit writes both read the same `prev_entry_hash`, both write entries with the same predecessor. Chain forks. Subsequent verification fails -- but the attacker can exploit the fork to insert entries that appear valid on one branch. | HIGH -- destroys tamper evidence. The hash chain is the mathematical proof of non-tampering; a fork makes it unreliable. | High -- achievable at peak load (20 concurrent writes). No synchronization mechanism specified. | PostgreSQL advisory lock (`pg_advisory_xact_lock`) on a fixed lock ID before reading prev_hash and writing new entry. Serializes hash chain writes. ~1ms overhead per write. |
| 3 | PII extraction via audit log API | Attacker with clearance-1 access queries the audit log API. Even without raw query text (hashed), the `retrieved_chunk_ids` reveal which documents were accessed. Combined with document titles (available via lineage API), attacker can infer what high-clearance users queried. | HIGH -- information leakage via metadata, even without PII plaintext. Knowing that the CFO queried "executive compensation" chunks is itself sensitive. | High -- requires only authenticated API access. No additional privilege needed if audit API lacks its own RBAC. | RBAC on audit log API: clearance-1 sees only their own entries. Compliance role (separate from clearance levels) required for full access. Chunk IDs in audit entries do not resolve to content without separate authorization. |
| 4 | Langfuse trace manipulation | Attacker with access to Langfuse's PostgreSQL database modifies trace data. Audit log entry references trace ID. When regulator asks for reconstruction, the Langfuse trace shows different data than what actually happened. | HIGH -- creates plausible deniability for AI decisions. "The trace shows the AI said X" but it actually said Y. | Low -- requires database access to Langfuse's PostgreSQL. But if Langfuse runs in the same Docker Compose with shared network, lateral movement from a compromised container is feasible. | Snapshot critical trace data (response_hash, token counts, model version) in the audit log entry itself. Cross-reference with Langfuse trace. Discrepancy = tampering alert. Run Langfuse in isolated network segment. |
| 5 | Compliance report parameter manipulation | Attacker (or compromised admin) modifies the `from`/`to` date parameters in the compliance report API to exclude a specific date range containing problematic decisions. | MEDIUM -- report omits entries, regulator sees incomplete data. | Medium -- requires authenticated access to report API. But compliance officers may share report URLs. | Log every report generation request in the audit log itself (meta-auditing). Report includes hash of all included entry IDs. Regulator can verify completeness by comparing entry count in report vs direct database count for the same date range. |
| 6 | Denial of service via expensive compliance report | Attacker requests a compliance report for a 10-year date range. Query scans 36.5M rows. PostgreSQL becomes unresponsive. All audit writes fail. | MEDIUM -- temporary unavailability, not data loss. But if audit writes fail during the DoS, compliance gaps are created. | High -- single API call. No rate limiting on compliance endpoints mentioned in spec. | Rate limit compliance report generation to 1 per minute per user. Maximum date range: 1 year per request. For multi-year reports, queue as background job. Separate read replica for report queries to protect write path. |
| 7 | Encryption key extraction from PII vault | If AES-256-GCM encryption key is stored in application memory (environment variable), a memory dump or core dump leaks the key. All PII vault entries decryptable. | HIGH -- full PII exposure for every audit entry. | Low -- requires server-level access or memory dump capability. | Use Azure Key Vault for key management. Application never holds the raw key -- calls Key Vault API for encrypt/decrypt operations. Key is HSM-backed, never exportable. Cost: EUR 10/year at LogiCore scale. |

### Red Team Test Cases (implementable as pytest)

**Test 1: SQL Injection in Audit Metadata**
```python
def test_audit_metadata_sql_injection_blocked():
    """Malicious JSON in metadata field cannot execute SQL."""
    # Setup: Create audit entry with metadata containing SQL injection
    malicious_metadata = {
        "note": "'; DROP TABLE audit_log; --",
        "extra": "\" OR 1=1; UPDATE audit_log SET response_text='hacked'"
    }
    # Action: Insert audit entry with malicious metadata
    entry = await audit_logger.write(
        user_id="attacker",
        query_text="normal query",
        metadata=malicious_metadata,
    )
    # Assert: Entry exists, table intact, metadata stored as literal string
    assert await audit_logger.count() > 0
    stored = await audit_logger.get(entry.id)
    assert stored.metadata["note"] == "'; DROP TABLE audit_log; --"
```

**Test 2: RBAC on Audit Log API**
```python
def test_clearance_1_user_cannot_see_clearance_4_audit_entries():
    """Low-clearance user sees only their own audit entries."""
    # Setup: Create entries for clearance-1 and clearance-4 users
    await create_audit_entry(user_id="max.weber", clearance=1)
    await create_audit_entry(user_id="eva.richter", clearance=4)
    # Action: Query audit log as max.weber
    response = await client.get(
        "/api/v1/compliance/audit-log",
        headers={"X-User-ID": "max.weber"}
    )
    # Assert: Only max.weber's entries returned
    entries = response.json()["entries"]
    assert all(e["user_id"] == "max.weber" for e in entries)
```

**Test 3: Hash Chain Integrity Under Concurrent Writes**
```python
def test_hash_chain_integrity_under_concurrency():
    """50 concurrent audit writes produce a valid, linear hash chain."""
    # Setup: Clean audit log
    # Action: 50 asyncio.gather audit writes
    tasks = [audit_logger.write(user_id=f"user-{i}", ...) for i in range(50)]
    await asyncio.gather(*tasks)
    # Assert: Hash chain is valid (each entry's prev_hash matches predecessor's hash)
    entries = await audit_logger.get_all(order_by="created_at")
    for i in range(1, len(entries)):
        expected_prev = entries[i-1].entry_hash
        assert entries[i].prev_entry_hash == expected_prev
```

**Test 4: GDPR Erasure Does Not Break Audit Chain**
```python
def test_gdpr_erasure_preserves_hash_chain():
    """Deleting PII vault entry does not affect audit log hash chain."""
    # Setup: Create 5 audit entries with PII vault entries
    # Action: Delete PII vault entry for entry #3
    await pii_vault.delete(audit_entry_id=entries[2].id)
    # Assert: Audit log hash chain still valid
    assert await audit_logger.verify_hash_chain() is True
    # Assert: Entry #3 still exists in audit log (hash, chunk IDs, model version)
    entry_3 = await audit_logger.get(entries[2].id)
    assert entry_3 is not None
    assert entry_3.query_hash is not None  # hash preserved
    # Assert: PII vault entry is gone
    pii = await pii_vault.get(audit_entry_id=entries[2].id)
    assert pii is None or pii.deleted_at is not None
```

**Test 5: Compliance Report Completeness Verification**
```python
def test_compliance_report_includes_all_entries_for_period():
    """Report cannot silently exclude entries."""
    # Setup: Create 100 audit entries for March 2026
    for i in range(100):
        await create_audit_entry(created_at=datetime(2026, 3, i % 28 + 1))
    # Action: Generate compliance report for March 2026
    report = await report_generator.generate(
        period_start=datetime(2026, 3, 1),
        period_end=datetime(2026, 3, 31),
    )
    # Assert: Report contains exactly 100 entries
    assert report.total_entries == 100
    # Assert: Report includes verification hash
    assert report.entry_count_hash == sha256(f"100:{report.period_start}:{report.period_end}")
```

### Defense-in-Depth Recommendations

| Layer | Current | Recommended | Priority |
|---|---|---|---|
| Database access control | `REVOKE UPDATE, DELETE` on application role | Add: separate `audit_reader` role for report queries (SELECT only on audit_log, no access to pii_vault). Separate `compliance_officer` role for full access including PII vault. | HIGH |
| Tamper evidence | None (REVOKE is preventive, not detective) | SHA-256 hash chain linking entries. Monthly hash checkpoints for efficient verification. Cross-hash with Langfuse snapshot data. | HIGH |
| PII protection | Raw query text in audit_log (plaintext) | PII vault with AES-256-GCM encryption. Azure Key Vault for key management. Query hash in audit_log. | HIGH |
| API access control | Phase 1 RBAC (clearance + departments) | Audit-specific RBAC: own entries (default), team entries (manager role), all entries (compliance role). Rate limiting on report generation. | HIGH |
| Langfuse dependency | Trace ID as sole reconstruction link | Snapshot critical fields (model version, tokens, cost, response hash) in audit entry. Langfuse trace is supplementary, not required. | MEDIUM |
| Backup integrity | Not specified | WAL archiving to separate storage account. Weekly integrity check (restore from backup, verify hash chain). | MEDIUM |
| Network isolation | Langfuse in same Docker Compose network | Isolate Langfuse in separate network segment. Restrict database access to application service only. | LOW |
| Concurrent write safety | Not specified | PostgreSQL advisory lock for hash chain serialization. Sequence generator for entry ordering. | HIGH |

### Monitoring Gaps

1. **No alert on hash chain break.** If a chain verification fails (indicating tampering or race condition), there is no alerting mechanism. A scheduled job should verify the chain daily and alert immediately on failure.

2. **No monitoring on audit write latency.** If audit writes slow down (indicating PostgreSQL degradation), the system silently degrades. Monitor p95 audit write latency and alert if it exceeds 50ms (10x expected baseline).

3. **No monitoring on PII vault growth vs audit log growth.** If audit entries are created without corresponding PII vault entries (implementation bug), PII is logged in the wrong table or not at all. The ratio should be ~1:1 for PII-containing queries. Alert if it diverges by >10%.

4. **No monitoring on Langfuse trace reconciliation queue depth.** If the InMemoryFallbackStore (or PostgreSQL-backed replacement) grows beyond 1,000 entries, Langfuse has been down too long. Alert at 100 entries, escalate at 1,000.

5. **No monitoring on compliance report generation time.** If a quarterly report takes >30 minutes (3x expected), table partitioning or indexing needs attention. Monitor and alert.

6. **No monitoring on concurrent audit write contention.** Advisory lock wait time should be <5ms at normal load. If it exceeds 50ms, concurrent write volume exceeds design capacity. Alert and investigate.

</details>
