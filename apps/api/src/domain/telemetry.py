"""Domain models for Phase 4: Trust Layer -- LLMOps, Observability & Evaluation.

Models:
- TraceRecord: Single LLM call with full observability data
- CostSummary: Aggregated costs by agent/user/period
- EvalScore: RAG quality metrics from LLM-as-Judge
- CacheEntry: Cached LLM response with RBAC-aware partition key
- ModelRoute: Routing decision with cost justification
- QueryComplexity: SIMPLE/MEDIUM/COMPLEX classification

All costs in EUR, all timestamps in UTC.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class QueryComplexity(StrEnum):
    """Query complexity classification for model routing."""

    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


class TraceRecord(BaseModel):
    """A single LLM call trace with full observability data.

    Captures: model, tokens, latency, cost, cache status.
    Used by Langfuse handler and PostgreSQL fallback.
    """

    trace_id: str
    run_id: str
    agent_name: str
    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    cost_eur: Decimal = Field(ge=Decimal("0"))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cache_hit: bool = False
    user_id: str | None = None
    metadata: dict | None = None


class CostSummary(BaseModel):
    """Aggregated cost data for a time period.

    Used by the analytics API to serve FinOps dashboards.
    """

    period_start: datetime
    period_end: datetime
    total_cost_eur: Decimal = Field(ge=Decimal("0"))
    total_queries: int = Field(ge=0)
    avg_cost_per_query_eur: Decimal = Field(ge=Decimal("0"))
    cache_hit_rate: float = Field(ge=0.0, le=1.0)
    by_agent: dict[str, Decimal]


class EvalScore(BaseModel):
    """RAG quality metrics from LLM-as-Judge evaluation.

    CI quality gate: all metrics must be > threshold to pass.
    """

    eval_id: str
    context_precision: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevancy: float = Field(ge=0.0, le=1.0)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    dataset_size: int = Field(ge=0)
    metadata: dict | None = None

    def passes_quality_gate(self, threshold: float = 0.8) -> bool:
        """Check if all metrics exceed the quality gate threshold."""
        return (
            self.context_precision > threshold
            and self.faithfulness > threshold
            and self.answer_relevancy > threshold
        )


class CacheEntry(BaseModel):
    """A cached LLM response stored in Redis.

    SECURITY-CRITICAL: The RBAC partition key ensures that cached responses
    are scoped to clearance_level + sorted(departments) + entity_keys.
    Without this, the cache is a universal RBAC bypass.
    """

    cache_key: str
    query: str
    response: str
    embedding: list[float]
    clearance_level: int = Field(ge=1, le=4)
    departments: list[str]
    entity_keys: list[str] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = Field(gt=0)

    def rbac_partition_key(self) -> str:
        """Generate RBAC-aware partition key.

        Includes clearance_level + sorted departments + sorted entity keys.
        Two users with different clearance or departments MUST map to
        different partitions -- otherwise the cache becomes an RBAC bypass.
        """
        sorted_depts = sorted(self.departments)
        sorted_entities = sorted(self.entity_keys)
        parts = [
            f"cl:{self.clearance_level}",
            f"dept:{','.join(sorted_depts)}",
            f"ent:{','.join(sorted_entities)}",
        ]
        return "|".join(parts)

    def is_stale(self, doc_updated_at: datetime) -> bool:
        """Check if any source document was updated after this cache entry was created."""
        return doc_updated_at > self.created_at


class ModelRoute(BaseModel):
    """A model routing decision with cost justification.

    Captures why a specific model was selected and whether
    keyword overrides or confidence escalation were applied.
    """

    query: str
    complexity: QueryComplexity
    selected_model: str
    confidence: float = Field(ge=0.0, le=1.0)
    routing_reason: str
    keyword_override: bool = False
    escalated: bool = False
