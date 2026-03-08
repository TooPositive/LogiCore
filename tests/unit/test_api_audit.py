"""Tests for audit API endpoints.

POST /api/v1/audit/start -- kicks off audit workflow, returns run_id
GET /api/v1/audit/{run_id}/status -- returns current state
POST /api/v1/audit/{run_id}/approve -- resumes workflow with approval
"""


from httpx import ASGITransport, AsyncClient


class TestAuditStartEndpoint:
    """POST /api/v1/audit/start."""

    async def test_start_returns_run_id(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/start",
                json={"invoice_id": "INV-2024-0847"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "processing"

    async def test_start_requires_invoice_id(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post("/api/v1/audit/start", json={})

        assert response.status_code == 422  # Validation error

    async def test_start_rejects_empty_invoice_id(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/start",
                json={"invoice_id": ""},
            )

        assert response.status_code == 422

    async def test_start_returns_unique_run_ids(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        run_ids = []
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            for _ in range(5):
                response = await ac.post(
                    "/api/v1/audit/start",
                    json={"invoice_id": "INV-001"},
                )
                run_ids.append(response.json()["run_id"])

        assert len(set(run_ids)) == 5, "Run IDs must be unique"


class TestAuditStatusEndpoint:
    """GET /api/v1/audit/{run_id}/status."""

    async def test_status_returns_current_state(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import _audit_store, router

        app = FastAPI()
        app.include_router(router)

        # Seed a known audit state
        _audit_store["run-status-001"] = {
            "run_id": "run-status-001",
            "invoice_id": "INV-2024-0847",
            "status": "awaiting_approval",
            "discrepancies": [{"description": "Test", "band": "critical"}],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/audit/run-status-001/status")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run-status-001"
        assert data["status"] == "awaiting_approval"
        assert len(data["discrepancies"]) == 1

    async def test_status_not_found(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/audit/nonexistent/status")

        assert response.status_code == 404


class TestAuditApproveEndpoint:
    """POST /api/v1/audit/{run_id}/approve."""

    async def test_approve_returns_success(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import _audit_store, router

        app = FastAPI()
        app.include_router(router)

        # Seed an audit waiting for approval
        _audit_store["run-approve-001"] = {
            "run_id": "run-approve-001",
            "invoice_id": "INV-2024-0847",
            "status": "awaiting_approval",
            "discrepancies": [],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/run-approve-001/approve",
                json={
                    "approved": True,
                    "reviewer_id": "martin.lang",
                    "notes": "Verified.",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run-approve-001"

    async def test_approve_not_found(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import router

        app = FastAPI()
        app.include_router(router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/nonexistent/approve",
                json={
                    "approved": True,
                    "reviewer_id": "test",
                },
            )

        assert response.status_code == 404

    async def test_approve_requires_reviewer_id(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import _audit_store, router

        app = FastAPI()
        app.include_router(router)

        _audit_store["run-approve-002"] = {
            "run_id": "run-approve-002",
            "invoice_id": "INV-001",
            "status": "awaiting_approval",
            "discrepancies": [],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/run-approve-002/approve",
                json={"approved": True},  # missing reviewer_id
            )

        assert response.status_code == 422

    async def test_approve_rejects_non_awaiting_status(self):
        from fastapi import FastAPI

        from apps.api.src.api.v1.audit import _audit_store, router

        app = FastAPI()
        app.include_router(router)

        _audit_store["run-approve-003"] = {
            "run_id": "run-approve-003",
            "invoice_id": "INV-001",
            "status": "completed",  # Already completed
            "discrepancies": [],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/audit/run-approve-003/approve",
                json={
                    "approved": True,
                    "reviewer_id": "test",
                },
            )

        assert response.status_code == 409  # Conflict


class TestAuditApiModels:
    """Validate request/response models."""

    def test_start_request_model(self):
        from apps.api.src.api.v1.audit import AuditStartRequest

        req = AuditStartRequest(invoice_id="INV-2024-0847")
        assert req.invoice_id == "INV-2024-0847"

    def test_approve_request_model(self):
        from apps.api.src.api.v1.audit import ApproveRequest

        req = ApproveRequest(
            approved=True,
            reviewer_id="martin.lang",
            notes="Verified.",
        )
        assert req.approved is True
        assert req.reviewer_id == "martin.lang"
