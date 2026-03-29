"""Phase 8 compliance models for EU AI Act Article 12 audit logging.

Models:
- AuditEntryCreate: input for writing an audit entry (all user-supplied fields)
- AuditEntry: full entry with server-side fields (id, timestamps, hash chain)
- ComplianceReport: Article 12 compliance report for a date range
- DocumentVersion / ChunkVersion: data lineage sub-models
- LineageRecord: full document -> chunk -> embedding lineage
- PIIVaultEntry: GDPR-safe PII storage with separate retention policy
- LogLevel: three-tier logging depth (full_trace, summary, metadata_only)

Frozen models (AuditEntry) enforce immutability at the application layer.
Database-level immutability (REVOKE UPDATE/DELETE) is enforced in migration.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class LogLevel(StrEnum):
    """Three-tier logging depth per phase spec decision tree.

    FULL_TRACE: every token in/out, chunk content, Langfuse trace -- Article 12 mandatory
    SUMMARY: query + response summary + chunk IDs -- external-facing / PII-containing
    METADATA_ONLY: timestamp, user, model, chunk IDs, cost -- internal analytics
    """

    FULL_TRACE = "full_trace"
    SUMMARY = "summary"
    METADATA_ONLY = "metadata_only"


class AuditEntryCreate(BaseModel):
    """Input model for creating an immutable audit log entry.

    All fields supplied by the caller. Server-side fields (id, created_at,
    entry_hash) are added by the audit logger on write.
    """

    # Core fields (Article 12 mandatory)
    user_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    retrieved_chunk_ids: list[str]
    model_version: str = Field(min_length=1)
    model_deployment: str = Field(min_length=1)
    response_text: str = Field(min_length=1)

    # Optional context
    hitl_approver_id: str | None = None
    langfuse_trace_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    log_level: LogLevel = LogLevel.FULL_TRACE

    # Hash chain (M2: set by audit logger, but accepted on create for flexibility)
    prev_entry_hash: str | None = None

    # Langfuse snapshot fields (self-contained audit entry)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_cost_eur: Decimal | None = Field(default=None, ge=Decimal("0"))
    response_hash: str | None = None

    # Degraded mode fields (Phase 7 integration)
    is_degraded: bool = False
    provider_name: str | None = None
    quality_drift_alert: bool = False


class AuditEntry(BaseModel):
    """Full audit log entry -- immutable after creation.

    Frozen: fields cannot be modified after construction.
    This mirrors the database constraint (REVOKE UPDATE/DELETE).
    """

    model_config = {"frozen": True}

    # Server-side fields
    id: UUID
    created_at: datetime
    entry_hash: str

    # Core fields (same as AuditEntryCreate)
    user_id: str
    query_text: str
    retrieved_chunk_ids: list[str]
    model_version: str
    model_deployment: str
    response_text: str

    # Optional context
    hitl_approver_id: str | None = None
    langfuse_trace_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    log_level: LogLevel = LogLevel.FULL_TRACE

    # Hash chain
    prev_entry_hash: str | None = None

    # Langfuse snapshot
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_cost_eur: Decimal | None = None
    response_hash: str | None = None

    # Degraded mode
    is_degraded: bool = False
    provider_name: str | None = None
    quality_drift_alert: bool = False


class ComplianceReport(BaseModel):
    """EU AI Act Article 12 compliance report for a date range.

    Summarizes all audit entries within the period: models used,
    user count, HITL approvals, cost, and entries by logging level.
    """

    report_id: UUID
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    total_entries: int = Field(ge=0)
    entries_by_level: dict[str, int]
    models_used: list[str]
    unique_users: int = Field(ge=0)
    hitl_approval_count: int = Field(ge=0)
    total_cost_eur: Decimal = Field(ge=Decimal("0"))
    generated_by: str
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def period_end_after_start(self) -> "ComplianceReport":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class DocumentVersion(BaseModel):
    """Version of a document in the lineage tracking system.

    Each re-ingestion creates a new version. Old versions are preserved
    so audit entries can reference the exact document state at decision time.
    """

    id: UUID
    document_id: str
    version: int = Field(ge=1)
    ingested_at: datetime
    source_hash: str  # SHA-256 of source file
    chunk_count: int = Field(ge=0)


class ChunkVersion(BaseModel):
    """Version of a chunk within a document version.

    Links to Qdrant point ID and embedding model for full traceability.
    """

    id: UUID
    document_version_id: UUID
    chunk_index: int = Field(ge=0)
    content_hash: str  # SHA-256 of chunk content
    qdrant_point_id: str
    embedding_model: str


class LineageRecord(BaseModel):
    """Full data lineage for a document: versions + chunks.

    Used by /api/v1/compliance/lineage/{document_id} endpoint.
    """

    document_id: str
    versions: list[DocumentVersion]
    chunks: list[ChunkVersion]


class PIIVaultEntry(BaseModel):
    """GDPR-safe PII storage with separate retention policy.

    Resolves the GDPR vs EU AI Act tension: raw PII is stored here
    (encrypted), while the audit log stores only a query_hash.
    On GDPR erasure request, delete from PII vault while keeping
    the audit entry structure intact for Article 12 compliance.
    """

    id: UUID
    audit_entry_id: UUID
    encrypted_query_text: str
    query_hash: str
    created_at: datetime
    retention_expires_at: datetime
