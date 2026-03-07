from fastapi import FastAPI

from apps.api.src.api.v1.health import router as health_router
from apps.api.src.api.v1.ingest import router as ingest_router
from apps.api.src.api.v1.search import router as search_router

app = FastAPI(
    title="LogiCore API",
    description="Enterprise AI Operating System for Logistics & Supply Chain",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(search_router)
app.include_router(ingest_router)
