"""Tests for audit graph -- LangGraph state machine wiring.

Tests graph structure: node ordering, edge routing, state transitions.
Uses MemorySaver (in-memory) for unit tests -- PostgreSQL checkpointer
is tested in integration tests.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestAuditGraphState:
    """Validate the AuditGraphState TypedDict schema."""

    def test_state_has_required_fields(self):
        from apps.api.src.graphs.state import AuditGraphState

        # TypedDict fields
        annotations = AuditGraphState.__annotations__
        required = {
            "invoice_id", "run_id", "status",
            "extracted_rates", "invoice_data", "discrepancies",
            "approval", "report",
        }
        for field in required:
            assert field in annotations, f"Missing field: {field}"

    def test_state_accepts_valid_data(self):
        from apps.api.src.graphs.state import AuditGraphState

        state: AuditGraphState = {
            "invoice_id": "INV-2024-0847",
            "run_id": "run-001",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
            "compliance_findings": [],
        }
        assert state["invoice_id"] == "INV-2024-0847"
        assert state["status"] == "extracting"


class TestAuditGraphStructure:
    """Test graph structure: nodes, edges, entry point."""

    def test_graph_has_all_nodes(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        node_names = set(compiled.get_graph().nodes.keys())

        expected_nodes = {"reader", "sql_agent", "auditor", "hitl_gate", "report"}
        for node in expected_nodes:
            assert node in node_names, f"Missing node: {node}"

    def test_graph_entry_point_is_reader(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        # Check that __start__ connects to reader
        start_edges = [
            e.target for e in graph_def.edges
            if e.source == "__start__"
        ]
        assert "reader" in start_edges

    def test_graph_edge_reader_to_sql(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        edges = [(e.source, e.target) for e in graph_def.edges]
        assert ("reader", "sql_agent") in edges

    def test_graph_edge_sql_to_auditor(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        edges = [(e.source, e.target) for e in graph_def.edges]
        assert ("sql_agent", "auditor") in edges

    def test_graph_edge_auditor_to_hitl(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        edges = [(e.source, e.target) for e in graph_def.edges]
        assert ("auditor", "hitl_gate") in edges

    def test_graph_edge_hitl_to_report(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        edges = [(e.source, e.target) for e in graph_def.edges]
        assert ("hitl_gate", "report") in edges

    def test_graph_edge_report_to_end(self):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph()
        compiled = graph.compile()
        graph_def = compiled.get_graph()

        edges = [(e.source, e.target) for e in graph_def.edges]
        assert ("report", "__end__") in edges


class TestAuditGraphExecution:
    """Test graph execution with mock agents."""

    @pytest.fixture
    def mock_deps(self):
        """Mock dependencies for all agents."""
        retriever = AsyncMock()
        retriever.search = AsyncMock(return_value=[
            MagicMock(
                content="Contract CTR-2024-001: rate EUR 0.45/kg pharmaceutical",
                score=0.95,
                source="CTR-2024-001.pdf",
                document_id="doc-1",
            )
        ])

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='[{"contract_id": "CTR-2024-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg", "cargo_type": "pharmaceutical", '
            '"clearance_level": 3}]'
        ))

        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-2024-0847",
            "vendor": "PharmaCorp",
            "contract_id": "CTR-2024-001",
            "issue_date": "2024-11-15T00:00:00Z",
            "total_amount": Decimal("4368.00"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[{
            "description": "Pharmaceutical cargo transport",
            "quantity": Decimal("8400"),
            "unit": "kg",
            "unit_price": Decimal("0.52"),
            "total": Decimal("4368.00"),
            "cargo_type": "pharmaceutical",
        }])

        return {"retriever": retriever, "llm": llm, "pool": pool}

    async def test_graph_runs_reader_node(self, mock_deps):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        compiled = graph.compile()

        result = await compiled.ainvoke({
            "invoice_id": "INV-2024-0847",
            "run_id": "test-run-001",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
            "compliance_findings": [],
        })

        # Reader should have populated extracted_rates
        assert len(result["extracted_rates"]) > 0
        # SQL agent should have fetched invoice
        assert result["invoice_data"] is not None
        # Auditor should have found discrepancies
        assert len(result["discrepancies"]) > 0
        # Report should be generated
        assert result["report"] is not None
        assert result["status"] == "completed"

    async def test_graph_transitions_through_all_nodes(self, mock_deps):
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        compiled = graph.compile()

        result = await compiled.ainvoke({
            "invoice_id": "INV-2024-0847",
            "run_id": "test-run-002",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
            "compliance_findings": [],
        })

        # Final status should be completed
        assert result["status"] == "completed"

    async def test_graph_handles_no_discrepancies(self, mock_deps):
        """When rates match, no discrepancy should be found."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        # Override invoice to match contract rate
        conn = await mock_deps["pool"].acquire().__aenter__()
        conn.fetch = AsyncMock(return_value=[{
            "description": "Pharmaceutical cargo transport",
            "quantity": Decimal("8400"),
            "unit": "kg",
            "unit_price": Decimal("0.45"),
            "total": Decimal("3780.00"),
            "cargo_type": "pharmaceutical",
        }])
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-2024-0850",
            "vendor": "PharmaCorp",
            "contract_id": "CTR-2024-001",
            "issue_date": "2024-12-01T00:00:00Z",
            "total_amount": Decimal("3780.00"),
            "currency": "EUR",
        })

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        compiled = graph.compile()

        result = await compiled.ainvoke({
            "invoice_id": "INV-2024-0850",
            "run_id": "test-run-003",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
            "compliance_findings": [],
        })

        assert len(result["discrepancies"]) == 0
        assert result["status"] == "completed"
