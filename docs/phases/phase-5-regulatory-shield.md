# Phase 5: "The Regulatory Shield" — EU AI Act Compliance

## Business Problem

The EU AI Act enforcement for "High-Risk" AI systems is approaching. Companies using AI for financial decisions, HR screening, or safety-critical logistics face mandatory compliance with Articles 11 (Technical Documentation), 12 (Record-Keeping), and 14 (Human Oversight). Non-compliance means fines up to 7% of global turnover.

**CTO pain**: "Legal says we need full audit trails for every AI decision. If a regulator asks 'Why did the AI flag this invoice 6 months ago?' we need to reconstruct the exact system state."

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
| `apps/api/src/compliance/__init__.py` | Package init |
| `apps/api/src/compliance/audit_logger.py` | Immutable audit log writer |
| `apps/api/src/compliance/data_lineage.py` | Document → chunk → embedding version tracking |
| `apps/api/src/compliance/report_generator.py` | EU AI Act compliance report builder |
| `apps/api/src/compliance/bias_detector.py` | Statistical fairness checks |
| `apps/api/src/infrastructure/postgres/migrations/001_audit_log.sql` | Audit log table (append-only) |
| `apps/api/src/infrastructure/postgres/migrations/002_data_lineage.sql` | Lineage tracking tables |
| `apps/api/src/api/v1/compliance.py` | GET /api/v1/compliance/audit-log, /report endpoints |
| `apps/api/src/domain/compliance.py` | AuditEntry, ComplianceReport, LineageRecord models |
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
