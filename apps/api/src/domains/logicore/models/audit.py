"""Domain models for Phase 3: Customs & Finance Engine.

Models: Invoice, ContractRate, LineItem, Discrepancy, DiscrepancyBand,
AuditReport, ApprovalDecision.

Discrepancy bands map to business actions:
  <1%  AUTO_APPROVE  -- rounding/FX, log only
  1-5% INVESTIGATE   -- possible data entry error, flag for review
  5-15% ESCALATE     -- significant, HITL required
  >15% CRITICAL      -- potential fraud, CFO alert
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class DiscrepancyBand(StrEnum):
    """Discrepancy magnitude classification.

    Boundaries: [0,1) = auto_approve, [1,5) = investigate,
    [5,15) = escalate, [15,inf) = critical.
    """

    AUTO_APPROVE = "auto_approve"
    INVESTIGATE = "investigate"
    ESCALATE = "escalate"
    CRITICAL = "critical"


def classify_discrepancy_band(percentage: Decimal) -> DiscrepancyBand:
    """Classify a discrepancy percentage into a business action band.

    Uses absolute value -- undercharges are as noteworthy as overcharges.
    """
    abs_pct = abs(percentage)
    if abs_pct < Decimal("1"):
        return DiscrepancyBand.AUTO_APPROVE
    elif abs_pct < Decimal("5"):
        return DiscrepancyBand.INVESTIGATE
    elif abs_pct < Decimal("15"):
        return DiscrepancyBand.ESCALATE
    else:
        return DiscrepancyBand.CRITICAL


class ContractRate(BaseModel):
    """Rate extracted from a contract via RAG."""

    contract_id: str
    rate: Decimal = Field(ge=Decimal("0"))
    currency: str
    unit: str
    cargo_type: str | None = None
    min_volume: Decimal | None = None
    clearance_level: int = Field(default=1, ge=1, le=4)


class LineItem(BaseModel):
    """Invoice line item -- actual billing data from SQL."""

    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total: Decimal
    cargo_type: str | None = None


class Invoice(BaseModel):
    """Invoice with line items."""

    invoice_id: str
    vendor: str
    contract_id: str
    issue_date: datetime
    total_amount: Decimal = Field(ge=Decimal("0"))
    currency: str
    line_items: list[LineItem] = Field(min_length=1)


class Discrepancy(BaseModel):
    """A discrepancy found between contract rate and invoice billing."""

    line_item_index: int
    description: str
    expected_rate: Decimal
    actual_rate: Decimal
    expected_total: Decimal
    actual_total: Decimal
    difference: Decimal
    percentage: Decimal
    band: DiscrepancyBand
    currency: str


class ApprovalDecision(BaseModel):
    """HITL approval or rejection of an audit finding."""

    approved: bool
    reviewer_id: str
    notes: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditReport(BaseModel):
    """Final audit report -- output of the full workflow."""

    run_id: str
    invoice_id: str
    summary: str
    discrepancies: list[Discrepancy]
    total_discrepancy: Decimal
    max_band: DiscrepancyBand
    approval: ApprovalDecision | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
