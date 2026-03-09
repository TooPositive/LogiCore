-- Phase 8: Data Lineage Tables for EU AI Act Article 12 Compliance
--
-- DESIGN DECISIONS:
-- 1. Every document re-ingestion creates a new document_versions row.
--    Old versions are preserved so audit entries can reference the exact
--    document state at decision time.
-- 2. chunk_versions references document_versions via FK. Each chunk stores
--    its content hash, Qdrant point ID, and embedding model for full
--    traceability: source file -> document version -> chunk -> embedding.
-- 3. Indexes on document_id and document_version_id for fast lineage lookups.
-- 4. source_hash (SHA-256 of source file) enables tamper detection:
--    re-hash the file and compare to stored hash.

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR(255) NOT NULL,
    version INT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_hash VARCHAR(64) NOT NULL,  -- SHA-256 of source file
    chunk_count INT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES document_versions(id),
    chunk_index INT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,  -- SHA-256 of chunk content
    qdrant_point_id VARCHAR(255) NOT NULL,
    embedding_model VARCHAR(100) NOT NULL
);

-- Indexes for lineage lookups
CREATE INDEX IF NOT EXISTS idx_document_versions_document_id
    ON document_versions (document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_versions_document_version_id
    ON chunk_versions (document_version_id);
