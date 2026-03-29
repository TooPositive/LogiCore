-- Phase 8: Immutable Audit Log for EU AI Act Article 12 Compliance
--
-- DESIGN DECISIONS:
-- 1. Append-only: REVOKE UPDATE/DELETE at role level, not application code.
--    Even a compromised application server cannot tamper with the log.
-- 2. Hash chain: prev_entry_hash + entry_hash provide mathematical proof
--    of sequential integrity (tamper evidence beyond REVOKE).
-- 3. Langfuse snapshot: prompt_tokens, completion_tokens, total_cost_eur,
--    response_hash are stored in the audit entry itself. If Langfuse goes
--    down or gets rebuilt, the audit entry is self-contained.
-- 4. Degraded mode: is_degraded + provider_name track when the system
--    fell back to a local model (Phase 7). quality_drift_alert flags
--    entries where quality may have been compromised.
-- 5. JSONB for metadata and retrieved_chunk_ids: flexible schema
--    without sacrificing query performance.
-- 6. Indexes on created_at (date range reports) and user_id (per-user queries).

CREATE TABLE IF NOT EXISTS audit_log (
    -- Identity
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Article 12: Who asked
    user_id VARCHAR(255) NOT NULL,

    -- Article 12: What was asked
    query_text TEXT NOT NULL,

    -- Article 12: What AI saw (chunk IDs with versions baked in)
    retrieved_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Article 12: Which model answered
    model_version VARCHAR(100) NOT NULL,
    model_deployment VARCHAR(100) NOT NULL,

    -- Article 12: What it said
    response_text TEXT NOT NULL,

    -- Article 12: Who approved (HITL gateway)
    hitl_approver_id VARCHAR(255),

    -- Langfuse trace link
    langfuse_trace_id VARCHAR(255),

    -- Flexible metadata (invoice_id, run_id, etc.)
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Logging depth (full_trace / summary / metadata_only)
    log_level VARCHAR(20) NOT NULL DEFAULT 'full_trace',

    -- Hash chain for tamper evidence
    prev_entry_hash VARCHAR(128),
    entry_hash VARCHAR(128) NOT NULL,

    -- Langfuse snapshot (self-contained audit entry)
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_cost_eur NUMERIC(12, 6),
    response_hash VARCHAR(128),

    -- Degraded mode tracking (Phase 7 integration)
    is_degraded BOOLEAN NOT NULL DEFAULT FALSE,
    provider_name VARCHAR(50),
    quality_drift_alert BOOLEAN NOT NULL DEFAULT FALSE
);

-- Indexes for compliance report queries
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log (user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id_created_at ON audit_log (user_id, created_at);

-- IMMUTABILITY ENFORCEMENT
-- The application role can only INSERT and SELECT.
-- Even a compromised application server cannot UPDATE or DELETE audit entries.
-- DBA access should be restricted via separate mechanisms (pg_hba.conf, audit triggers).
REVOKE UPDATE, DELETE ON audit_log FROM logicore;
