"""Tests for HITL gateway -- workflow blocks and resumes on human approval.

Uses LangGraph's interrupt() + MemorySaver to test the interrupt/resume pattern.
The graph pauses at hitl_gate, exposing the approval state. A human decision
is injected via Command(resume=...) to continue.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver


class TestHitlGateway:
    """HITL gateway blocks workflow until human approval."""

    @pytest.fixture
    def mock_deps(self):
        """Standard mock dependencies for graph execution."""
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

    async def test_hitl_blocks_at_gate(self, mock_deps):
        """Workflow stops at hitl_gate, exposing awaiting_approval status."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])
        config = {"configurable": {"thread_id": "test-hitl-001"}}

        result = await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-hitl-001",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
            },
            config=config,
        )

        # Workflow should have stopped before hitl_gate
        # Status should be "awaiting_approval" (set by auditor node)
        assert result["status"] == "awaiting_approval"
        # Report should NOT be generated yet
        assert result["report"] is None
        # But discrepancies should be calculated
        assert len(result["discrepancies"]) > 0

    async def test_hitl_resume_with_approval(self, mock_deps):
        """After approval, workflow continues to report generation."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])
        config = {"configurable": {"thread_id": "test-hitl-002"}}

        # Phase 1: run until blocked
        await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-hitl-002",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
            },
            config=config,
        )

        # Phase 2: resume with approval (pass None as input to continue)
        result = await compiled.ainvoke(None, config=config)

        # Workflow should complete
        assert result["status"] == "completed"
        assert result["report"] is not None

    async def test_hitl_state_persists_across_invocations(self, mock_deps):
        """State from before the interrupt survives in the checkpointer."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])
        config = {"configurable": {"thread_id": "test-hitl-003"}}

        # Phase 1: run until blocked
        await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-hitl-003",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
            },
            config=config,
        )

        # Get state from checkpointer
        state = await compiled.aget_state(config)
        assert state.values["invoice_id"] == "INV-2024-0847"
        assert len(state.values["discrepancies"]) > 0

    async def test_hitl_blocks_not_at_other_nodes(self, mock_deps):
        """Interrupt only happens before hitl_gate, not at other nodes."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])
        config = {"configurable": {"thread_id": "test-hitl-004"}}

        result = await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-hitl-004",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
            },
            config=config,
        )

        # Reader and SQL agent should have run
        assert len(result["extracted_rates"]) > 0
        assert result["invoice_data"] is not None
        # Auditor should have run
        assert len(result["discrepancies"]) > 0

    async def test_hitl_multiple_audits_independent(self, mock_deps):
        """Two audit runs don't interfere -- different thread_ids."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])

        config_a = {"configurable": {"thread_id": "audit-A"}}
        config_b = {"configurable": {"thread_id": "audit-B"}}

        init_state = {
            "invoice_id": "INV-2024-0847",
            "run_id": "run-A",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
        }

        # Both block
        await compiled.ainvoke({**init_state, "run_id": "run-A"}, config=config_a)
        await compiled.ainvoke({**init_state, "run_id": "run-B"}, config=config_b)

        # Resume only A
        result_a = await compiled.ainvoke(None, config=config_a)
        state_b = await compiled.aget_state(config_b)

        assert result_a["status"] == "completed"
        assert state_b.values["report"] is None  # B still blocked
