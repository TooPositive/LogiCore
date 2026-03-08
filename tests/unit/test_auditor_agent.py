"""Tests for Auditor Agent -- rate comparison and discrepancy classification.

The auditor compares extracted contract rates against actual invoice billing,
classifies discrepancies into 4 bands, and determines the overall action.
"""

from decimal import Decimal

from apps.api.src.domain.audit import ContractRate, DiscrepancyBand, Invoice, LineItem


def _make_invoice(
    invoice_id: str = "INV-001",
    contract_id: str = "CTR-001",
    line_items: list[LineItem] | None = None,
) -> Invoice:
    """Helper to create test invoices."""
    if line_items is None:
        line_items = [
            LineItem(
                description="Test cargo",
                quantity=Decimal("1000"),
                unit="kg",
                unit_price=Decimal("0.50"),
                total=Decimal("500.00"),
                cargo_type="general",
            )
        ]
    total = sum(item.total for item in line_items)
    return Invoice(
        invoice_id=invoice_id,
        vendor="TestVendor",
        contract_id=contract_id,
        issue_date="2024-11-15T00:00:00Z",
        total_amount=total,
        currency="EUR",
        line_items=line_items,
    )


def _make_rate(
    contract_id: str = "CTR-001",
    rate: str = "0.45",
    cargo_type: str = "general",
) -> ContractRate:
    """Helper to create test contract rates."""
    return ContractRate(
        contract_id=contract_id,
        rate=Decimal(rate),
        currency="EUR",
        unit="kg",
        cargo_type=cargo_type,
    )


class TestAuditorAgent:
    """Auditor agent compares rates and classifies discrepancies."""

    async def test_no_discrepancy_when_rates_match(self):
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("1000"),
                unit="kg",
                unit_price=Decimal("0.45"),
                total=Decimal("450.00"),
                cargo_type="general",
            )
        ])
        rates = [_make_rate(rate="0.45")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 0

    async def test_auto_approve_band_small_overcharge(self):
        """<1% difference -> AUTO_APPROVE."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("10000"),
                unit="kg",
                unit_price=Decimal("0.4505"),
                total=Decimal("4505.00"),
                cargo_type="general",
            )
        ])
        rates = [_make_rate(rate="0.45")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.AUTO_APPROVE

    async def test_investigate_band_moderate_overcharge(self):
        """1-5% difference -> INVESTIGATE."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("10000"),
                unit="kg",
                unit_price=Decimal("0.46"),
                total=Decimal("4600.00"),
                cargo_type="general",
            )
        ])
        rates = [_make_rate(rate="0.45")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.INVESTIGATE

    async def test_escalate_band_significant_overcharge(self):
        """5-15% difference -> ESCALATE."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("10000"),
                unit="kg",
                unit_price=Decimal("0.495"),
                total=Decimal("4950.00"),
                cargo_type="general",
            )
        ])
        rates = [_make_rate(rate="0.45")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.ESCALATE

    async def test_critical_band_major_overcharge(self):
        """>15% difference -> CRITICAL (the spec scenario: 0.45 vs 0.52)."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Pharmaceutical cargo transport",
                quantity=Decimal("8400"),
                unit="kg",
                unit_price=Decimal("0.52"),
                total=Decimal("4368.00"),
                cargo_type="pharmaceutical",
            )
        ])
        rates = [_make_rate(rate="0.45", cargo_type="pharmaceutical")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.CRITICAL
        assert discrepancies[0].difference == Decimal("588.00")

    async def test_discrepancy_calculates_correct_amounts(self):
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Pharma",
                quantity=Decimal("8400"),
                unit="kg",
                unit_price=Decimal("0.52"),
                total=Decimal("4368.00"),
                cargo_type="pharmaceutical",
            )
        ])
        rates = [_make_rate(rate="0.45", cargo_type="pharmaceutical")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        d = discrepancies[0]
        assert d.expected_rate == Decimal("0.45")
        assert d.actual_rate == Decimal("0.52")
        assert d.expected_total == Decimal("3780.00")
        assert d.actual_total == Decimal("4368.00")
        assert d.difference == Decimal("588.00")
        assert d.currency == "EUR"

    async def test_multiple_line_items_mixed_bands(self):
        """One clean line, one overcharged -> only overcharged flagged."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(
            contract_id="CTR-002",
            line_items=[
                LineItem(
                    description="General pallets",
                    quantity=Decimal("80"),
                    unit="pallet",
                    unit_price=Decimal("50.00"),
                    total=Decimal("4000.00"),
                    cargo_type="general",
                ),
                LineItem(
                    description="Hazmat pallets",
                    quantity=Decimal("30"),
                    unit="pallet",
                    unit_price=Decimal("105.00"),
                    total=Decimal("3150.00"),
                    cargo_type="hazardous",
                ),
            ],
        )
        rates = [
            ContractRate(
                contract_id="CTR-002",
                rate=Decimal("50.00"),
                currency="EUR",
                unit="pallet",
                cargo_type="general",
            ),
            ContractRate(
                contract_id="CTR-002",
                rate=Decimal("85.00"),
                currency="EUR",
                unit="pallet",
                cargo_type="hazardous",
            ),
        ]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        # General pallets: exact match, no discrepancy
        # Hazmat pallets: 105 vs 85 = 23.5% over -> CRITICAL
        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.CRITICAL
        assert discrepancies[0].description == "Hazmat pallets"

    async def test_undercharge_also_flagged(self):
        """Undercharges are flagged too (vendor billed less than contract)."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("10000"),
                unit="kg",
                unit_price=Decimal("0.40"),
                total=Decimal("4000.00"),
                cargo_type="general",
            )
        ])
        rates = [_make_rate(rate="0.45")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        # 0.40 vs 0.45 = -11.1% -> ESCALATE band
        assert len(discrepancies) == 1
        assert discrepancies[0].band == DiscrepancyBand.ESCALATE

    async def test_no_matching_rate_skips_line_item(self):
        """Line items without matching contract rate are skipped."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Unknown cargo",
                quantity=Decimal("100"),
                unit="kg",
                unit_price=Decimal("10.00"),
                total=Decimal("1000.00"),
                cargo_type="unknown_type",
            )
        ])
        rates = [_make_rate(rate="0.45", cargo_type="general")]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        assert len(discrepancies) == 0

    async def test_auditor_is_idempotent(self):
        """Same input produces same output (crash recovery safety)."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        invoice = _make_invoice(line_items=[
            LineItem(
                description="Test",
                quantity=Decimal("8400"),
                unit="kg",
                unit_price=Decimal("0.52"),
                total=Decimal("4368.00"),
                cargo_type="pharmaceutical",
            )
        ])
        rates = [_make_rate(rate="0.45", cargo_type="pharmaceutical")]

        agent = AuditorAgent()
        d1 = await agent.compare(invoice, rates)
        d2 = await agent.compare(invoice, rates)

        assert len(d1) == len(d2)
        assert d1[0].difference == d2[0].difference
        assert d1[0].band == d2[0].band

    async def test_five_auto_approve_cases(self):
        """Comprehensive: 5 invoices in <1% band."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        agent = AuditorAgent()
        percentages = ["0.4502", "0.4510", "0.4520", "0.4540", "0.4544"]

        for price in percentages:
            invoice = _make_invoice(line_items=[
                LineItem(
                    description="Test",
                    quantity=Decimal("10000"),
                    unit="kg",
                    unit_price=Decimal(price),
                    total=Decimal(price) * Decimal("10000"),
                    cargo_type="general",
                )
            ])
            rates = [_make_rate(rate="0.45")]
            discrepancies = await agent.compare(invoice, rates)
            if discrepancies:
                assert discrepancies[0].band == DiscrepancyBand.AUTO_APPROVE, (
                    f"Expected AUTO_APPROVE for rate {price}"
                )

    async def test_five_critical_cases(self):
        """Comprehensive: 5 invoices in >15% band."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent

        agent = AuditorAgent()
        prices = ["0.52", "0.55", "0.60", "0.75", "0.85"]

        for price in prices:
            invoice = _make_invoice(line_items=[
                LineItem(
                    description="Test",
                    quantity=Decimal("10000"),
                    unit="kg",
                    unit_price=Decimal(price),
                    total=Decimal(price) * Decimal("10000"),
                    cargo_type="general",
                )
            ])
            rates = [_make_rate(rate="0.45")]
            discrepancies = await agent.compare(invoice, rates)
            assert len(discrepancies) == 1
            assert discrepancies[0].band == DiscrepancyBand.CRITICAL, (
                f"Expected CRITICAL for rate {price} vs 0.45"
            )
