import random
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from apps.api.src.core.api.v1.analytics import create_analytics_router
from apps.api.src.core.api.v1.health import router as health_router
from apps.api.src.core.api.v1.ingest import router as ingest_router
from apps.api.src.core.api.v1.search import router as search_router
from apps.api.src.core.telemetry.cost_tracker import CostTracker
from apps.api.src.domains.logicore.api.audit import router as audit_router
from apps.api.src.domains.logicore.api.compliance import (
    create_compliance_router,
)
from apps.api.src.domains.logicore.api.fleet import create_fleet_router

app = FastAPI(
    title="LogiCore API",
    description="Enterprise AI Operating System for Logistics & Supply Chain",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global cost tracker instance (production: backed by PostgreSQL)
_cost_tracker = CostTracker()


def _seed_cost_tracker(tracker: CostTracker) -> None:
    """Seed with realistic 24h baseline data so dashboard shows plausible costs."""
    now = datetime.now(UTC)
    agents = [
        # (agent, model, count, prompt_tok_range, completion_tok_range)
        ("fleet-guardian", "gpt-5-nano", 200, (400, 800), (100, 300)),
        ("rag-search", "gpt-5-mini", 50, (1200, 2400), (200, 600)),
        ("audit-workflow", "gpt-5-mini", 5, (2000, 4000), (800, 1500)),
        ("compliance-report", "gpt-5.2", 2, (3000, 5000), (1000, 2000)),
    ]
    for agent, model, count, pt_range, ct_range in agents:
        for i in range(count):
            ts = now - timedelta(hours=random.uniform(0.5, 23.5))
            tracker.record(
                agent_name=agent,
                model=model,
                prompt_tokens=random.randint(*pt_range),
                completion_tokens=random.randint(*ct_range),
                user_id=random.choice(
                    ["anna.schmidt", "marek.kowalski", "system"]
                ),
                cache_hit=(random.random() < 0.15),
                timestamp=ts,
            )


_seed_cost_tracker(_cost_tracker)

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

# Fleet router (Phase 9)
app.include_router(create_fleet_router())
