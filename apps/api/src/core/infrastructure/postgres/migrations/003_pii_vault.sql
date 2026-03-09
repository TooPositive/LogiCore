-- Phase 8 M2: PII Vault for GDPR-safe query text storage
--
-- DESIGN DECISIONS:
-- 1. Separate from audit_log: GDPR erasure (soft delete) happens here
--    without touching the append-only audit_log table.
-- 2. query_text_encrypted (BYTEA): AES-256-GCM encrypted query text.
--    Key management is external (Azure Key Vault / env var).
-- 3. Soft delete (deleted_at): preserves the row for audit trail structure
--    while marking PII as erased. Hard delete after retention expiry.
-- 4. retention_until: Article 12 requires 5-10 year retention for
--    high-risk AI decisions. GDPR erasure sets deleted_at but the row
--    remains until retention_until for compliance verification.
-- 5. FK to audit_log: one-to-one relationship. Not all audit entries
--    have PII (only those flagged by detect_pii heuristic).

CREATE TABLE IF NOT EXISTS audit_pii_vault (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_entry_id UUID NOT NULL REFERENCES audit_log(id),
    query_text_encrypted BYTEA NOT NULL,
    encryption_key_id VARCHAR(100) NOT NULL,
    retention_until TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- Index for FK lookups (retrieve by audit entry)
CREATE INDEX IF NOT EXISTS idx_pii_vault_audit_entry_id
    ON audit_pii_vault (audit_entry_id);

-- Index for retention cleanup jobs
CREATE INDEX IF NOT EXISTS idx_pii_vault_retention_until
    ON audit_pii_vault (retention_until)
    WHERE deleted_at IS NOT NULL;

-- IMMUTABILITY: PII vault allows UPDATE (for soft delete) but not DELETE.
-- Hard deletes are done by a separate maintenance job with elevated privileges.
REVOKE DELETE ON audit_pii_vault FROM logicore;
