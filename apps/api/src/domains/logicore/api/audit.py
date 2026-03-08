"""Audit API endpoints.

POST /api/v1/audit/start       -- start a new audit workflow
GET  /api/v1/audit/{run_id}/status   -- get current state
POST /api/v1/audit/{run_id}/approve  -- approve/reject at HITL gate

In production, the graph runs asynchronously and the audit state is stored
in the PostgreSQL checkpointer. For unit tests, we use an in-memory store.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

# In-memory audit state store for unit tests and development.
# In production, this is replaced by the LangGraph checkpointer + PostgreSQL.
_audit_store: dict[str, dict[str, Any]] = {}


class AuditStartRequest(BaseModel):
    """Request to start a new audit."""

    invoice_id: str = Field(min_length=1)


class AuditStartResponse(BaseModel):
    """Response from starting an audit."""

    run_id: str
    status: str


class AuditStatusResponse(BaseModel):
    """Response for audit status query."""

    run_id: str
    invoice_id: str
    status: str
    discrepancies: list[dict[str, Any]] = []


class ApproveRequest(BaseModel):
    """Request to approve/reject at HITL gate."""

    approved: bool
    reviewer_id: str = Field(min_length=1)
    notes: str | None = None


class ApproveResponse(BaseModel):
    """Response from approval endpoint."""

    run_id: str
    status: str


@router.post("/start", response_model=AuditStartResponse)
async def start_audit(request: AuditStartRequest) -> AuditStartResponse:
    """Start a new audit workflow.

    Creates a run_id and kicks off the LangGraph workflow.
    Returns immediately with the run_id for status polling.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"

    # Store initial state
    _audit_store[run_id] = {
        "run_id": run_id,
        "invoice_id": request.invoice_id,
        "status": "processing",
        "discrepancies": [],
    }

    # In production: kick off graph.ainvoke() in background task
    # For now, just store the initial state

    return AuditStartResponse(run_id=run_id, status="processing")


@router.get("/{run_id}/status", response_model=AuditStatusResponse)
async def get_status(run_id: str) -> AuditStatusResponse:
    """Get the current status of an audit run."""
    if run_id not in _audit_store:
        raise HTTPException(status_code=404, detail=f"Audit run {run_id} not found")

    state = _audit_store[run_id]
    return AuditStatusResponse(
        run_id=state["run_id"],
        invoice_id=state["invoice_id"],
        status=state["status"],
        discrepancies=state.get("discrepancies", []),
    )


@router.post("/{run_id}/approve", response_model=ApproveResponse)
async def approve_audit(run_id: str, request: ApproveRequest) -> ApproveResponse:
    """Approve or reject an audit at the HITL gate.

    Only valid when status is 'awaiting_approval'.
    """
    if run_id not in _audit_store:
        raise HTTPException(status_code=404, detail=f"Audit run {run_id} not found")

    state = _audit_store[run_id]
    if state["status"] != "awaiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Audit run {run_id} is not awaiting approval (status: {state['status']})",
        )

    # Update state with approval
    state["approval"] = {
        "approved": request.approved,
        "reviewer_id": request.reviewer_id,
        "notes": request.notes,
    }
    state["status"] = "approved" if request.approved else "rejected"
    _audit_store[run_id] = state

    # In production: resume the LangGraph with Command(resume=approval_data)

    return ApproveResponse(run_id=run_id, status=state["status"])
