"""Audit workflow graph -- LangGraph state machine.

Nodes: reader -> sql_agent -> auditor -> hitl_gate -> report
Each node wraps a standalone agent function from Layer 2.

Dependencies (retriever, llm, pool) are injected via build_audit_graph().
The graph definition is domain-agnostic -- only the node functions
contain LogiCore-specific logic.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from apps.api.src.agents.auditor.comparator import AuditorAgent
from apps.api.src.agents.brain.reader import ReaderAgent
from apps.api.src.domain.audit import ContractRate, Invoice
from apps.api.src.graphs.state import AuditGraphState
from apps.api.src.tools.report_generator import ReportGenerator
from apps.api.src.tools.sql_query import SqlQueryTool


def build_audit_graph(
    retriever=None,
    llm=None,
    pool=None,
) -> StateGraph:
    """Build the audit workflow state graph.

    Args:
        retriever: RAG retriever for contract lookup.
        llm: LLM for rate extraction.
        pool: asyncpg connection pool for invoice DB.

    Returns:
        StateGraph (not compiled -- caller compiles with optional checkpointer).
    """
    reader_agent = ReaderAgent(retriever=retriever, llm=llm)
    sql_tool = SqlQueryTool(pool=pool)
    auditor_agent = AuditorAgent()
    report_gen = ReportGenerator()

    async def reader_node(state: AuditGraphState) -> dict[str, Any]:
        """Extract contract rates via RAG."""
        # Derive contract_id from invoice_id pattern or use generic search
        rates = await reader_agent.extract_rates(
            contract_id=state["invoice_id"],
            cargo_type="",
        )
        return {
            "extracted_rates": [r.model_dump() for r in rates],
            "status": "querying",
        }

    async def sql_agent_node(state: AuditGraphState) -> dict[str, Any]:
        """Fetch invoice data from DB."""
        invoice = await sql_tool.fetch_invoice(state["invoice_id"])
        return {
            "invoice_data": invoice.model_dump() if invoice else None,
            "status": "auditing",
        }

    async def auditor_node(state: AuditGraphState) -> dict[str, Any]:
        """Compare rates and classify discrepancies."""
        invoice_data = state["invoice_data"]
        if not invoice_data:
            return {
                "discrepancies": [],
                "status": "awaiting_approval",
            }

        invoice = Invoice(**invoice_data)
        rates = [ContractRate(**r) for r in state["extracted_rates"]]

        discrepancies = await auditor_agent.compare(invoice, rates)
        return {
            "discrepancies": [d.model_dump() for d in discrepancies],
            "status": "awaiting_approval",
        }

    async def hitl_gate_node(state: AuditGraphState) -> dict[str, Any]:
        """HITL gateway -- in the full version, this uses interrupt().

        For unit tests without a checkpointer, this is a pass-through.
        The interrupt-based HITL is tested in Layer 4 / integration tests.
        """
        return {"status": "approved"}

    async def report_node(state: AuditGraphState) -> dict[str, Any]:
        """Generate the final audit report."""
        invoice_data = state["invoice_data"]
        if not invoice_data:
            return {"report": None, "status": "completed"}

        from apps.api.src.domain.audit import Discrepancy

        invoice = Invoice(**invoice_data)
        discrepancies = [Discrepancy(**d) for d in state["discrepancies"]]

        approval_data = state.get("approval")
        approval = None
        if approval_data:
            from apps.api.src.domain.audit import ApprovalDecision

            approval = ApprovalDecision(**approval_data)

        report = await report_gen.generate(
            run_id=state["run_id"],
            invoice=invoice,
            discrepancies=discrepancies,
            approval=approval,
        )

        return {
            "report": report.model_dump(),
            "status": "completed",
        }

    # Build the graph
    graph = StateGraph(AuditGraphState)

    graph.add_node("reader", reader_node)
    graph.add_node("sql_agent", sql_agent_node)
    graph.add_node("auditor", auditor_node)
    graph.add_node("hitl_gate", hitl_gate_node)
    graph.add_node("report", report_node)

    graph.add_edge(START, "reader")
    graph.add_edge("reader", "sql_agent")
    graph.add_edge("sql_agent", "auditor")
    graph.add_edge("auditor", "hitl_gate")
    graph.add_edge("hitl_gate", "report")
    graph.add_edge("report", END)

    return graph
