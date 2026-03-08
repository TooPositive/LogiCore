"""Report Generator -- produces structured audit reports.

Takes the full audit state (invoice, discrepancies, approval)
and creates an AuditReport. Deterministic, no LLM needed.
Idempotent: same inputs always produce same output.
"""

from decimal import Decimal

from apps.api.src.domain.audit import (
    ApprovalDecision,
    AuditReport,
    Discrepancy,
    DiscrepancyBand,
    Invoice,
)

# Band priority for max_band calculation
_BAND_PRIORITY = {
    DiscrepancyBand.AUTO_APPROVE: 0,
    DiscrepancyBand.INVESTIGATE: 1,
    DiscrepancyBand.ESCALATE: 2,
    DiscrepancyBand.CRITICAL: 3,
}


class ReportGenerator:
    """Generates audit reports from workflow results."""

    async def generate(
        self,
        run_id: str,
        invoice: Invoice,
        discrepancies: list[Discrepancy],
        approval: ApprovalDecision | None = None,
    ) -> AuditReport:
        """Generate a structured audit report."""
        total_discrepancy = sum(
            (d.difference for d in discrepancies), Decimal("0")
        )

        if discrepancies:
            max_band = max(
                (d.band for d in discrepancies),
                key=lambda b: _BAND_PRIORITY[b],
            )
        else:
            max_band = DiscrepancyBand.AUTO_APPROVE

        summary = self._build_summary(invoice, discrepancies, total_discrepancy, max_band)

        return AuditReport(
            run_id=run_id,
            invoice_id=invoice.invoice_id,
            summary=summary,
            discrepancies=discrepancies,
            total_discrepancy=total_discrepancy,
            max_band=max_band,
            approval=approval,
        )

    def _build_summary(
        self,
        invoice: Invoice,
        discrepancies: list[Discrepancy],
        total: Decimal,
        max_band: DiscrepancyBand,
    ) -> str:
        """Build a human-readable summary."""
        if not discrepancies:
            return (
                f"Invoice {invoice.invoice_id} from {invoice.vendor}: "
                f"no discrepancies found. All rates match contract."
            )

        count = len(discrepancies)
        return (
            f"Invoice {invoice.invoice_id} from {invoice.vendor}: "
            f"{count} discrepanc{'y' if count == 1 else 'ies'} found "
            f"totaling {invoice.currency} {total:.2f}. "
            f"Maximum severity: {max_band.value}."
        )
