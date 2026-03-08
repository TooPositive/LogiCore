"""Analytics API endpoints for FinOps dashboard.

GET /api/v1/analytics/costs?period=7d -- cost breakdown by agent
GET /api/v1/analytics/quality -- RAG quality scores

Domain-agnostic: takes CostTracker and EvalScore as dependencies.
"""

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from apps.api.src.domain.telemetry import EvalScore
from apps.api.src.telemetry.cost_tracker import CostTracker


class CostsResponse(BaseModel):
    """Response model for /analytics/costs."""

    total_cost: float
    total_queries: int
    avg_cost_per_query: float
    cache_hit_rate: float
    by_agent: dict[str, float]
    period: str


class QualityResponse(BaseModel):
    """Response model for /analytics/quality."""

    context_precision: float
    faithfulness: float
    answer_relevancy: float
    last_eval: str
    dataset_size: int
    passes_gate: bool


def _parse_period(period: str) -> timedelta:
    """Parse period string like '7d', '30d', '24h' into timedelta.

    Raises ValueError on invalid format.
    """
    match = re.match(r"^(\d+)([dh])$", period)
    if not match:
        raise ValueError(f"Invalid period format: {period}")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == "d":
        return timedelta(days=value)
    elif unit == "h":
        return timedelta(hours=value)
    raise ValueError(f"Unknown unit: {unit}")


def create_analytics_router(
    cost_tracker: CostTracker,
    eval_scores: EvalScore | None,
) -> APIRouter:
    """Factory function to create analytics router with injected dependencies.

    This pattern keeps the router testable without global state.
    """
    router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

    @router.get("/costs", response_model=CostsResponse)
    async def get_costs(
        period: str = Query(
            default="7d",
            pattern=r"^\d+[dh]$",
            description="Time period: e.g., 7d, 30d, 24h",
        ),
    ) -> CostsResponse:
        """Get cost analytics for the specified period."""
        delta = _parse_period(period)
        now = datetime.now(UTC)
        period_start = now - delta
        period_end = now

        summary = cost_tracker.to_cost_summary(
            period_start=period_start,
            period_end=period_end,
        )

        return CostsResponse(
            total_cost=float(summary.total_cost_eur),
            total_queries=summary.total_queries,
            avg_cost_per_query=float(summary.avg_cost_per_query_eur),
            cache_hit_rate=summary.cache_hit_rate,
            by_agent={k: float(v) for k, v in summary.by_agent.items()},
            period=period,
        )

    @router.get("/quality", response_model=QualityResponse)
    async def get_quality() -> QualityResponse:
        """Get latest RAG quality scores."""
        if eval_scores is None:
            raise HTTPException(
                status_code=404,
                detail="No evaluation scores available",
            )

        return QualityResponse(
            context_precision=eval_scores.context_precision,
            faithfulness=eval_scores.faithfulness,
            answer_relevancy=eval_scores.answer_relevancy,
            last_eval=eval_scores.evaluated_at.isoformat(),
            dataset_size=eval_scores.dataset_size,
            passes_gate=eval_scores.passes_quality_gate(),
        )

    return router
