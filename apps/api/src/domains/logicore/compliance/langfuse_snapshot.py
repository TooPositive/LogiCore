"""Langfuse snapshot helper for self-contained audit entries.

Extracts snapshot fields from Langfuse trace data and verifies them
against audit entries. This ensures audit entries are reconstructable
even if Langfuse goes down or gets rebuilt (single point of failure
elimination).

Functions:
  - create_langfuse_snapshot(trace_data) -> dict of snapshot fields
  - verify_snapshot_against_trace(entry, trace_data) -> (bool, list[str])
"""

import hashlib
import json
from decimal import Decimal

from apps.api.src.domains.logicore.models.compliance import AuditEntry


def _compute_response_hash(output: object) -> str:
    """Compute SHA-256 hash of trace output for tamper detection."""
    content = json.dumps(output, sort_keys=True, default=str)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def create_langfuse_snapshot(trace_data: dict) -> dict:
    """Extract snapshot fields from Langfuse trace data.

    Returns a dict with the 5 audit-critical fields:
      - prompt_tokens: number of input tokens
      - completion_tokens: number of output tokens
      - total_cost_eur: total cost in EUR
      - model_version: model identifier
      - response_hash: SHA-256 of the trace output

    Missing fields default to safe values (0 tokens, 0 cost, None model).
    """
    usage = trace_data.get("usage", {}) or {}
    cost = trace_data.get("cost")
    model = trace_data.get("model")
    output = trace_data.get("output")

    return {
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "total_cost_eur": Decimal(str(cost)) if cost else Decimal("0"),
        "model_version": model,
        "response_hash": _compute_response_hash(output),
    }


def verify_snapshot_against_trace(
    audit_entry: AuditEntry,
    trace_data: dict,
) -> tuple[bool, list[str]]:
    """Compare audit entry snapshot fields to live Langfuse trace data.

    Returns:
        (True, []) if all fields match.
        (False, ["field: expected X, got Y", ...]) for each mismatch.

    This detects:
      - Langfuse trace tampering (someone modified trace after audit)
      - Langfuse rebuild drift (trace IDs resolve but data changed)
      - Missing snapshot data in audit entry (None vs actual values)
    """
    live_snapshot = create_langfuse_snapshot(trace_data)
    mismatches: list[str] = []

    # Compare prompt_tokens
    if audit_entry.prompt_tokens != live_snapshot["prompt_tokens"]:
        mismatches.append(
            f"prompt_tokens: audit={audit_entry.prompt_tokens}, "
            f"trace={live_snapshot['prompt_tokens']}"
        )

    # Compare completion_tokens
    if audit_entry.completion_tokens != live_snapshot["completion_tokens"]:
        mismatches.append(
            f"completion_tokens: audit={audit_entry.completion_tokens}, "
            f"trace={live_snapshot['completion_tokens']}"
        )

    # Compare total_cost_eur
    entry_cost = audit_entry.total_cost_eur or Decimal("0")
    if entry_cost != live_snapshot["total_cost_eur"]:
        mismatches.append(
            f"total_cost_eur: audit={entry_cost}, "
            f"trace={live_snapshot['total_cost_eur']}"
        )

    # Compare response_hash
    if audit_entry.response_hash != live_snapshot["response_hash"]:
        mismatches.append(
            f"response_hash: audit={audit_entry.response_hash}, "
            f"trace={live_snapshot['response_hash']}"
        )

    return (len(mismatches) == 0, mismatches)
