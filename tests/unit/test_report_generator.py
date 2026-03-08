"""Tests for Report Generator -- creates audit reports from workflow state.

The report generator takes the full audit state (invoice, discrepancies,
approval) and produces a structured AuditReport.
"""

from decimal import Decimal

from apps.api.src.domain.audit import (
    ApprovalDecision,
    Discrepancy,
    DiscrepancyBand,
    Invoice,
    LineItem,
)


class TestReportGenerator:
    """Report generator produces AuditReport from audit state."""

    async def test_generate_report_with_discrepancies(self):
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        report = await gen.generate(
            run_id="run-001",
            invoice=Invoice(
                invoice_id="INV-2024-0847",
                vendor="PharmaCorp",
                contract_id="CTR-2024-001",
                issue_date="2024-11-15T00:00:00Z",
                total_amount=Decimal("4368.00"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="Pharma transport",
                        quantity=Decimal("8400"),
                        unit="kg",
                        unit_price=Decimal("0.52"),
                        total=Decimal("4368.00"),
                        cargo_type="pharmaceutical",
                    ),
                ],
            ),
            discrepancies=[
                Discrepancy(
                    line_item_index=0,
                    description="Pharma transport",
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
            approval=ApprovalDecision(
                approved=True,
                reviewer_id="martin.lang",
                notes="Verified.",
            ),
        )

        assert report.run_id == "run-001"
        assert report.invoice_id == "INV-2024-0847"
        assert report.total_discrepancy == Decimal("588.00")
        assert report.max_band == DiscrepancyBand.CRITICAL
        assert report.approval is not None
        assert report.approval.approved is True
        assert "INV-2024-0847" in report.summary

    async def test_generate_report_no_discrepancies(self):
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        report = await gen.generate(
            run_id="run-002",
            invoice=Invoice(
                invoice_id="INV-2024-0850",
                vendor="TransEuropa",
                contract_id="CTR-2024-003",
                issue_date="2024-12-01T00:00:00Z",
                total_amount=Decimal("6000.00"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="Refrigerated",
                        quantity=Decimal("5000"),
                        unit="kg",
                        unit_price=Decimal("1.20"),
                        total=Decimal("6000.00"),
                    ),
                ],
            ),
            discrepancies=[],
        )

        assert report.total_discrepancy == Decimal("0")
        assert report.max_band == DiscrepancyBand.AUTO_APPROVE
        assert report.approval is None
        assert len(report.discrepancies) == 0

    async def test_generate_report_multiple_discrepancies(self):
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        report = await gen.generate(
            run_id="run-003",
            invoice=Invoice(
                invoice_id="INV-003",
                vendor="Test",
                contract_id="CTR-003",
                issue_date="2024-01-01T00:00:00Z",
                total_amount=Decimal("10000.00"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="A",
                        quantity=Decimal("100"),
                        unit="pallet",
                        unit_price=Decimal("52.00"),
                        total=Decimal("5200.00"),
                    ),
                    LineItem(
                        description="B",
                        quantity=Decimal("30"),
                        unit="pallet",
                        unit_price=Decimal("105.00"),
                        total=Decimal("3150.00"),
                    ),
                ],
            ),
            discrepancies=[
                Discrepancy(
                    line_item_index=0,
                    description="A",
                    expected_rate=Decimal("50.00"),
                    actual_rate=Decimal("52.00"),
                    expected_total=Decimal("5000.00"),
                    actual_total=Decimal("5200.00"),
                    difference=Decimal("200.00"),
                    percentage=Decimal("4.0"),
                    band=DiscrepancyBand.INVESTIGATE,
                    currency="EUR",
                ),
                Discrepancy(
                    line_item_index=1,
                    description="B",
                    expected_rate=Decimal("85.00"),
                    actual_rate=Decimal("105.00"),
                    expected_total=Decimal("2550.00"),
                    actual_total=Decimal("3150.00"),
                    difference=Decimal("600.00"),
                    percentage=Decimal("23.5"),
                    band=DiscrepancyBand.CRITICAL,
                    currency="EUR",
                ),
            ],
        )

        # Total discrepancy is sum of all differences
        assert report.total_discrepancy == Decimal("800.00")
        # Max band is the highest band across all discrepancies
        assert report.max_band == DiscrepancyBand.CRITICAL
        assert len(report.discrepancies) == 2

    async def test_generate_report_with_rejection(self):
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        report = await gen.generate(
            run_id="run-004",
            invoice=Invoice(
                invoice_id="INV-004",
                vendor="Test",
                contract_id="CTR-004",
                issue_date="2024-01-01T00:00:00Z",
                total_amount=Decimal("500.00"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="Test",
                        quantity=Decimal("1000"),
                        unit="kg",
                        unit_price=Decimal("0.50"),
                        total=Decimal("500.00"),
                    ),
                ],
            ),
            discrepancies=[
                Discrepancy(
                    line_item_index=0,
                    description="Test",
                    expected_rate=Decimal("0.45"),
                    actual_rate=Decimal("0.50"),
                    expected_total=Decimal("450.00"),
                    actual_total=Decimal("500.00"),
                    difference=Decimal("50.00"),
                    percentage=Decimal("11.1"),
                    band=DiscrepancyBand.ESCALATE,
                    currency="EUR",
                ),
            ],
            approval=ApprovalDecision(
                approved=False,
                reviewer_id="anna.kowalska",
                notes="Amendment covers this.",
            ),
        )

        assert report.approval is not None
        assert report.approval.approved is False

    async def test_report_summary_mentions_vendor(self):
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        report = await gen.generate(
            run_id="run-005",
            invoice=Invoice(
                invoice_id="INV-005",
                vendor="PharmaCorp",
                contract_id="CTR-005",
                issue_date="2024-01-01T00:00:00Z",
                total_amount=Decimal("100.00"),
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
            ),
            discrepancies=[],
        )

        assert "PharmaCorp" in report.summary or "INV-005" in report.summary

    async def test_report_is_idempotent(self):
        """Same inputs produce same output."""
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        kwargs = dict(
            run_id="run-006",
            invoice=Invoice(
                invoice_id="INV-006",
                vendor="Test",
                contract_id="CTR-006",
                issue_date="2024-01-01T00:00:00Z",
                total_amount=Decimal("100.00"),
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
            ),
            discrepancies=[],
        )

        r1 = await gen.generate(**kwargs)
        r2 = await gen.generate(**kwargs)

        assert r1.summary == r2.summary
        assert r1.total_discrepancy == r2.total_discrepancy
        assert r1.max_band == r2.max_band
