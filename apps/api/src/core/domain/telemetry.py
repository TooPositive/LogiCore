"""Domain models for Trust Layer -- LLMOps, Observability & Evaluation.

Phase 4 models:
- TraceRecord: Single LLM call with full observability data
- CostSummary: Aggregated costs by agent/user/period
- EvalScore: RAG quality metrics from LLM-as-Judge
- CacheEntry: Cached LLM response with RBAC-aware partition key
- ModelRoute: Routing decision with cost justification
- QueryComplexity: SIMPLE/MEDIUM/COMPLEX classification

Phase 5 models (Assessment Rigor):
- JudgeBiasResult: Position, verbosity, self-preference bias rates + calibration status
- DriftAlert: Metric regression alert with severity (green/yellow/red)
- DriftSeverity: Enum for drift severity levels
- ModelVersion: Model name + version + baseline scores for drift detection
- PromptCacheStats: Cache hit/miss rates, savings, static token ratio

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


# =========================================================================
# Phase 5: Assessment Rigor — Judge Bias, Drift Detection, Prompt Caching
# =========================================================================


class JudgeBiasResult(BaseModel):
    """Results from judge bias detection across multiple comparison dimensions.

    is_calibrated is computed from thresholds: all bias rates must be below
    their respective thresholds AND Spearman correlation must exceed minimum.

    Thresholds are configurable per deployment. Defaults from spec:
    - position_bias_threshold: 0.10 (10% disagreement when swapping A/B)
    - verbosity_bias_threshold: 0.10 (10% preference for longer answers)
    - self_preference_threshold: 0.10 (10% preference for same-family output)
    - min_spearman_correlation: 0.85
    """

    position_bias_rate: float = Field(ge=0.0, le=1.0)
    verbosity_bias_rate: float = Field(ge=0.0, le=1.0)
    self_preference_rate: float = Field(ge=0.0, le=1.0)
    spearman_correlation: float = Field(ge=-1.0, le=1.0)
    total_comparisons: int = Field(ge=0)

    # Configurable thresholds
    position_bias_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    verbosity_bias_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    self_preference_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    min_spearman_correlation: float = Field(default=0.85, ge=-1.0, le=1.0)

    @property
    def is_calibrated(self) -> bool:
        """Check if all bias rates are below thresholds and correlation is sufficient.

        Returns False if ANY bias exceeds its threshold or Spearman correlation
        falls below the minimum. This is an AND condition — all must pass.
        """
        return (
            self.position_bias_rate <= self.position_bias_threshold
            and self.verbosity_bias_rate <= self.verbosity_bias_threshold
            and self.self_preference_rate <= self.self_preference_threshold
            and self.spearman_correlation >= self.min_spearman_correlation
        )


class DriftSeverity(StrEnum):
    """Severity levels for drift detection alerts.

    Green: <2% drift — within normal variance
    Yellow: 2-5% drift — investigate, may need recalibration
    Red: >5% drift — immediate action required, halt quality gates
    """

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class DriftAlert(BaseModel):
    """A single metric regression alert from the drift detector.

    Captures baseline vs current value, the delta, and severity classification.
    Used by alerting interfaces (Slack, email, log) to communicate drift.
    """

    metric: str = Field(min_length=1)
    baseline_value: float
    current_value: float
    delta: float
    severity: DriftSeverity
    model_name: str | None = None
    model_version: str | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelVersion(BaseModel):
    """A tracked model version with baseline quality scores.

    The model registry stores one ModelVersion per detected version.
    Baseline scores are the quality metrics measured when the version was
    first detected, serving as the reference point for drift detection.
    """

    model_name: str
    version: str
    baseline_scores: dict[str, float]
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromptCacheStats(BaseModel):
    """Prompt caching performance metrics.

    IMPORTANT: RBAC partitioning fragments prompt cache prefixes.
    Single-tenant deployments achieve 55-65% hit rate.
    Multi-tenant (5 clients): 20-30% hit rate.
    Multi-tenant (20+ clients): 10-15% hit rate.

    The spec's 60% claim assumes single-tenant. Be honest about this.
    """

    hit_rate: float = Field(ge=0.0, le=1.0)
    miss_rate: float = Field(ge=0.0, le=1.0)
    savings_per_day_eur: float = Field(ge=0.0)
    total_prompts: int = Field(ge=0)
    static_token_ratio: float = Field(ge=0.0, le=1.0)
    deployment_type: str = "single_tenant"
    measured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
