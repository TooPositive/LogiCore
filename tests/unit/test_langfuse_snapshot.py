"""Unit tests for Langfuse snapshot helper.

The AuditEntry already stores snapshot fields (prompt_tokens,
completion_tokens, total_cost_eur, response_hash) from M1. This helper:
  - Extracts snapshot fields from Langfuse trace data
  - Verifies snapshot against live trace (detects tampering/drift)
  - Ensures audit entry is self-contained without Langfuse

Tests cover:
  - Snapshot extracts correct fields from trace data
  - Snapshot with missing fields provides defaults
  - verify detects mismatch (tampered Langfuse trace)
  - verify passes for matching data
  - Audit entry is reconstructable without Langfuse
  - Snapshot handles None/empty trace data gracefully
  - Multiple mismatches detected and listed
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from apps.api.src.domains.logicore.models.compliance import (
    AuditEntry,
)


def _make_audit_entry(**overrides) -> AuditEntry:
    """Factory for AuditEntry with snapshot fields."""
    defaults = {
        "id": uuid4(),
        "created_at": datetime.now(UTC),
        "entry_hash": "sha256:abc123",
        "user_id": "user-logistics-01",
        "query_text": "Audit invoice INV-2024-0847",
        "retrieved_chunk_ids": ["chunk-47", "chunk-48"],
        "model_version": "gpt-5.2-2026-0201",
        "model_deployment": "logicore-prod-east",
        "response_text": "Discrepancy detected",
        "prompt_tokens": 250,
        "completion_tokens": 180,
        "total_cost_eur": Decimal("0.012"),
        "response_hash": "sha256:response_abc",
    }
    defaults.update(overrides)
    return AuditEntry(**defaults)


def _make_trace_data(**overrides) -> dict:
    """Factory for Langfuse trace data dict."""
    defaults = {
        "id": "trace-abc-123",
        "name": "audit-workflow",
        "input": {"query": "Audit invoice INV-2024-0847"},
        "output": {"response": "Discrepancy detected"},
        "metadata": {"model_version": "gpt-5.2-2026-0201"},
        "usage": {
            "prompt_tokens": 250,
            "completion_tokens": 180,
            "total_tokens": 430,
        },
        "cost": 0.012,
        "model": "gpt-5.2-2026-0201",
    }
    defaults.update(overrides)
    return defaults


class TestCreateLangfuseSnapshot:
    """create_langfuse_snapshot: extract fields from trace data."""

    def test_extracts_correct_fields(self):
        """Snapshot extracts tokens, cost, and model from trace data."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        trace = _make_trace_data()
        snapshot = create_langfuse_snapshot(trace)

        assert snapshot["prompt_tokens"] == 250
        assert snapshot["completion_tokens"] == 180
        assert snapshot["total_cost_eur"] == Decimal("0.012")
        assert snapshot["model_version"] == "gpt-5.2-2026-0201"

    def test_extracts_response_hash(self):
        """Snapshot computes response_hash from trace output."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        trace = _make_trace_data()
        snapshot = create_langfuse_snapshot(trace)

        assert snapshot["response_hash"] is not None
        assert snapshot["response_hash"].startswith("sha256:")

    def test_missing_usage_defaults_to_zero(self):
        """When trace has no usage data, tokens default to 0."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        trace = _make_trace_data()
        del trace["usage"]
        snapshot = create_langfuse_snapshot(trace)

        assert snapshot["prompt_tokens"] == 0
        assert snapshot["completion_tokens"] == 0

    def test_missing_cost_defaults_to_zero(self):
        """When trace has no cost data, cost defaults to 0."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        trace = _make_trace_data()
        del trace["cost"]
        snapshot = create_langfuse_snapshot(trace)

        assert snapshot["total_cost_eur"] == Decimal("0")

    def test_empty_trace_provides_all_defaults(self):
        """Empty trace dict produces snapshot with all defaults."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        snapshot = create_langfuse_snapshot({})

        assert snapshot["prompt_tokens"] == 0
        assert snapshot["completion_tokens"] == 0
        assert snapshot["total_cost_eur"] == Decimal("0")
        assert snapshot["model_version"] is None
        assert snapshot["response_hash"] is not None  # hash of empty/None

    def test_snapshot_has_all_required_keys(self):
        """Snapshot always contains the 5 audit-critical keys."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
        )

        trace = _make_trace_data()
        snapshot = create_langfuse_snapshot(trace)

        required_keys = {
            "prompt_tokens",
            "completion_tokens",
            "total_cost_eur",
            "model_version",
            "response_hash",
        }
        assert required_keys.issubset(snapshot.keys())


class TestVerifySnapshot:
    """verify_snapshot_against_trace: detect snapshot/trace mismatch."""

    def test_matching_data_passes(self):
        """When snapshot and trace match, returns (True, [])."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            create_langfuse_snapshot,
            verify_snapshot_against_trace,
        )

        trace = _make_trace_data()
        snapshot = create_langfuse_snapshot(trace)

        # Create an AuditEntry with matching snapshot fields
        entry = _make_audit_entry(
            prompt_tokens=snapshot["prompt_tokens"],
            completion_tokens=snapshot["completion_tokens"],
            total_cost_eur=snapshot["total_cost_eur"],
            response_hash=snapshot["response_hash"],
        )

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        assert matches is True
        assert mismatches == []

    def test_detects_token_mismatch(self):
        """Tampered prompt_tokens in trace is detected."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            verify_snapshot_against_trace,
        )

        entry = _make_audit_entry(prompt_tokens=250)
        trace = _make_trace_data()
        trace["usage"]["prompt_tokens"] = 999  # tampered

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        assert matches is False
        assert any("prompt_tokens" in m for m in mismatches)

    def test_detects_cost_mismatch(self):
        """Tampered cost in trace is detected."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            verify_snapshot_against_trace,
        )

        entry = _make_audit_entry(total_cost_eur=Decimal("0.012"))
        trace = _make_trace_data()
        trace["cost"] = 0.999  # tampered

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        assert matches is False
        assert any("total_cost_eur" in m for m in mismatches)

    def test_detects_response_hash_mismatch(self):
        """Changed response output is detected via hash mismatch."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            verify_snapshot_against_trace,
        )

        entry = _make_audit_entry(response_hash="sha256:original")
        trace = _make_trace_data()
        trace["output"] = {"response": "TAMPERED response text"}

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        assert matches is False
        assert any("response_hash" in m for m in mismatches)

    def test_multiple_mismatches_all_reported(self):
        """All mismatches are reported, not just the first one."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            verify_snapshot_against_trace,
        )

        entry = _make_audit_entry(
            prompt_tokens=250,
            completion_tokens=180,
            total_cost_eur=Decimal("0.012"),
            response_hash="sha256:original",
        )
        trace = _make_trace_data()
        trace["usage"]["prompt_tokens"] = 999
        trace["usage"]["completion_tokens"] = 999
        trace["cost"] = 99.99

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        assert matches is False
        assert len(mismatches) >= 3

    def test_entry_reconstructable_without_langfuse(self):
        """AuditEntry snapshot fields contain enough data for compliance
        without needing to query Langfuse."""
        entry = _make_audit_entry(
            prompt_tokens=250,
            completion_tokens=180,
            total_cost_eur=Decimal("0.012"),
            response_hash="sha256:response_abc",
            langfuse_trace_id="trace-abc-123",
        )

        # All critical fields are present in the entry itself
        assert entry.prompt_tokens is not None
        assert entry.completion_tokens is not None
        assert entry.total_cost_eur is not None
        assert entry.response_hash is not None
        assert entry.model_version is not None
        assert entry.model_deployment is not None

    def test_verify_with_none_entry_fields_still_works(self):
        """When audit entry has None snapshot fields, verify reports
        mismatches against actual trace data."""
        from apps.api.src.domains.logicore.compliance.langfuse_snapshot import (
            verify_snapshot_against_trace,
        )

        entry = _make_audit_entry(
            prompt_tokens=None,
            completion_tokens=None,
            total_cost_eur=None,
            response_hash=None,
        )
        trace = _make_trace_data()

        matches, mismatches = verify_snapshot_against_trace(entry, trace)

        # Mismatches expected since entry has None but trace has values
        assert matches is False
        assert len(mismatches) > 0
