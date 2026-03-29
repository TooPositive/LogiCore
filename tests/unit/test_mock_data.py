"""Tests for mock invoice and contract data.

Validates: all 4 discrepancy bands covered with 5+ invoices each,
contracts load correctly, invoice-contract relationships are valid.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "mock-invoices"


class TestMockInvoices:
    """Mock invoice data validation."""

    @pytest.fixture
    def invoices(self) -> list[dict]:
        with open(DATA_DIR / "invoices.json") as f:
            return json.load(f)

    @pytest.fixture
    def contracts(self) -> list[dict]:
        with open(DATA_DIR / "contracts.json") as f:
            return json.load(f)

    def test_invoices_file_loads(self, invoices):
        assert len(invoices) >= 20, f"Need 20+ invoices, got {len(invoices)}"

    def test_contracts_file_loads(self, contracts):
        assert len(contracts) >= 5, f"Need 5+ contracts, got {len(contracts)}"

    def test_all_invoices_have_required_fields(self, invoices):
        required = {
            "invoice_id", "vendor", "contract_id", "issue_date",
            "total_amount", "currency", "line_items",
        }
        for inv in invoices:
            missing = required - set(inv.keys())
            assert not missing, f"{inv['invoice_id']} missing: {missing}"

    def test_all_contracts_have_required_fields(self, contracts):
        required = {"contract_id", "vendor", "rates", "effective_from", "effective_to"}
        for ctr in contracts:
            missing = required - set(ctr.keys())
            assert not missing, f"{ctr['contract_id']} missing: {missing}"

    def test_every_invoice_references_existing_contract(self, invoices, contracts):
        contract_ids = {c["contract_id"] for c in contracts}
        for inv in invoices:
            assert inv["contract_id"] in contract_ids, (
                f"{inv['invoice_id']} references nonexistent {inv['contract_id']}"
            )

    def test_at_least_5_auto_approve_invoices(self, invoices, contracts):
        """Verify 5+ invoices in the <1% band."""
        count = self._count_band(invoices, contracts, "auto_approve")
        assert count >= 5, f"Need 5+ AUTO_APPROVE invoices, got {count}"

    def test_at_least_5_investigate_invoices(self, invoices, contracts):
        """Verify 5+ invoices in the 1-5% band."""
        count = self._count_band(invoices, contracts, "investigate")
        assert count >= 5, f"Need 5+ INVESTIGATE invoices, got {count}"

    def test_at_least_5_escalate_invoices(self, invoices, contracts):
        """Verify 5+ invoices in the 5-15% band."""
        count = self._count_band(invoices, contracts, "escalate")
        assert count >= 5, f"Need 5+ ESCALATE invoices, got {count}"

    def test_at_least_5_critical_invoices(self, invoices, contracts):
        """Verify 5+ invoices in the >15% band."""
        count = self._count_band(invoices, contracts, "critical")
        assert count >= 5, f"Need 5+ CRITICAL invoices, got {count}"

    def test_at_least_one_multi_line_invoice(self, invoices):
        multi_line = [inv for inv in invoices if len(inv["line_items"]) > 1]
        assert len(multi_line) >= 1, "Need at least 1 multi-line invoice"

    def test_at_least_one_exact_match_invoice(self, invoices, contracts):
        """At least one invoice with 0% discrepancy."""
        rate_map = self._build_rate_map(contracts)
        exact_matches = 0
        for inv in invoices:
            for item in inv["line_items"]:
                cargo = item.get("cargo_type")
                ctr_id = inv["contract_id"]
                key = (ctr_id, cargo)
                if key in rate_map:
                    contract_rate = rate_map[key]
                    invoice_rate = Decimal(item["unit_price"])
                    if invoice_rate == contract_rate:
                        exact_matches += 1
        assert exact_matches >= 1, "Need at least 1 exact-match line item"

    def test_invoice_ids_unique(self, invoices):
        ids = [inv["invoice_id"] for inv in invoices]
        assert len(ids) == len(set(ids)), "Duplicate invoice IDs found"

    def test_line_items_not_empty(self, invoices):
        for inv in invoices:
            assert len(inv["line_items"]) >= 1, f"{inv['invoice_id']} has 0 line items"

    def _build_rate_map(self, contracts: list[dict]) -> dict[tuple[str, str], Decimal]:
        """Build (contract_id, cargo_type) -> rate mapping."""
        rate_map = {}
        for ctr in contracts:
            for rate_info in ctr["rates"]:
                key = (ctr["contract_id"], rate_info["cargo_type"])
                rate_map[key] = Decimal(rate_info["rate"])
        return rate_map

    def _count_band(self, invoices: list[dict], contracts: list[dict], band: str) -> int:
        """Count invoices with at least one line item in the given band."""
        from apps.api.src.domains.logicore.models.audit import classify_discrepancy_band

        rate_map = self._build_rate_map(contracts)
        count = 0
        for inv in invoices:
            for item in inv["line_items"]:
                cargo = item.get("cargo_type")
                ctr_id = inv["contract_id"]
                key = (ctr_id, cargo)
                if key not in rate_map:
                    continue
                contract_rate = rate_map[key]
                invoice_rate = Decimal(item["unit_price"])
                if contract_rate == 0:
                    continue
                pct = ((invoice_rate - contract_rate) / contract_rate) * Decimal("100")
                result = classify_discrepancy_band(pct)
                if result.value == band:
                    count += 1
                    break  # count each invoice once
        return count
