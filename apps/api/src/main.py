from fastapi import FastAPI

from apps.api.src.api.v1.analytics import create_analytics_router
from apps.api.src.api.v1.audit import router as audit_router
from apps.api.src.api.v1.health import router as health_router
from apps.api.src.api.v1.ingest import router as ingest_router
from apps.api.src.api.v1.search import router as search_router
from apps.api.src.telemetry.cost_tracker import CostTracker

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
