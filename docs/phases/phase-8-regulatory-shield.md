# Phase 8: "The Regulatory Shield" — EU AI Act Compliance

## Business Problem

The EU AI Act enforcement for "High-Risk" AI systems is approaching. Companies using AI for financial decisions, HR screening, or safety-critical logistics face mandatory compliance with Articles 11 (Technical Documentation), 12 (Record-Keeping), and 14 (Human Oversight). Non-compliance means fines up to 7% of global turnover.

**CTO pain**: "Legal says we need full audit trails for every AI decision. If a regulator asks 'Why did the AI flag this invoice 6 months ago?' we need to reconstruct the exact system state."

## Real-World Scenario: LogiCore Transport

**Feature: Compliance Report Generator**

Six months from now, a Polish regulator audits LogiCore Transport's AI system. The question: "On September 15, 2026, your AI flagged invoice INV-2024-0847 as a billing discrepancy. Reconstruct exactly what happened."

**Without Phase 8**: "Uh... the AI found something? We think it was an overcharge. Not sure which model version was running. The logs got rotated."

**With Phase 8**: Pull audit log entry #4,721:
- **Who asked**: Anna Schmidt (user-logistics-01, clearance 2)
- **What was asked**: "Audit invoice INV-2024-0847 against contract CTR-2024-001"
- **What AI saw**: Retrieved chunks: contract-CTR-2024-001-v2.3-chunk-47 (rate clause), contract-CTR-2024-001-v2.3-chunk-48 (penalty clause)
- **Which model**: gpt-5.2-2026-0201, deployment: logicore-prod-east
- **What it said**: "Discrepancy detected: billed €0.52/kg vs contracted €0.45/kg. Overcharge: €588."
- **Who approved**: Martin Lang (user-cfo-01), approved 2026-09-15T14:23:07Z, note: "Verified. Dispute with vendor."
- **Full trace**: Langfuse trace ID → click to see exact token-by-token execution

**Data lineage demo**: Click on "contract-CTR-2024-001-v2.3-chunk-47" → shows: Source PDF uploaded 2024-06-01 → re-ingested 2024-09-15 (v2.3, SHA-256: abc123...) → chunked by semantic splitter → embedded with text-embedding-3-small → Qdrant point ID q-47-v2 → retrieved in audit run #4,721.

**The immutability test**: Try `UPDATE audit_log SET response_text = 'nothing wrong'` → permission denied. Even a DBA with the application role can't tamper with the log.

### Tech → Business Translation

| Technical Concept | What the User Sees | Why It Matters |
|---|---|---|
| Immutable audit log (append-only) | Tamper-proof record of every AI decision | Regulator trusts the data — nobody could have altered it |
| Data lineage | "This answer came from contract v2.3, clause 47, uploaded June 1" | Full traceability from answer → source document version |
| Langfuse trace linking | Click to see the exact AI execution, step by step | Reconstruct any past decision with full context |
| Article 12 compliance | One-click compliance report for any date range | Turn a 3-week audit into a 10-minute report generation |
| Database-level immutability | UPDATE/DELETE revoked at role level | Even compromised app code can't tamper with logs |

## Architecture

```
Every AI Decision → Compliance Logger
  ├── Immutable Audit Log (PostgreSQL + append-only)
  │     ├── Timestamp
  │     ├── User ID (who triggered)
  │     ├── Query (exact input)
  │     ├── Retrieved Chunks (IDs + versions)
  │     ├── Model Version (deployment ID + checkpoint)
  │     ├── Response (exact output)
  │     ├── HITL Approver ID (if applicable)
  │     └── Langfuse Trace ID (link to full trace)
  ├── Data Lineage Graph
  │     └── Document Version → Chunk Version → Embedding Version
  └── Bias Detection (scheduled)
        └── Statistical fairness checks on routing decisions
```

**Key design decisions**:
- Append-only audit table — no UPDATE, no DELETE, ever
- Every log entry links to Langfuse trace for full reconstruction
- Document versioning: re-ingested docs get new version, old chunks preserved
- Compliance report generator pulls from audit log + Langfuse API

## Implementation Guide

### Prerequisites
- Phases 1-3 complete (RAG + agents + observability)
- PostgreSQL running
- Understanding of EU AI Act Articles 11, 12, 14

### Files to Create/Modify

| File | Purpose |
|------|---------|
| `apps/api/src/domains/logicore/compliance/__init__.py` | Package init |
| `apps/api/src/domains/logicore/compliance/audit_logger.py` | Immutable audit log writer |
| `apps/api/src/domains/logicore/compliance/data_lineage.py` | Document → chunk → embedding version tracking |
| `apps/api/src/domains/logicore/compliance/report_generator.py` | EU AI Act compliance report builder |
| `apps/api/src/domains/logicore/compliance/bias_detector.py` | Statistical fairness checks |
| `apps/api/src/core/infrastructure/postgres/migrations/001_audit_log.sql` | Audit log table (append-only) |
| `apps/api/src/core/infrastructure/postgres/migrations/002_data_lineage.sql` | Lineage tracking tables |
| `apps/api/src/domains/logicore/api/compliance.py` | GET /api/v1/compliance/audit-log, /report endpoints |
| `apps/api/src/domains/logicore/models/compliance.py` | AuditEntry, ComplianceReport, LineageRecord models |
| `tests/unit/test_audit_logger.py` | Immutability tests (verify no UPDATE/DELETE) |
| `tests/integration/test_compliance_report.py` | Full report generation test |

### Technical Spec

**API Endpoints**:

```
GET /api/v1/compliance/audit-log?from=2026-01-01&to=2026-03-01
  Response: { "entries": [AuditEntry], "total": int }

GET /api/v1/compliance/report?period=2026-Q1
  Response: { "report_id": str, "generated_at": datetime, "sections": [...] }

GET /api/v1/compliance/lineage/{document_id}
  Response: { "versions": [...], "chunks": [...], "embeddings": [...] }
```

**Audit Log Schema**:
```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    query_text TEXT NOT NULL,
    retrieved_chunk_ids JSONB NOT NULL,
    model_version VARCHAR(100) NOT NULL,
    model_deployment VARCHAR(100) NOT NULL,
    response_text TEXT NOT NULL,
    hitl_approver_id VARCHAR(255),
    langfuse_trace_id VARCHAR(255),
    metadata JSONB DEFAULT '{}'
);

-- Immutability: revoke UPDATE and DELETE
REVOKE UPDATE, DELETE ON audit_log FROM logicore;
-- Only INSERT and SELECT allowed
```

**Data Lineage**:
```sql
CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_hash VARCHAR(64) NOT NULL,  -- SHA-256 of source file
    chunk_count INT NOT NULL
);

CREATE TABLE chunk_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID REFERENCES document_versions(id),
    chunk_index INT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    qdrant_point_id VARCHAR(255) NOT NULL,
    embedding_model VARCHAR(100) NOT NULL
);
```

### Success Criteria
- [ ] Every RAG query creates an immutable audit log entry
- [ ] `UPDATE audit_log` and `DELETE FROM audit_log` fail with permission error
- [ ] Compliance report covers a date range with all decisions, models, and approvers
- [ ] Data lineage traces a document from source file → chunks → embeddings → retrieval
- [ ] Audit entry links to Langfuse trace — clicking trace ID reconstructs full context
- [ ] 6-month-old query can be fully reconstructed (same chunks, same model version)

## Cost of Getting It Wrong

Compliance logging costs EUR 5,400/year. A single unlogged decision costs up to EUR 3.5M.

| Error | Scenario | Cost | Frequency |
|---|---|---|---|
| **Audit trail gap** | Server crashes between agent execution and log write. Workflow resumes (checkpoint works), but audit entry was never written. Gap in trail. | EUR 100,000-3,500,000 (EU AI Act fine: up to 7% global turnover) | 1 incident |
| **Langfuse trace ID broken** | Langfuse rebuilt after failure. Trace IDs in audit log no longer resolve. Can't reconstruct token-level execution. | EUR 50,000-500,000 (compliance violation) | 1-2/year |
| **Over-logging PII** | Full trace captures employee health queries verbatim. Creates second GDPR liability. Data subject request reveals their queries were logged. | EUR 20,000-200,000 (GDPR fine for unnecessary retention) | 1-2/year |
| **Log volume degrades query performance** | 10 years × 10K decisions/day = 36.5M records. Report generation degrades from 10 min to 45 min. Regulator waiting. | Reputational damage + compliance risk | After 3-5 years |

**The CTO line**: "Full trace compliance logging costs EUR 5,400/year. A single unlogged AI decision that a regulator asks about costs up to EUR 3.5M. The ratio is 648:1."

### Atomic Audit Logging

The audit log write and the LangGraph checkpointer update MUST be in the same database transaction. Otherwise, a crash between them creates a compliance gap.

```python
# ❌ WRONG: Separate writes
await checkpointer.save(state)  # succeeds
await audit_logger.write(entry)  # server crashes here → gap

# ✅ RIGHT: Same transaction
async with pg_pool.acquire() as conn:
    async with conn.transaction():
        await checkpointer.save(state, conn=conn)
        await audit_logger.write(entry, conn=conn)
        # Both succeed or both roll back
```

### Engineering Time Saved Per Audit

Without Phase 8: regulator asks to reconstruct a decision from 6 months ago. 3 engineers × 2 weeks digging through logs = EUR 6,000 per audit query.

With Phase 8: 10 minutes to generate the report.

At 10 regulator audit queries/year: EUR 60,000 saved in engineering time alone — before even considering the fine risk.

## Decision Framework: Compliance Logging Depth

Not every AI decision needs the same audit granularity. Over-logging wastes storage and money. Under-logging risks regulatory fines.

### Three Logging Levels

| Level | What's Captured | Storage Multiplier | Monthly Cost (10K decisions/day) |
|---|---|---|---|
| **Full trace** | Every token in/out, chunk content, embedding vectors, Langfuse trace with full replay | 3x baseline | ~€450/mo |
| **Summary trace** | Query, response summary (first 500 chars), chunk IDs (not content), model version, approver | 1.5x baseline | ~€225/mo |
| **Metadata only** | Timestamp, user ID, model version, chunk IDs, latency, cost, trace ID (no content) | 1x baseline | ~€150/mo |

### Decision Tree: Which Level?

```
AI decision occurs
  ├─ Is this a High-Risk use case under EU AI Act?
  │   ├─ YES (financial decisions, safety-critical, HR)
  │   │   └─ FULL TRACE — mandatory under Article 12
  │   │       Store: all tokens, chunk content, full Langfuse trace
  │   │       Retention: 10 years minimum (financial), 5 years (other)
  │   └─ NO
  │       ├─ Does it involve PII or sensitive data?
  │       │   ├─ YES → SUMMARY TRACE (log structure, not raw content)
  │       │   └─ NO
  │       │       ├─ Internal analytics / search / recommendations?
  │       │       │   └─ METADATA ONLY — sufficient for debugging
  │       │       └─ External-facing decision?
  │       │           └─ SUMMARY TRACE — enough to reconstruct if disputed
  └─ Cost of non-compliance: up to 7% annual global revenue
      (For a €50M company = €3.5M fine. Full trace costs €5,400/year.)
```

### When NOT to Log Full Traces

Full traces capture every token — that's expensive and sometimes counterproductive:

- **Non-regulated use cases**: Internal search, content recommendations, fleet dashboard summaries. Metadata + summary is sufficient for debugging and incident response.
- **High-volume, low-risk decisions**: 10,000 GPS anomaly classifications/day where the rule-based tier handles 95%. Log metadata for the rule-based tier; summary trace only for the LLM-escalated 5%.
- **PII-heavy queries**: Full token logging of queries containing employee health data or salary information creates a *second* compliance liability (GDPR). Summary trace with redacted content is safer.
- **Development/staging environments**: Metadata only. Full traces in dev waste storage and risk leaking test data with real PII.

**Rule of thumb**: If a regulator would never ask about it, metadata is enough. If they might ask, summary. If they *will* ask, full trace.

## Technical Deep Dive: Document Versioning in Audit Trails

### The Problem

Contract CTR-2024-001 gets updated from v2.3 to v3.0 on October 1. An audit entry from September 15 references chunks from v2.3. If we only keep the latest version, we can't reconstruct what the AI actually saw.

### Immutable Snapshot Strategy

Every audit log entry captures the **document version at decision time**, not a pointer to the "current" version:

```
audit_log entry #4,721 (September 15)
  └─ retrieved_chunk_ids: [
       "contract-CTR-2024-001-v2.3-chunk-47",  ← version baked into ID
       "contract-CTR-2024-001-v2.3-chunk-48"
     ]
  └─ document_versions table:
       document_id: CTR-2024-001
       version: 2.3
       ingested_at: 2024-09-15
       source_hash: abc123...  ← SHA-256 proves content hasn't changed
```

### Version Lifecycle Rules

| Event | What Happens | Old Version |
|---|---|---|
| Document re-ingested (new version) | New `document_versions` row, new chunks, new embeddings | **Preserved** — old chunks remain in Qdrant with version-tagged IDs |
| Chunk content changes | New `chunk_versions` row with new `content_hash` | Old chunk row retained, Qdrant point preserved |
| Embedding model upgraded | New embeddings generated, stored alongside old | Old embeddings kept (audit entries reference them by point ID) |
| Audit query for old entry | Resolve chunk IDs → exact version that was live at decision time | Always reconstructible |

### Garbage Collection (When to Delete Old Versions)

- **Never delete** versions referenced by audit entries within the retention window (5-10 years for regulated use cases)
- **Safe to delete** after retention expiry AND no pending litigation hold
- **Soft delete first**: mark as `archived`, move to cold storage (Azure Blob Archive tier at €0.002/GB/mo), hard delete after confirmation period

## LinkedIn Post Template

### Hook
"The EU AI Act requires Article 12 compliance today. If your AI architecture doesn't include immutable logging, you're building a fine, not a feature."

### Body
Built a compliance layer for our multi-agent logistics AI. Every decision is logged:

- Who asked (user ID)
- What was asked (exact query)
- What the AI saw (retrieved chunk IDs + versions)
- Which model answered (deployment ID + checkpoint)
- What it said (exact response)
- Who approved it (HITL gateway approver)

The audit log is append-only. No UPDATE, no DELETE — enforced at the database role level, not application code. Even a compromised application server cannot tamper with the log.

Data lineage tracks the full chain: source document → document version → chunk → embedding → retrieval event. If a regulator asks "Why did the AI give this answer 6 months ago?" we can reconstruct the exact system state.

This isn't optional anymore. Article 12 mandates "automatic recording of events" for high-risk AI systems. The fines for non-compliance: up to 7% of global turnover.

### Visual
Data lineage diagram: Source PDF → Document Version (v1, v2) → Chunks (with hashes) → Qdrant Points → Retrieval Events → Audit Log Entry → Langfuse Trace

### CTA
"How are you handling AI audit trails? Are you logging at the application level or the infrastructure level?"

## Key Metrics to Screenshot
- Audit log table with sample entries (user, query, model, approver)
- Data lineage visualization: document → chunks → retrievals
- Compliance report PDF/HTML output
- Database role permissions showing UPDATE/DELETE revoked
