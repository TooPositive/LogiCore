"""Tests for crash recovery -- checkpoint persistence and node idempotency.

Every agent node must be idempotent: running twice with the same input
produces the same output. Combined with LangGraph's checkpointer, this
ensures crash recovery without data corruption.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver


class TestNodeIdempotency:
    """Every node must be idempotent for crash recovery."""

    @pytest.fixture
    def mock_deps(self):
        """Standard mock dependencies."""
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

    async def test_reader_agent_idempotent(self):
        """ReaderAgent produces same output for same input."""
        from apps.api.src.agents.brain.reader import ReaderAgent

        retriever = AsyncMock()
        retriever.search = AsyncMock(return_value=[
            MagicMock(
                content="Contract CTR-001: EUR 0.45/kg",
                score=0.95,
                source="ctr.pdf",
                document_id="d1",
            )
        ])
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(
            content='[{"contract_id": "CTR-001", "rate": "0.45", '
            '"currency": "EUR", "unit": "kg"}]'
        ))

        agent = ReaderAgent(retriever=retriever, llm=llm)
        r1 = await agent.extract_rates("CTR-001", "general")
        r2 = await agent.extract_rates("CTR-001", "general")

        assert len(r1) == len(r2)
        assert r1[0].rate == r2[0].rate

    async def test_sql_tool_idempotent(self):
        """SqlQueryTool produces same output for same input."""
        from apps.api.src.tools.sql_query import SqlQueryTool

        pool = MagicMock()
        conn = AsyncMock()
        pool.acquire = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        ))
        conn.fetchrow = AsyncMock(return_value={
            "invoice_id": "INV-001",
            "vendor": "Test",
            "contract_id": "CTR-001",
            "issue_date": "2024-01-01T00:00:00Z",
            "total_amount": Decimal("100"),
            "currency": "EUR",
        })
        conn.fetch = AsyncMock(return_value=[{
            "description": "Test",
            "quantity": Decimal("100"),
            "unit": "kg",
            "unit_price": Decimal("1.00"),
            "total": Decimal("100"),
            "cargo_type": "general",
        }])

        tool = SqlQueryTool(pool=pool)
        r1 = await tool.fetch_invoice("INV-001")
        r2 = await tool.fetch_invoice("INV-001")

        assert r1.invoice_id == r2.invoice_id
        assert r1.total_amount == r2.total_amount

    async def test_auditor_agent_idempotent(self):
        """AuditorAgent produces same output for same input."""
        from apps.api.src.agents.auditor.comparator import AuditorAgent
        from apps.api.src.domain.audit import ContractRate, Invoice, LineItem

        invoice = Invoice(
            invoice_id="INV-001",
            vendor="Test",
            contract_id="CTR-001",
            issue_date="2024-01-01T00:00:00Z",
            total_amount=Decimal("520"),
            currency="EUR",
            line_items=[
                LineItem(
                    description="Test",
                    quantity=Decimal("1000"),
                    unit="kg",
                    unit_price=Decimal("0.52"),
                    total=Decimal("520"),
                    cargo_type="general",
                )
            ],
        )
        rates = [
            ContractRate(
                contract_id="CTR-001",
                rate=Decimal("0.45"),
                currency="EUR",
                unit="kg",
                cargo_type="general",
            )
        ]

        agent = AuditorAgent()
        d1 = await agent.compare(invoice, rates)
        d2 = await agent.compare(invoice, rates)

        assert len(d1) == len(d2)
        assert d1[0].difference == d2[0].difference
        assert d1[0].band == d2[0].band

    async def test_report_generator_idempotent(self):
        """ReportGenerator produces same output for same input."""
        from apps.api.src.domain.audit import Invoice, LineItem
        from apps.api.src.tools.report_generator import ReportGenerator

        gen = ReportGenerator()
        kwargs = dict(
            run_id="run-001",
            invoice=Invoice(
                invoice_id="INV-001",
                vendor="Test",
                contract_id="CTR-001",
                issue_date="2024-01-01T00:00:00Z",
                total_amount=Decimal("100"),
                currency="EUR",
                line_items=[
                    LineItem(
                        description="Test",
                        quantity=Decimal("100"),
                        unit="kg",
                        unit_price=Decimal("1.00"),
                        total=Decimal("100"),
                    )
                ],
            ),
            discrepancies=[],
        )

        r1 = await gen.generate(**kwargs)
        r2 = await gen.generate(**kwargs)

        assert r1.summary == r2.summary
        assert r1.total_discrepancy == r2.total_discrepancy


class TestCheckpointRecovery:
    """Test crash recovery at each node using MemorySaver."""

    @pytest.fixture
    def mock_deps(self):
        """Standard mock dependencies."""
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

    async def test_checkpoint_persists_after_reader(self, mock_deps):
        """State saved after reader node completes."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["sql_agent"],
        )
        config = {"configurable": {"thread_id": "crash-reader"}}

        result = await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-crash-001",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
                "compliance_findings": [],
            },
            config=config,
        )

        # Reader ran but sql_agent didn't
        assert len(result["extracted_rates"]) > 0
        assert result["invoice_data"] is None

        # Resume from checkpoint
        result2 = await compiled.ainvoke(None, config=config)

        # Now sql_agent completed and blocked at auditor
        assert result2["invoice_data"] is not None

    async def test_checkpoint_persists_after_sql(self, mock_deps):
        """State saved after SQL node completes."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["auditor"],
        )
        config = {"configurable": {"thread_id": "crash-sql"}}

        result = await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-crash-002",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
                "compliance_findings": [],
            },
            config=config,
        )

        # Reader + SQL ran, auditor didn't
        assert result["invoice_data"] is not None
        assert len(result["discrepancies"]) == 0

        # Resume from checkpoint
        result2 = await compiled.ainvoke(None, config=config)

        # Auditor completed
        assert len(result2["discrepancies"]) > 0

    async def test_checkpoint_at_hitl_survives_long_wait(self, mock_deps):
        """State at HITL gate persists indefinitely in checkpointer."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["hitl_gate"],
        )
        config = {"configurable": {"thread_id": "crash-hitl"}}

        # Run until HITL gate
        await compiled.ainvoke(
            {
                "invoice_id": "INV-2024-0847",
                "run_id": "run-crash-003",
                "status": "extracting",
                "extracted_rates": [],
                "invoice_data": None,
                "discrepancies": [],
                "approval": None,
                "report": None,
                "compliance_findings": [],
            },
            config=config,
        )

        # Verify state is fully intact
        state = await compiled.aget_state(config)
        assert state.values["invoice_id"] == "INV-2024-0847"
        assert state.values["run_id"] == "run-crash-003"
        assert len(state.values["extracted_rates"]) > 0
        assert state.values["invoice_data"] is not None
        assert len(state.values["discrepancies"]) > 0

        # Resume after "long wait"
        result = await compiled.ainvoke(None, config=config)
        assert result["status"] == "completed"
        assert result["report"] is not None

    async def test_full_graph_completes_after_all_interrupts(self, mock_deps):
        """Resume through every node step by step."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()

        # Interrupt at every node in sequence
        for interrupt_node in ["sql_agent", "auditor", "hitl_gate", "report"]:
            compiled = graph.compile(
                checkpointer=checkpointer,
                interrupt_before=[interrupt_node],
            )
            config = {"configurable": {"thread_id": f"crash-all-{interrupt_node}"}}

            await compiled.ainvoke(
                {
                    "invoice_id": "INV-2024-0847",
                    "run_id": f"run-{interrupt_node}",
                    "status": "extracting",
                    "extracted_rates": [],
                    "invoice_data": None,
                    "discrepancies": [],
                    "approval": None,
                    "report": None,
                    "compliance_findings": [],
                },
                config=config,
            )

            # Resume and verify completion
            result = await compiled.ainvoke(None, config=config)
            assert result["status"] == "completed", (
                f"Failed to complete after interrupt at {interrupt_node}"
            )

    async def test_checkpoint_state_accessible_by_thread_id(self, mock_deps):
        """Different thread_ids maintain independent checkpoints."""
        from apps.api.src.graphs.audit_graph import build_audit_graph

        graph = build_audit_graph(
            retriever=mock_deps["retriever"],
            llm=mock_deps["llm"],
            pool=mock_deps["pool"],
        )
        checkpointer = MemorySaver()
        compiled = graph.compile(
            checkpointer=checkpointer,
            interrupt_before=["hitl_gate"],
        )

        init = {
            "invoice_id": "INV-2024-0847",
            "run_id": "default",
            "status": "extracting",
            "extracted_rates": [],
            "invoice_data": None,
            "discrepancies": [],
            "approval": None,
            "report": None,
            "compliance_findings": [],
        }

        config_a = {"configurable": {"thread_id": "thread-A"}}
        config_b = {"configurable": {"thread_id": "thread-B"}}

        await compiled.ainvoke({**init, "run_id": "run-A"}, config=config_a)
        await compiled.ainvoke({**init, "run_id": "run-B"}, config=config_b)

        state_a = await compiled.aget_state(config_a)
        state_b = await compiled.aget_state(config_b)

        assert state_a.values["run_id"] == "run-A"
        assert state_b.values["run_id"] == "run-B"
