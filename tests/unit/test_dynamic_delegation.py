"""Tests for dynamic delegation -- compliance sub-agent with clearance filter.

The auditor can spawn a compliance sub-agent when it encounters an unknown
clause. The sub-agent gets temporary elevated clearance (scoped to the run),
but its return value is FILTERED to the parent's clearance level before
state merge. This is the #1 security risk in the entire project.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from apps.api.src.domain.audit import ContractRate, DiscrepancyBand


class TestClearanceFilter:
    """ClearanceFilter strips data above the parent's clearance level."""

    def test_filter_strips_clearance_3_from_clearance_2_state(self):
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        findings = [
            {"content": "Amendment +0.07/kg surcharge Q4", "clearance_level": 2},
            {"content": "Confidential vendor rebate terms", "clearance_level": 3},
            {"content": "Internal margin analysis", "clearance_level": 4},
        ]

        filtered = ClearanceFilter.filter(findings, parent_clearance=2)

        assert len(filtered) == 1
        assert filtered[0]["clearance_level"] == 2

    def test_filter_keeps_same_level_data(self):
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        findings = [
            {"content": "Public rate", "clearance_level": 1},
            {"content": "Internal rate", "clearance_level": 2},
        ]

        filtered = ClearanceFilter.filter(findings, parent_clearance=2)
        assert len(filtered) == 2

    def test_filter_returns_empty_when_all_above_clearance(self):
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        findings = [
            {"content": "Top secret", "clearance_level": 4},
        ]

        filtered = ClearanceFilter.filter(findings, parent_clearance=1)
        assert len(filtered) == 0

    def test_filter_handles_empty_input(self):
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        filtered = ClearanceFilter.filter([], parent_clearance=3)
        assert filtered == []

    def test_filter_preserves_content(self):
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        findings = [
            {"content": "Amendment details", "clearance_level": 1, "extra": "metadata"},
        ]

        filtered = ClearanceFilter.filter(findings, parent_clearance=2)
        assert filtered[0]["content"] == "Amendment details"
        assert filtered[0]["extra"] == "metadata"

    def test_filter_boundary_exact_clearance_level(self):
        """Data AT the parent's clearance level is kept."""
        from apps.api.src.graphs.clearance_filter import ClearanceFilter

        findings = [
            {"content": "Level 3 data", "clearance_level": 3},
        ]

        filtered = ClearanceFilter.filter(findings, parent_clearance=3)
        assert len(filtered) == 1


class TestNeedsLegalContext:
    """Determines when to trigger dynamic delegation."""

    def test_unknown_clause_triggers_delegation(self):
        from apps.api.src.graphs.compliance_subgraph import needs_legal_context

        discrepancies = [
            {
                "description": "Rate mismatch with unknown amendment clause",
                "band": DiscrepancyBand.ESCALATE.value,
                "percentage": Decimal("10.0"),
            }
        ]

        assert needs_legal_context(discrepancies) is True

    def test_simple_overcharge_does_not_trigger(self):
        from apps.api.src.graphs.compliance_subgraph import needs_legal_context

        discrepancies = [
            {
                "description": "Standard rate overcharge",
                "band": DiscrepancyBand.CRITICAL.value,
                "percentage": Decimal("20.0"),
            }
        ]

        assert needs_legal_context(discrepancies) is False

    def test_empty_discrepancies_does_not_trigger(self):
        from apps.api.src.graphs.compliance_subgraph import needs_legal_context

        assert needs_legal_context([]) is False

    def test_amendment_keyword_triggers(self):
        from apps.api.src.graphs.compliance_subgraph import needs_legal_context

        discrepancies = [
            {
                "description": "Rate differs from contract amendment",
                "band": DiscrepancyBand.INVESTIGATE.value,
                "percentage": Decimal("3.0"),
            }
        ]

        assert needs_legal_context(discrepancies) is True

    def test_surcharge_keyword_triggers(self):
        from apps.api.src.graphs.compliance_subgraph import needs_legal_context

        discrepancies = [
            {
                "description": "Possible temporary surcharge clause",
                "band": DiscrepancyBand.ESCALATE.value,
                "percentage": Decimal("8.0"),
            }
        ]

        assert needs_legal_context(discrepancies) is True


class TestComplianceSubgraph:
    """Compliance sub-agent graph for legal context retrieval."""

    async def test_compliance_subgraph_returns_findings(self):
        from apps.api.src.graphs.compliance_subgraph import run_compliance_check

        mock_retriever = AsyncMock()
        mock_retriever.search = AsyncMock(return_value=[
            MagicMock(
                content="Amendment dated 2024-09-15: temporary +EUR 0.07/kg surcharge for Q4",
                score=0.92,
                source="CTR-2024-001-A.pdf",
                document_id="doc-amendment",
            )
        ])

        findings = await run_compliance_check(
            contract_id="CTR-2024-001",
            query="amendments affecting rate for pharmaceutical cargo",
            retriever=mock_retriever,
            elevated_clearance=3,
        )

        assert len(findings) > 0
        content_lower = findings[0]["content"].lower()
        assert "amendment" in content_lower or "surcharge" in content_lower

    async def test_compliance_subgraph_applies_clearance_filter(self):
        """Findings are filtered to parent clearance before return."""
        from apps.api.src.graphs.compliance_subgraph import run_compliance_check

        mock_retriever = AsyncMock()
        mock_retriever.search = AsyncMock(return_value=[
            MagicMock(
                content="Public amendment info",
                score=0.9,
                source="public.pdf",
                document_id="doc-public",
                clearance_level=2,
            ),
            MagicMock(
                content="Confidential vendor terms",
                score=0.8,
                source="confidential.pdf",
                document_id="doc-secret",
                clearance_level=3,
            ),
        ])

        findings = await run_compliance_check(
            contract_id="CTR-2024-001",
            query="amendments",
            retriever=mock_retriever,
            elevated_clearance=3,
            parent_clearance=2,
        )

        # All findings should have clearance <= parent_clearance
        for f in findings:
            assert f["clearance_level"] <= 2

    async def test_compliance_subgraph_empty_results(self):
        from apps.api.src.graphs.compliance_subgraph import run_compliance_check

        mock_retriever = AsyncMock()
        mock_retriever.search = AsyncMock(return_value=[])

        findings = await run_compliance_check(
            contract_id="CTR-UNKNOWN",
            query="amendments",
            retriever=mock_retriever,
            elevated_clearance=3,
        )

        assert findings == []

    async def test_compliance_subgraph_is_idempotent(self):
        from apps.api.src.graphs.compliance_subgraph import run_compliance_check

        mock_retriever = AsyncMock()
        mock_retriever.search = AsyncMock(return_value=[
            MagicMock(
                content="Amendment info",
                score=0.9,
                source="amend.pdf",
                document_id="doc-1",
            )
        ])

        f1 = await run_compliance_check(
            contract_id="CTR-001",
            query="amendments",
            retriever=mock_retriever,
            elevated_clearance=3,
        )
        f2 = await run_compliance_check(
            contract_id="CTR-001",
            query="amendments",
            retriever=mock_retriever,
            elevated_clearance=3,
        )

        assert len(f1) == len(f2)
        assert f1[0]["content"] == f2[0]["content"]


class TestAuditorWithDelegation:
    """Auditor agent with conditional sub-agent spawn."""

    async def test_auditor_delegates_on_amendment_keyword(self):
        from apps.api.src.agents.auditor.comparator import AuditorAgent
        from apps.api.src.domain.audit import Invoice, LineItem

        invoice = Invoice(
            invoice_id="INV-001",
            vendor="PharmaCorp",
            contract_id="CTR-2024-001",
            issue_date="2024-11-15T00:00:00Z",
            total_amount=Decimal("4368.00"),
            currency="EUR",
            line_items=[
                LineItem(
                    description="Pharmaceutical cargo transport with amendment surcharge",
                    quantity=Decimal("8400"),
                    unit="kg",
                    unit_price=Decimal("0.52"),
                    total=Decimal("4368.00"),
                    cargo_type="pharmaceutical",
                ),
            ],
        )
        rates = [
            ContractRate(
                contract_id="CTR-2024-001",
                rate=Decimal("0.45"),
                currency="EUR",
                unit="kg",
                cargo_type="pharmaceutical",
            )
        ]

        agent = AuditorAgent()
        discrepancies = await agent.compare(invoice, rates)

        # The discrepancy still gets flagged -- delegation happens at graph level
        assert len(discrepancies) == 1
