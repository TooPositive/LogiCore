"""Unit tests for Phase 8 compliance Pydantic models.

Tests cover:
- AuditEntryCreate: input model for writing audit entries
- AuditEntry: full model with computed fields (id, timestamps)
- ComplianceReport: summary report for a date range
- LineageRecord: document -> chunk -> embedding version tracking
- DocumentVersion / ChunkVersion: sub-models for lineage
- PIIVaultEntry: GDPR-safe PII storage with separate retention
- Field validation, defaults, serialization
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
    AuditEntryCreate,
    ChunkVersion,
    ComplianceReport,
    DocumentVersion,
    LineageRecord,
    LogLevel,
    PIIVaultEntry,
)

# --- AuditEntryCreate tests ---


class TestAuditEntryCreate:
    """Input model for creating an audit entry."""

    def test_minimal_entry_create(self):
        """Minimum required fields produce a valid entry."""
        entry = AuditEntryCreate(
            user_id="user-logistics-01",
            query_text="Audit invoice INV-2024-0847",
            retrieved_chunk_ids=["chunk-47", "chunk-48"],
            model_version="gpt-5.2-2026-0201",
            model_deployment="logicore-prod-east",
            response_text="Discrepancy detected: billed 0.52/kg vs contracted 0.45/kg",
        )
        assert entry.user_id == "user-logistics-01"
        assert len(entry.retrieved_chunk_ids) == 2
        assert entry.hitl_approver_id is None
        assert entry.langfuse_trace_id is None
        assert entry.metadata == {}
        assert entry.log_level == LogLevel.FULL_TRACE

    def test_full_entry_create_with_all_fields(self):
        """All optional fields can be set."""
        entry = AuditEntryCreate(
            user_id="user-cfo-01",
            query_text="Audit invoice INV-2024-0847",
            retrieved_chunk_ids=["chunk-47"],
            model_version="gpt-5.2-2026-0201",
            model_deployment="logicore-prod-east",
            response_text="No discrepancy found.",
            hitl_approver_id="user-cfo-01",
            langfuse_trace_id="trace-abc-123",
            metadata={"invoice_id": "INV-2024-0847"},
            log_level=LogLevel.SUMMARY,
            prev_entry_hash=None,
            prompt_tokens=150,
            completion_tokens=200,
            total_cost_eur=Decimal("0.0023"),
            response_hash="sha256:abcdef1234567890",
            is_degraded=False,
            provider_name="azure",
            quality_drift_alert=False,
        )
        assert entry.hitl_approver_id == "user-cfo-01"
        assert entry.langfuse_trace_id == "trace-abc-123"
        assert entry.prompt_tokens == 150
        assert entry.completion_tokens == 200
        assert entry.total_cost_eur == Decimal("0.0023")
        assert entry.is_degraded is False
        assert entry.provider_name == "azure"

    def test_empty_user_id_rejected(self):
        """user_id cannot be empty."""
        with pytest.raises(Exception):
            AuditEntryCreate(
                user_id="",
                query_text="test",
                retrieved_chunk_ids=[],
                model_version="v1",
                model_deployment="deploy-1",
                response_text="response",
            )

    def test_empty_query_text_rejected(self):
        """query_text cannot be empty."""
        with pytest.raises(Exception):
            AuditEntryCreate(
                user_id="user-1",
                query_text="",
                retrieved_chunk_ids=[],
                model_version="v1",
                model_deployment="deploy-1",
                response_text="response",
            )

    def test_empty_response_text_rejected(self):
        """response_text cannot be empty."""
        with pytest.raises(Exception):
            AuditEntryCreate(
                user_id="user-1",
                query_text="test",
                retrieved_chunk_ids=[],
                model_version="v1",
                model_deployment="deploy-1",
                response_text="",
            )

    def test_log_level_defaults_to_full_trace(self):
        """Default log level is FULL_TRACE for EU AI Act Article 12."""
        entry = AuditEntryCreate(
            user_id="user-1",
            query_text="test",
            retrieved_chunk_ids=[],
            model_version="v1",
            model_deployment="deploy-1",
            response_text="response",
        )
        assert entry.log_level == LogLevel.FULL_TRACE

    def test_metadata_defaults_to_empty_dict(self):
        """metadata defaults to empty dict if not provided."""
        entry = AuditEntryCreate(
            user_id="user-1",
            query_text="test",
            retrieved_chunk_ids=[],
            model_version="v1",
            model_deployment="deploy-1",
            response_text="response",
        )
        assert entry.metadata == {}

    def test_degraded_mode_fields(self):
        """Degraded mode entries mark provider and degraded flag."""
        entry = AuditEntryCreate(
            user_id="user-1",
            query_text="test",
            retrieved_chunk_ids=[],
            model_version="qwen3:8b",
            model_deployment="ollama-local",
            response_text="response from local model",
            is_degraded=True,
            provider_name="ollama",
            quality_drift_alert=True,
        )
        assert entry.is_degraded is True
        assert entry.provider_name == "ollama"
        assert entry.quality_drift_alert is True

    def test_negative_tokens_rejected(self):
        """Token counts cannot be negative."""
        with pytest.raises(Exception):
            AuditEntryCreate(
                user_id="user-1",
                query_text="test",
                retrieved_chunk_ids=[],
                model_version="v1",
                model_deployment="deploy-1",
                response_text="response",
                prompt_tokens=-1,
            )

    def test_negative_cost_rejected(self):
        """Cost cannot be negative."""
        with pytest.raises(Exception):
            AuditEntryCreate(
                user_id="user-1",
                query_text="test",
                retrieved_chunk_ids=[],
                model_version="v1",
                model_deployment="deploy-1",
                response_text="response",
                total_cost_eur=Decimal("-0.01"),
            )


# --- AuditEntry tests (read model with id + timestamps) ---


class TestAuditEntry:
    """Full audit entry with server-side fields."""

    def test_audit_entry_has_id_and_timestamps(self):
        """AuditEntry includes id, created_at, entry_hash."""
        now = datetime.now(UTC)
        entry_id = uuid4()
        entry = AuditEntry(
            id=entry_id,
            created_at=now,
            user_id="user-1",
            query_text="test",
            retrieved_chunk_ids=["chunk-1"],
            model_version="v1",
            model_deployment="deploy-1",
            response_text="response",
            entry_hash="sha256:abc123",
        )
        assert entry.id == entry_id
        assert entry.created_at == now
        assert entry.entry_hash == "sha256:abc123"

    def test_audit_entry_immutability_model_frozen(self):
        """AuditEntry is frozen -- fields cannot be modified after creation."""
        now = datetime.now(UTC)
        entry = AuditEntry(
            id=uuid4(),
            created_at=now,
            user_id="user-1",
            query_text="test",
            retrieved_chunk_ids=[],
            model_version="v1",
            model_deployment="deploy-1",
            response_text="response",
            entry_hash="sha256:abc123",
        )
        with pytest.raises(Exception):
            entry.response_text = "tampered"

    def test_audit_entry_serialization_roundtrip(self):
        """Serialize to dict and back preserves all fields."""
        now = datetime.now(UTC)
        entry_id = uuid4()
        entry = AuditEntry(
            id=entry_id,
            created_at=now,
            user_id="user-1",
            query_text="test query",
            retrieved_chunk_ids=["c-1", "c-2"],
            model_version="gpt-5.2",
            model_deployment="prod-east",
            response_text="response text",
            entry_hash="sha256:def456",
            prev_entry_hash="sha256:abc123",
            hitl_approver_id="approver-1",
            langfuse_trace_id="trace-xyz",
            metadata={"key": "value"},
            log_level=LogLevel.SUMMARY,
            prompt_tokens=100,
            completion_tokens=50,
            total_cost_eur=Decimal("0.005"),
            response_hash="sha256:resp123",
            is_degraded=False,
            provider_name="azure",
            quality_drift_alert=False,
        )
        data = entry.model_dump()
        restored = AuditEntry(**data)
        assert restored.id == entry_id
        assert restored.query_text == "test query"
        assert restored.prompt_tokens == 100
        assert restored.total_cost_eur == Decimal("0.005")


# --- LogLevel enum tests ---


class TestLogLevel:
    """Three-tier logging levels from phase spec."""

    def test_three_levels_exist(self):
        assert LogLevel.FULL_TRACE == "full_trace"
        assert LogLevel.SUMMARY == "summary"
        assert LogLevel.METADATA_ONLY == "metadata_only"

    def test_log_level_values(self):
        """All expected values are accessible."""
        levels = [e.value for e in LogLevel]
        assert "full_trace" in levels
        assert "summary" in levels
        assert "metadata_only" in levels


# --- ComplianceReport tests ---


class TestComplianceReport:
    """EU AI Act Article 12 compliance report model."""

    def test_compliance_report_creation(self):
        report = ComplianceReport(
            report_id=uuid4(),
            generated_at=datetime.now(UTC),
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 31, tzinfo=UTC),
            total_entries=4721,
            entries_by_level={"full_trace": 3000, "summary": 1500, "metadata_only": 221},
            models_used=["gpt-5.2-2026-0201"],
            unique_users=15,
            hitl_approval_count=42,
            total_cost_eur=Decimal("234.56"),
            generated_by="compliance-officer-01",
        )
        assert report.total_entries == 4721
        assert report.unique_users == 15
        assert report.total_cost_eur == Decimal("234.56")

    def test_compliance_report_period_validation(self):
        """period_end must be after period_start."""
        with pytest.raises(Exception):
            ComplianceReport(
                report_id=uuid4(),
                generated_at=datetime.now(UTC),
                period_start=datetime(2026, 3, 31, tzinfo=UTC),
                period_end=datetime(2026, 1, 1, tzinfo=UTC),
                total_entries=0,
                entries_by_level={},
                models_used=[],
                unique_users=0,
                hitl_approval_count=0,
                total_cost_eur=Decimal("0"),
                generated_by="sys",
            )


# --- DocumentVersion / ChunkVersion / LineageRecord tests ---


class TestDocumentVersion:
    """Document version tracking for audit lineage."""

    def test_document_version_creation(self):
        dv = DocumentVersion(
            id=uuid4(),
            document_id="CTR-2024-001",
            version=3,
            ingested_at=datetime.now(UTC),
            source_hash="sha256:abc123def456",
            chunk_count=12,
        )
        assert dv.document_id == "CTR-2024-001"
        assert dv.version == 3
        assert dv.chunk_count == 12

    def test_version_must_be_positive(self):
        with pytest.raises(Exception):
            DocumentVersion(
                id=uuid4(),
                document_id="CTR-2024-001",
                version=0,
                ingested_at=datetime.now(UTC),
                source_hash="sha256:abc",
                chunk_count=1,
            )


class TestChunkVersion:
    """Chunk version tracking within a document version."""

    def test_chunk_version_creation(self):
        cv = ChunkVersion(
            id=uuid4(),
            document_version_id=uuid4(),
            chunk_index=47,
            content_hash="sha256:chunk47hash",
            qdrant_point_id="q-47-v2",
            embedding_model="text-embedding-3-small",
        )
        assert cv.chunk_index == 47
        assert cv.qdrant_point_id == "q-47-v2"

    def test_chunk_index_non_negative(self):
        with pytest.raises(Exception):
            ChunkVersion(
                id=uuid4(),
                document_version_id=uuid4(),
                chunk_index=-1,
                content_hash="sha256:x",
                qdrant_point_id="q-1",
                embedding_model="model",
            )


class TestLineageRecord:
    """Full lineage: document -> chunks -> retrieval events."""

    def test_lineage_record_creation(self):
        doc_ver = DocumentVersion(
            id=uuid4(),
            document_id="CTR-2024-001",
            version=2,
            ingested_at=datetime.now(UTC),
            source_hash="sha256:source",
            chunk_count=5,
        )
        chunk_ver = ChunkVersion(
            id=uuid4(),
            document_version_id=doc_ver.id,
            chunk_index=0,
            content_hash="sha256:c0",
            qdrant_point_id="q-0",
            embedding_model="text-embedding-3-small",
        )
        record = LineageRecord(
            document_id="CTR-2024-001",
            versions=[doc_ver],
            chunks=[chunk_ver],
        )
        assert record.document_id == "CTR-2024-001"
        assert len(record.versions) == 1
        assert len(record.chunks) == 1


# --- PIIVaultEntry tests ---


class TestPIIVaultEntry:
    """GDPR-safe PII storage with separate retention policy."""

    def test_pii_vault_entry_creation(self):
        entry = PIIVaultEntry(
            id=uuid4(),
            audit_entry_id=uuid4(),
            encrypted_query_text="AES256GCM:encrypted_blob_here",
            query_hash="sha256:queryhash123",
            created_at=datetime.now(UTC),
            retention_expires_at=datetime.now(UTC) + timedelta(days=365 * 5),
        )
        assert entry.encrypted_query_text.startswith("AES256GCM:")
        assert entry.query_hash.startswith("sha256:")

    def test_pii_vault_requires_all_fields(self):
        """All fields are required -- no optional PII storage."""
        with pytest.raises(Exception):
            PIIVaultEntry(
                id=uuid4(),
                audit_entry_id=uuid4(),
                # missing encrypted_query_text, query_hash, timestamps
            )

    def test_pii_vault_retention_date_must_be_future_relative_to_created(self):
        """retention_expires_at should be after created_at."""
        now = datetime.now(UTC)
        entry = PIIVaultEntry(
            id=uuid4(),
            audit_entry_id=uuid4(),
            encrypted_query_text="AES256GCM:blob",
            query_hash="sha256:hash",
            created_at=now,
            retention_expires_at=now + timedelta(days=1),
        )
        assert entry.retention_expires_at > entry.created_at
