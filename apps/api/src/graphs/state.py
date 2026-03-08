"""LangGraph state schema for audit workflow.

TypedDict-based state that flows through all graph nodes.
Each node reads what it needs and writes its outputs.
"""

from typing import Any, TypedDict


class AuditGraphState(TypedDict):
    """State for the audit workflow graph.

    Fields:
        invoice_id: The invoice being audited.
        run_id: Unique identifier for this audit run.
        status: Current workflow status.
        extracted_rates: Contract rates extracted by Reader (list of dicts).
        invoice_data: Invoice data fetched by SQL agent (dict or None).
        discrepancies: Discrepancies found by Auditor (list of dicts).
        approval: HITL approval decision (dict or None).
        report: Final audit report (dict or None).
    """

    invoice_id: str
    run_id: str
    status: str
    extracted_rates: list[dict[str, Any]]
    invoice_data: dict[str, Any] | None
    discrepancies: list[dict[str, Any]]
    approval: dict[str, Any] | None
    report: dict[str, Any] | None
