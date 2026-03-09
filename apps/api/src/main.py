from fastapi import FastAPI

from apps.api.src.core.api.v1.analytics import create_analytics_router
from apps.api.src.core.api.v1.health import router as health_router
from apps.api.src.core.api.v1.ingest import router as ingest_router
from apps.api.src.core.api.v1.search import router as search_router
from apps.api.src.core.telemetry.cost_tracker import CostTracker
from apps.api.src.domains.logicore.api.audit import router as audit_router
from apps.api.src.domains.logicore.api.compliance import (
    create_compliance_router,
)

app = FastAPI(
    title="LogiCore API",
    description="Enterprise AI Operating System for Logistics & Supply Chain",
    version="0.1.0",
)

# Global cost tracker instance (production: backed by PostgreSQL)
_cost_tracker = CostTracker()

app.include_router(health_router)
app.include_router(search_router)
app.include_router(ingest_router)
app.include_router(audit_router)
app.include_router(
    create_analytics_router(cost_tracker=_cost_tracker, eval_scores=None)
)

# Compliance router (production: pass real asyncpg pool)
# db_pool=None means endpoints will fail until a real pool is injected.
# In tests, use create_compliance_router(db_pool=mock_pool) directly.
app.include_router(create_compliance_router(db_pool=None))
