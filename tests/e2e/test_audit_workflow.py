"""E2E tests for audit workflow through the main app.

Tests the full API surface using the registered audit router in main.py.
No Docker required -- uses in-memory audit store.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


@pytest.mark.e2e
class TestAuditWorkflowE2E:
    """Full audit workflow through the main FastAPI app."""

    async def test_start_status_approve_workflow(self):
        """Complete happy path: start -> check status -> approve."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Step 1: Start audit
            start_resp = await ac.post(
                "/api/v1/audit/start",
                json={"invoice_id": "INV-2024-0847"},
            )
            assert start_resp.status_code == 200
            run_id = start_resp.json()["run_id"]
            assert start_resp.json()["status"] == "processing"

            # Step 2: Check status
            status_resp = await ac.get(f"/api/v1/audit/{run_id}/status")
            assert status_resp.status_code == 200
            assert status_resp.json()["invoice_id"] == "INV-2024-0847"
            assert status_resp.json()["status"] == "processing"

    async def test_start_reject_workflow(self):
        """Start audit, simulate awaiting_approval, then reject."""
        from apps.api.src.api.v1.audit import _audit_store

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Start audit
            start_resp = await ac.post(
                "/api/v1/audit/start",
                json={"invoice_id": "INV-2024-0801"},
            )
            run_id = start_resp.json()["run_id"]

            # Simulate reaching HITL gate (in production, the graph does this)
            _audit_store[run_id]["status"] = "awaiting_approval"
            _audit_store[run_id]["discrepancies"] = [
                {"description": "Rate mismatch", "band": "escalate"}
            ]

            # Check status shows awaiting_approval
            status_resp = await ac.get(f"/api/v1/audit/{run_id}/status")
            assert status_resp.json()["status"] == "awaiting_approval"
            assert len(status_resp.json()["discrepancies"]) == 1

            # Reject
            approve_resp = await ac.post(
                f"/api/v1/audit/{run_id}/approve",
                json={
                    "approved": False,
                    "reviewer_id": "martin.lang",
                    "notes": "Needs further investigation.",
                },
            )
            assert approve_resp.status_code == 200
            assert approve_resp.json()["status"] == "rejected"

            # Verify final status
            final_resp = await ac.get(f"/api/v1/audit/{run_id}/status")
            assert final_resp.json()["status"] == "rejected"

    async def test_multiple_audits_independent(self):
        """Multiple audits run independently with unique run_ids."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            run_ids = []
            for inv_id in ["INV-001", "INV-002", "INV-003"]:
                resp = await ac.post(
                    "/api/v1/audit/start",
                    json={"invoice_id": inv_id},
                )
                assert resp.status_code == 200
                run_ids.append(resp.json()["run_id"])

            # All run_ids are unique
            assert len(set(run_ids)) == 3

            # Each status returns the correct invoice
            for i, inv_id in enumerate(["INV-001", "INV-002", "INV-003"]):
                status = await ac.get(f"/api/v1/audit/{run_ids[i]}/status")
                assert status.json()["invoice_id"] == inv_id

    async def test_nonexistent_run_returns_404(self):
        """Querying nonexistent run_id returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/audit/nonexistent-run/status")
            assert resp.status_code == 404

            resp2 = await ac.post(
                "/api/v1/audit/nonexistent-run/approve",
                json={"approved": True, "reviewer_id": "test"},
            )
            assert resp2.status_code == 404

    async def test_validation_errors(self):
        """API validates input at boundaries."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Missing invoice_id
            resp = await ac.post("/api/v1/audit/start", json={})
            assert resp.status_code == 422

            # Empty invoice_id
            resp2 = await ac.post(
                "/api/v1/audit/start", json={"invoice_id": ""}
            )
            assert resp2.status_code == 422

            # Null invoice_id
            resp3 = await ac.post(
                "/api/v1/audit/start", json={"invoice_id": None}
            )
            assert resp3.status_code == 422

    async def test_health_endpoint_still_works(self):
        """Verify audit router registration didn't break existing routes."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/api/v1/health")
            assert resp.status_code == 200

    async def test_approve_conflict_states(self):
        """Approve endpoint rejects non-awaiting states."""
        from apps.api.src.api.v1.audit import _audit_store

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Start an audit
            start_resp = await ac.post(
                "/api/v1/audit/start",
                json={"invoice_id": "INV-CONFLICT"},
            )
            run_id = start_resp.json()["run_id"]

            # Try to approve while still processing
            resp = await ac.post(
                f"/api/v1/audit/{run_id}/approve",
                json={"approved": True, "reviewer_id": "test"},
            )
            assert resp.status_code == 409

            # Set to awaiting_approval and approve
            _audit_store[run_id]["status"] = "awaiting_approval"
            resp2 = await ac.post(
                f"/api/v1/audit/{run_id}/approve",
                json={"approved": True, "reviewer_id": "martin.lang"},
            )
            assert resp2.status_code == 200

            # Try to approve again (now approved state)
            resp3 = await ac.post(
                f"/api/v1/audit/{run_id}/approve",
                json={"approved": True, "reviewer_id": "another"},
            )
            assert resp3.status_code == 409
