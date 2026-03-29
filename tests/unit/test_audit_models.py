"""Tests for Phase 3 audit domain models.

Covers: Invoice, ContractRate, LineItem, Discrepancy, DiscrepancyBand,
AuditReport, ApprovalDecision. Each model tested for creation,
serialization, validation, and edge cases.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError


class TestDiscrepancyBand:
    """Discrepancy band classification: <1%, 1-5%, 5-15%, >15%."""

    def test_band_auto_approve_under_one_percent(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("0.5")) == DiscrepancyBand.AUTO_APPROVE

    def test_band_auto_approve_zero(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("0.0")) == DiscrepancyBand.AUTO_APPROVE

    def test_band_investigate_one_to_five(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("3.2")) == DiscrepancyBand.INVESTIGATE

    def test_band_investigate_boundary_one_percent(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("1.0")) == DiscrepancyBand.INVESTIGATE

    def test_band_escalate_five_to_fifteen(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("10.0")) == DiscrepancyBand.ESCALATE

    def test_band_escalate_boundary_five_percent(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("5.0")) == DiscrepancyBand.ESCALATE

    def test_band_critical_over_fifteen(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("20.0")) == DiscrepancyBand.CRITICAL

    def test_band_critical_boundary_fifteen_percent(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("15.0")) == DiscrepancyBand.CRITICAL

    def test_band_critical_extreme_overcharge(self):
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("88.9")) == DiscrepancyBand.CRITICAL

    def test_band_negative_discrepancy_undercharge(self):
        """Negative discrepancy (undercharge) should use absolute value."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        # -3% means vendor undercharged -- still warrants investigation
        assert classify_discrepancy_band(Decimal("-3.0")) == DiscrepancyBand.INVESTIGATE

    def test_band_enum_values(self):
        from apps.api.src.domains.logicore.models.audit import DiscrepancyBand

        assert DiscrepancyBand.AUTO_APPROVE.value == "auto_approve"
        assert DiscrepancyBand.INVESTIGATE.value == "investigate"
        assert DiscrepancyBand.ESCALATE.value == "escalate"
        assert DiscrepancyBand.CRITICAL.value == "critical"


class TestContractRate:
    """Contract rate extracted from RAG."""

    def test_create_contract_rate(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        rate = ContractRate(
            contract_id="CTR-2024-001",
            rate=Decimal("0.45"),
            currency="EUR",
            unit="kg",
            cargo_type="pharmaceutical",
            min_volume=Decimal("5000"),
            clearance_level=3,
        )
        assert rate.rate == Decimal("0.45")
        assert rate.currency == "EUR"
        assert rate.unit == "kg"

    def test_contract_rate_without_optional_fields(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        rate = ContractRate(
            contract_id="CTR-2024-002",
            rate=Decimal("1.20"),
            currency="EUR",
            unit="pallet",
        )
        assert rate.min_volume is None
        assert rate.clearance_level == 1  # default
        assert rate.cargo_type is None

    def test_contract_rate_serialization(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        rate = ContractRate(
            contract_id="CTR-2024-001",
            rate=Decimal("0.45"),
            currency="EUR",
            unit="kg",
        )
        data = rate.model_dump()
        assert data["contract_id"] == "CTR-2024-001"
        assert data["rate"] == Decimal("0.45")

    def test_contract_rate_json_serialization(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        rate = ContractRate(
            contract_id="CTR-2024-001",
            rate=Decimal("0.45"),
            currency="EUR",
            unit="kg",
        )
        json_str = rate.model_dump_json()
        assert "CTR-2024-001" in json_str

    def test_contract_rate_clearance_level_bounds(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        with pytest.raises(ValidationError):
            ContractRate(
                contract_id="CTR-001",
                rate=Decimal("0.45"),
                currency="EUR",
                unit="kg",
                clearance_level=5,  # out of range
            )

    def test_contract_rate_negative_rate_rejected(self):
        from apps.api.src.domains.logicore.models.audit import ContractRate

        with pytest.raises(ValidationError):
            ContractRate(
                contract_id="CTR-001",
                rate=Decimal("-0.10"),
                currency="EUR",
                unit="kg",
            )


class TestLineItem:
    """Invoice line item -- actual billing data from SQL."""

    def test_create_line_item(self):
        from apps.api.src.domains.logicore.models.audit import LineItem

        item = LineItem(
            description="Pharmaceutical cargo transport",
            quantity=Decimal("8400"),
            unit="kg",
            unit_price=Decimal("0.52"),
            total=Decimal("4368.00"),
            cargo_type="pharmaceutical",
        )
        assert item.quantity == Decimal("8400")
        assert item.unit_price == Decimal("0.52")

    def test_line_item_computed_total(self):
        """Total should match quantity * unit_price."""
        from apps.api.src.domains.logicore.models.audit import LineItem

        item = LineItem(
            description="Standard cargo",
            quantity=Decimal("1000"),
            unit="kg",
            unit_price=Decimal("0.50"),
            total=Decimal("500.00"),
        )
        assert item.total == item.quantity * item.unit_price


class TestInvoice:
    """Invoice model with line items."""

    def test_create_invoice(self):
        from apps.api.src.domains.logicore.models.audit import Invoice, LineItem

        invoice = Invoice(
            invoice_id="INV-2024-0847",
            vendor="PharmaCorp",
            contract_id="CTR-2024-001",
            issue_date=datetime(2024, 11, 15, tzinfo=UTC),
            total_amount=Decimal("4368.00"),
            currency="EUR",
            line_items=[
                LineItem(
                    description="Pharmaceutical cargo transport",
                    quantity=Decimal("8400"),
                    unit="kg",
                    unit_price=Decimal("0.52"),
                    total=Decimal("4368.00"),
                    cargo_type="pharmaceutical",
                ),
            ],
        )
        assert invoice.invoice_id == "INV-2024-0847"
        assert len(invoice.line_items) == 1

    def test_invoice_multiple_line_items(self):
        from apps.api.src.domains.logicore.models.audit import Invoice, LineItem

        invoice = Invoice(
            invoice_id="INV-2024-0900",
            vendor="CargoFlex",
            contract_id="CTR-2024-003",
            issue_date=datetime(2024, 12, 1, tzinfo=UTC),
            total_amount=Decimal("7500.00"),
            currency="EUR",
            line_items=[
                LineItem(
                    description="Pallet transport",
                    quantity=Decimal("100"),
                    unit="pallet",
                    unit_price=Decimal("50.00"),
                    total=Decimal("5000.00"),
                ),
                LineItem(
                    description="Insurance surcharge",
                    quantity=Decimal("1"),
                    unit="flat",
                    unit_price=Decimal("2500.00"),
                    total=Decimal("2500.00"),
                ),
            ],
        )
        assert len(invoice.line_items) == 2
        assert invoice.total_amount == Decimal("7500.00")

    def test_invoice_serialization_roundtrip(self):
        from apps.api.src.domains.logicore.models.audit import Invoice, LineItem

        invoice = Invoice(
            invoice_id="INV-2024-0847",
            vendor="PharmaCorp",
            contract_id="CTR-2024-001",
            issue_date=datetime(2024, 11, 15, tzinfo=UTC),
            total_amount=Decimal("4368.00"),
            currency="EUR",
            line_items=[
                LineItem(
                    description="Test",
                    quantity=Decimal("100"),
                    unit="kg",
                    unit_price=Decimal("1.00"),
                    total=Decimal("100.00"),
                ),
            ],
        )
        data = invoice.model_dump()
        restored = Invoice(**data)
        assert restored.invoice_id == invoice.invoice_id
        assert restored.line_items[0].quantity == invoice.line_items[0].quantity

    def test_invoice_empty_line_items_rejected(self):
        from apps.api.src.domains.logicore.models.audit import Invoice

        with pytest.raises(ValidationError):
            Invoice(
                invoice_id="INV-001",
                vendor="Test",
                contract_id="CTR-001",
                issue_date=datetime(2024, 1, 1, tzinfo=UTC),
                total_amount=Decimal("100"),
                currency="EUR",
                line_items=[],  # at least one required
            )

    def test_invoice_negative_total_rejected(self):
        from apps.api.src.domains.logicore.models.audit import Invoice, LineItem

        with pytest.raises(ValidationError):
            Invoice(
                invoice_id="INV-001",
                vendor="Test",
                contract_id="CTR-001",
                issue_date=datetime(2024, 1, 1, tzinfo=UTC),
                total_amount=Decimal("-100"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="Test",
                        quantity=Decimal("1"),
                        unit="kg",
                        unit_price=Decimal("1.00"),
                        total=Decimal("1.00"),
                    ),
                ],
            )


class TestDiscrepancy:
    """Discrepancy found by auditor."""

    def test_create_discrepancy(self):
        from apps.api.src.domains.logicore.models.audit import Discrepancy, DiscrepancyBand

        disc = Discrepancy(
            line_item_index=0,
            description="Pharmaceutical cargo transport",
            expected_rate=Decimal("0.45"),
            actual_rate=Decimal("0.52"),
            expected_total=Decimal("3780.00"),
            actual_total=Decimal("4368.00"),
            difference=Decimal("588.00"),
            percentage=Decimal("15.56"),
            band=DiscrepancyBand.CRITICAL,
            currency="EUR",
        )
        assert disc.difference == Decimal("588.00")
        assert disc.band == DiscrepancyBand.CRITICAL

    def test_discrepancy_auto_approve_band(self):
        from apps.api.src.domains.logicore.models.audit import Discrepancy, DiscrepancyBand

        disc = Discrepancy(
            line_item_index=0,
            description="Standard transport",
            expected_rate=Decimal("0.45"),
            actual_rate=Decimal("0.4545"),
            expected_total=Decimal("4500.00"),
            actual_total=Decimal("4545.00"),
            difference=Decimal("45.00"),
            percentage=Decimal("0.99"),
            band=DiscrepancyBand.AUTO_APPROVE,
            currency="EUR",
        )
        assert disc.band == DiscrepancyBand.AUTO_APPROVE

    def test_discrepancy_investigate_band(self):
        from apps.api.src.domains.logicore.models.audit import Discrepancy, DiscrepancyBand

        disc = Discrepancy(
            line_item_index=0,
            description="Pallet transport",
            expected_rate=Decimal("50.00"),
            actual_rate=Decimal("52.00"),
            expected_total=Decimal("5000.00"),
            actual_total=Decimal("5200.00"),
            difference=Decimal("200.00"),
            percentage=Decimal("4.0"),
            band=DiscrepancyBand.INVESTIGATE,
            currency="EUR",
        )
        assert disc.band == DiscrepancyBand.INVESTIGATE

    def test_discrepancy_escalate_band(self):
        from apps.api.src.domains.logicore.models.audit import Discrepancy, DiscrepancyBand

        disc = Discrepancy(
            line_item_index=0,
            description="Container transport",
            expected_rate=Decimal("100.00"),
            actual_rate=Decimal("110.00"),
            expected_total=Decimal("10000.00"),
            actual_total=Decimal("11000.00"),
            difference=Decimal("1000.00"),
            percentage=Decimal("10.0"),
            band=DiscrepancyBand.ESCALATE,
            currency="EUR",
        )
        assert disc.band == DiscrepancyBand.ESCALATE

    def test_discrepancy_serialization(self):
        from apps.api.src.domains.logicore.models.audit import Discrepancy, DiscrepancyBand

        disc = Discrepancy(
            line_item_index=0,
            description="Test",
            expected_rate=Decimal("1.00"),
            actual_rate=Decimal("1.20"),
            expected_total=Decimal("100.00"),
            actual_total=Decimal("120.00"),
            difference=Decimal("20.00"),
            percentage=Decimal("20.0"),
            band=DiscrepancyBand.CRITICAL,
            currency="EUR",
        )
        data = disc.model_dump()
        assert data["band"] == "critical"
        assert data["currency"] == "EUR"


class TestApprovalDecision:
    """HITL approval/rejection."""

    def test_create_approval(self):
        from apps.api.src.domains.logicore.models.audit import ApprovalDecision

        decision = ApprovalDecision(
            approved=True,
            reviewer_id="martin.lang",
            notes="Verified. Vendor overcharged. Dispute and request credit note.",
            decided_at=datetime(2024, 11, 16, 10, 30, tzinfo=UTC),
        )
        assert decision.approved is True
        assert decision.reviewer_id == "martin.lang"

    def test_create_rejection(self):
        from apps.api.src.domains.logicore.models.audit import ApprovalDecision

        decision = ApprovalDecision(
            approved=False,
            reviewer_id="anna.kowalska",
            notes="Rate difference is covered by amendment CTR-2024-001-A.",
            decided_at=datetime(2024, 11, 16, 14, 0, tzinfo=UTC),
        )
        assert decision.approved is False

    def test_approval_auto_sets_timestamp(self):
        from apps.api.src.domains.logicore.models.audit import ApprovalDecision

        decision = ApprovalDecision(
            approved=True,
            reviewer_id="cfo",
        )
        assert decision.decided_at is not None

    def test_approval_serialization(self):
        from apps.api.src.domains.logicore.models.audit import ApprovalDecision

        decision = ApprovalDecision(
            approved=True,
            reviewer_id="cfo",
            notes="Confirmed.",
        )
        data = decision.model_dump()
        assert data["approved"] is True
        assert "decided_at" in data


class TestAuditReport:
    """Final audit report."""

    def test_create_report_with_discrepancies(self):
        from apps.api.src.domains.logicore.models.audit import (
            ApprovalDecision,
            AuditReport,
            Discrepancy,
            DiscrepancyBand,
        )

        report = AuditReport(
            run_id="run-001",
            invoice_id="INV-2024-0847",
            summary="Invoice INV-2024-0847 has 1 discrepancy totaling EUR 588.00.",
            discrepancies=[
                Discrepancy(
                    line_item_index=0,
                    description="Pharmaceutical cargo",
                    expected_rate=Decimal("0.45"),
                    actual_rate=Decimal("0.52"),
                    expected_total=Decimal("3780.00"),
                    actual_total=Decimal("4368.00"),
                    difference=Decimal("588.00"),
                    percentage=Decimal("15.56"),
                    band=DiscrepancyBand.CRITICAL,
                    currency="EUR",
                ),
            ],
            total_discrepancy=Decimal("588.00"),
            max_band=DiscrepancyBand.CRITICAL,
            approval=ApprovalDecision(
                approved=True,
                reviewer_id="martin.lang",
                notes="Verified.",
            ),
            created_at=datetime(2024, 11, 16, 11, 0, tzinfo=UTC),
        )
        assert report.total_discrepancy == Decimal("588.00")
        assert report.max_band == DiscrepancyBand.CRITICAL
        assert report.approval.approved is True

    def test_create_report_no_discrepancies(self):
        from apps.api.src.domains.logicore.models.audit import AuditReport, DiscrepancyBand

        report = AuditReport(
            run_id="run-002",
            invoice_id="INV-2024-0850",
            summary="Invoice INV-2024-0850 is within tolerance. No discrepancies found.",
            discrepancies=[],
            total_discrepancy=Decimal("0.00"),
            max_band=DiscrepancyBand.AUTO_APPROVE,
        )
        assert len(report.discrepancies) == 0
        assert report.approval is None

    def test_report_serialization_roundtrip(self):
        from apps.api.src.domains.logicore.models.audit import AuditReport, DiscrepancyBand

        report = AuditReport(
            run_id="run-003",
            invoice_id="INV-001",
            summary="Clean invoice.",
            discrepancies=[],
            total_discrepancy=Decimal("0.00"),
            max_band=DiscrepancyBand.AUTO_APPROVE,
        )
        data = report.model_dump()
        restored = AuditReport(**data)
        assert restored.run_id == report.run_id
        assert restored.max_band == report.max_band

    def test_report_json_includes_all_fields(self):
        from apps.api.src.domains.logicore.models.audit import AuditReport, DiscrepancyBand

        report = AuditReport(
            run_id="run-004",
            invoice_id="INV-002",
            summary="Test.",
            discrepancies=[],
            total_discrepancy=Decimal("0.00"),
            max_band=DiscrepancyBand.AUTO_APPROVE,
        )
        json_str = report.model_dump_json()
        assert "run_id" in json_str
        assert "invoice_id" in json_str
        assert "max_band" in json_str


class TestDiscrepancyBandClassification:
    """Comprehensive band classification with 5+ cases per band."""

    def test_auto_approve_band_cases(self):
        """5 cases in the <1% auto-approve band."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        cases = [
            Decimal("0.0"),
            Decimal("0.1"),
            Decimal("0.3"),
            Decimal("0.5"),
            Decimal("0.99"),
        ]
        for pct in cases:
            assert classify_discrepancy_band(pct) == DiscrepancyBand.AUTO_APPROVE, (
                f"Expected AUTO_APPROVE for {pct}%"
            )

    def test_investigate_band_cases(self):
        """5 cases in the 1-5% investigate band."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        cases = [
            Decimal("1.0"),
            Decimal("2.0"),
            Decimal("3.5"),
            Decimal("4.0"),
            Decimal("4.99"),
        ]
        for pct in cases:
            assert classify_discrepancy_band(pct) == DiscrepancyBand.INVESTIGATE, (
                f"Expected INVESTIGATE for {pct}%"
            )

    def test_escalate_band_cases(self):
        """5 cases in the 5-15% escalation band."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        cases = [
            Decimal("5.0"),
            Decimal("7.5"),
            Decimal("10.0"),
            Decimal("12.0"),
            Decimal("14.99"),
        ]
        for pct in cases:
            assert classify_discrepancy_band(pct) == DiscrepancyBand.ESCALATE, (
                f"Expected ESCALATE for {pct}%"
            )

    def test_critical_band_cases(self):
        """5 cases in the >15% critical band."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        cases = [
            Decimal("15.0"),
            Decimal("20.0"),
            Decimal("50.0"),
            Decimal("88.9"),
            Decimal("100.0"),
        ]
        for pct in cases:
            assert classify_discrepancy_band(pct) == DiscrepancyBand.CRITICAL, (
                f"Expected CRITICAL for {pct}%"
            )

    def test_negative_percentages_use_absolute_value(self):
        """Negative discrepancy (undercharge) classified by absolute value."""
        from apps.api.src.domains.logicore.models.audit import (
            DiscrepancyBand,
            classify_discrepancy_band,
        )

        assert classify_discrepancy_band(Decimal("-0.5")) == DiscrepancyBand.AUTO_APPROVE
        assert classify_discrepancy_band(Decimal("-3.0")) == DiscrepancyBand.INVESTIGATE
        assert classify_discrepancy_band(Decimal("-10.0")) == DiscrepancyBand.ESCALATE
        assert classify_discrepancy_band(Decimal("-20.0")) == DiscrepancyBand.CRITICAL
