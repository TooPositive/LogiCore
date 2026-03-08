"""Per-query cost calculation and aggregation for FinOps.

Domain-agnostic: pricing table is configurable via ModelPricing objects.
Default table includes GPT-5 nano/mini/5.2 pricing from spec.

Key decisions:
- Cache hits are always EUR 0.00 (no tokens consumed)
- Costs are in USD (API pricing) but could be converted to EUR at API layer
- Aggregation: by agent, by user, by time period
"""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from apps.api.src.domain.telemetry import CostSummary


class ModelPricing(BaseModel):
    """Pricing for a single model in USD per 1M tokens."""

    model_name: str
    input_per_1m: Decimal = Field(ge=Decimal("0"))
    output_per_1m: Decimal = Field(ge=Decimal("0"))


# Default pricing table (USD per 1M tokens, from Phase 4 spec)
MODEL_PRICING: dict[str, ModelPricing] = {
    "gpt-5-nano": ModelPricing(
        model_name="gpt-5-nano",
        input_per_1m=Decimal("0.05"),
        output_per_1m=Decimal("0.40"),
    ),
    "gpt-5-mini": ModelPricing(
        model_name="gpt-5-mini",
        input_per_1m=Decimal("0.25"),
        output_per_1m=Decimal("2.00"),
    ),
    "gpt-5.2": ModelPricing(
        model_name="gpt-5.2",
        input_per_1m=Decimal("1.75"),
        output_per_1m=Decimal("14.00"),
    ),
}


def calculate_query_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    pricing_table: dict[str, ModelPricing] | None = None,
    cache_hit: bool = False,
) -> Decimal:
    """Calculate the cost of a single LLM query.

    Args:
        model: Model identifier (must exist in pricing_table).
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.
        pricing_table: Custom pricing table. Defaults to MODEL_PRICING.
        cache_hit: If True, cost is always EUR 0.00.

    Returns:
        Cost in USD (Decimal).

    Raises:
        ValueError: If model not found in pricing table.
    """
    if cache_hit:
        return Decimal("0")

    if prompt_tokens == 0 and completion_tokens == 0:
        return Decimal("0")

    table = pricing_table or MODEL_PRICING

    if model not in table:
        raise ValueError(f"Unknown model: {model}")

    pricing = table[model]
    input_cost = (Decimal(prompt_tokens) / Decimal("1000000")) * pricing.input_per_1m
    output_cost = (
        Decimal(completion_tokens) / Decimal("1000000")
    ) * pricing.output_per_1m

    return input_cost + output_cost


class _CostRecord(BaseModel):
    """Internal record for a single query's cost data."""

    agent_name: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal
    cache_hit: bool = False
    user_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CostTracker:
    """In-memory cost aggregator for analytics.

    Thread-safe for single-process use. For multi-process production,
    back this with PostgreSQL or Redis.
    """

    def __init__(self) -> None:
        self._records: list[_CostRecord] = []

    def record(
        self,
        agent_name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: str | None = None,
        cache_hit: bool = False,
        timestamp: datetime | None = None,
        pricing_table: dict[str, ModelPricing] | None = None,
    ) -> Decimal:
        """Record a query and return its cost."""
        cost = calculate_query_cost(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_hit=cache_hit,
            pricing_table=pricing_table,
        )
        record = _CostRecord(
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
            cache_hit=cache_hit,
            user_id=user_id,
            timestamp=timestamp or datetime.now(UTC),
        )
        self._records.append(record)
        return cost

    def total_cost(self) -> Decimal:
        return sum((r.cost for r in self._records), Decimal("0"))

    def total_queries(self) -> int:
        return len(self._records)

    def avg_cost_per_query(self) -> Decimal:
        if not self._records:
            return Decimal("0")
        return self.total_cost() / len(self._records)

    def cache_hit_rate(self) -> float:
        if not self._records:
            return 0.0
        hits = sum(1 for r in self._records if r.cache_hit)
        return hits / len(self._records)

    def cost_by_agent(self) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for r in self._records:
            result[r.agent_name] = result.get(r.agent_name, Decimal("0")) + r.cost
        return result

    def cost_by_user(self) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for r in self._records:
            if r.user_id:
                result[r.user_id] = (
                    result.get(r.user_id, Decimal("0")) + r.cost
                )
        return result

    def _filter_by_period(
        self, start: datetime, end: datetime
    ) -> list[_CostRecord]:
        return [r for r in self._records if start <= r.timestamp <= end]

    def to_cost_summary(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> CostSummary:
        """Generate a CostSummary for the given time period."""
        records = self._filter_by_period(period_start, period_end)
        total = sum((r.cost for r in records), Decimal("0"))
        count = len(records)
        avg = total / count if count > 0 else Decimal("0")
        hits = sum(1 for r in records if r.cache_hit)
        hit_rate = hits / count if count > 0 else 0.0
        by_agent: dict[str, Decimal] = {}
        for r in records:
            by_agent[r.agent_name] = (
                by_agent.get(r.agent_name, Decimal("0")) + r.cost
            )

        return CostSummary(
            period_start=period_start,
            period_end=period_end,
            total_cost_eur=total,
            total_queries=count,
            avg_cost_per_query_eur=avg,
            cache_hit_rate=hit_rate,
            by_agent=by_agent,
        )
