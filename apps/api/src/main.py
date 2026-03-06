from fastapi import FastAPI

from apps.api.src.api.v1.health import router as health_router

app = FastAPI(
    title="LogiCore API",
    description="Enterprise AI Operating System for Logistics & Supply Chain",
    version="0.1.0",
)

app.include_router(health_router)
