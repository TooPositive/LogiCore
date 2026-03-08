"""Unit tests for Phase 4 telemetry domain models.

Tests: TraceRecord, CostSummary, EvalScore, CacheEntry, ModelRoute.
All costs in EUR, all timestamps in UTC.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError


class TestTraceRecord:
    """TraceRecord captures a single LLM call with full observability data."""

    def test_trace_record_creation_with_all_fields(self):
        from apps.api.src.domain.telemetry import TraceRecord

        now = datetime.now(UTC)
        record = TraceRecord(
            trace_id="trace-001",
            run_id="run-abc",
            agent_name="reader",
            model="gpt-5-mini",
            prompt_tokens=2800,
            completion_tokens=400,
            latency_ms=800.0,
            cost_eur=Decimal("0.0015"),
            timestamp=now,
            cache_hit=False,
        )
        assert record.trace_id == "trace-001"
        assert record.model == "gpt-5-mini"
        assert record.prompt_tokens == 2800
        assert record.completion_tokens == 400
        assert record.cost_eur == Decimal("0.0015")
        assert record.cache_hit is False
        assert record.timestamp == now

    def test_trace_record_defaults(self):
        from apps.api.src.domain.telemetry import TraceRecord

        record = TraceRecord(
            trace_id="trace-002",
            run_id="run-xyz",
            agent_name="auditor",
            model="gpt-5.2",
            prompt_tokens=8200,
            completion_tokens=1200,
            latency_ms=1500.0,
            cost_eur=Decimal("0.031"),
        )
        assert record.cache_hit is False
        assert record.user_id is None
        assert record.metadata is None
        # timestamp should default to approx now
        assert record.timestamp is not None
        assert (datetime.now(UTC) - record.timestamp).total_seconds() < 5

    def test_trace_record_cache_hit_zero_cost(self):
        """Cache hits MUST be recorded as EUR 0.00 cost."""
        from apps.api.src.domain.telemetry import TraceRecord

        record = TraceRecord(
            trace_id="trace-003",
            run_id="run-cache",
            agent_name="search",
            model="cache",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=2.0,
            cost_eur=Decimal("0.00"),
            cache_hit=True,
        )
        assert record.cache_hit is True
        assert record.cost_eur == Decimal("0.00")

    def test_trace_record_negative_cost_rejected(self):
        from apps.api.src.domain.telemetry import TraceRecord

        with pytest.raises(ValidationError):
            TraceRecord(
                trace_id="trace-bad",
                run_id="run-bad",
                agent_name="test",
                model="gpt-5-mini",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=100.0,
                cost_eur=Decimal("-0.01"),
            )

    def test_trace_record_negative_tokens_rejected(self):
        from apps.api.src.domain.telemetry import TraceRecord

        with pytest.raises(ValidationError):
            TraceRecord(
                trace_id="trace-bad",
                run_id="run-bad",
                agent_name="test",
                model="gpt-5-mini",
                prompt_tokens=-1,
                completion_tokens=50,
                latency_ms=100.0,
                cost_eur=Decimal("0.01"),
            )

    def test_trace_record_with_optional_metadata(self):
        from apps.api.src.domain.telemetry import TraceRecord

        record = TraceRecord(
            trace_id="trace-meta",
            run_id="run-meta",
            agent_name="router",
            model="gpt-5-nano",
            prompt_tokens=50,
            completion_tokens=5,
            latency_ms=50.0,
            cost_eur=Decimal("0.000025"),
            user_id="anna.schmidt",
            metadata={"routing_reason": "keyword_override", "complexity": "COMPLEX"},
        )
        assert record.user_id == "anna.schmidt"
        assert record.metadata["routing_reason"] == "keyword_override"


class TestCostSummary:
    """CostSummary aggregates costs by agent, user, or time period."""

    def test_cost_summary_creation(self):
        from apps.api.src.domain.telemetry import CostSummary

        summary = CostSummary(
            period_start=datetime(2026, 3, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 8, tzinfo=UTC),
            total_cost_eur=Decimal("47.00"),
            total_queries=1847,
            avg_cost_per_query_eur=Decimal("0.025"),
            cache_hit_rate=0.35,
            by_agent={"search": Decimal("1.20"), "audit": Decimal("1.55")},
        )
        assert summary.total_cost_eur == Decimal("47.00")
        assert summary.total_queries == 1847
        assert summary.cache_hit_rate == 0.35
        assert summary.by_agent["search"] == Decimal("1.20")

    def test_cost_summary_cache_hit_rate_bounds(self):
        from apps.api.src.domain.telemetry import CostSummary

        with pytest.raises(ValidationError):
            CostSummary(
                period_start=datetime(2026, 3, 1, tzinfo=UTC),
                period_end=datetime(2026, 3, 8, tzinfo=UTC),
                total_cost_eur=Decimal("10.00"),
                total_queries=100,
                avg_cost_per_query_eur=Decimal("0.10"),
                cache_hit_rate=1.5,  # > 1.0 is invalid
                by_agent={},
            )

    def test_cost_summary_negative_cache_hit_rate_rejected(self):
        from apps.api.src.domain.telemetry import CostSummary

        with pytest.raises(ValidationError):
            CostSummary(
                period_start=datetime(2026, 3, 1, tzinfo=UTC),
                period_end=datetime(2026, 3, 8, tzinfo=UTC),
                total_cost_eur=Decimal("10.00"),
                total_queries=100,
                avg_cost_per_query_eur=Decimal("0.10"),
                cache_hit_rate=-0.1,
                by_agent={},
            )

    def test_cost_summary_zero_queries(self):
        from apps.api.src.domain.telemetry import CostSummary

        summary = CostSummary(
            period_start=datetime(2026, 3, 1, tzinfo=UTC),
            period_end=datetime(2026, 3, 2, tzinfo=UTC),
            total_cost_eur=Decimal("0.00"),
            total_queries=0,
            avg_cost_per_query_eur=Decimal("0.00"),
            cache_hit_rate=0.0,
            by_agent={},
        )
        assert summary.total_queries == 0


class TestEvalScore:
    """EvalScore captures RAG quality metrics from LLM-as-Judge evaluation."""

    def test_eval_score_creation(self):
        from apps.api.src.domain.telemetry import EvalScore

        now = datetime.now(UTC)
        score = EvalScore(
            eval_id="eval-001",
            context_precision=0.92,
            faithfulness=0.89,
            answer_relevancy=0.91,
            evaluated_at=now,
            dataset_size=50,
        )
        assert score.context_precision == 0.92
        assert score.faithfulness == 0.89
        assert score.answer_relevancy == 0.91
        assert score.dataset_size == 50

    def test_eval_score_passes_quality_gate(self):
        """All metrics must be > 0.8 to pass CI gate."""
        from apps.api.src.domain.telemetry import EvalScore

        score = EvalScore(
            eval_id="eval-pass",
            context_precision=0.85,
            faithfulness=0.82,
            answer_relevancy=0.81,
            dataset_size=50,
        )
        assert score.passes_quality_gate(threshold=0.8) is True

    def test_eval_score_fails_quality_gate(self):
        from apps.api.src.domain.telemetry import EvalScore

        score = EvalScore(
            eval_id="eval-fail",
            context_precision=0.78,
            faithfulness=0.82,
            answer_relevancy=0.81,
            dataset_size=50,
        )
        assert score.passes_quality_gate(threshold=0.8) is False

    def test_eval_score_bounds_validation(self):
        from apps.api.src.domain.telemetry import EvalScore

        with pytest.raises(ValidationError):
            EvalScore(
                eval_id="eval-bad",
                context_precision=1.5,  # > 1.0
                faithfulness=0.89,
                answer_relevancy=0.91,
                dataset_size=50,
            )

    def test_eval_score_negative_rejected(self):
        from apps.api.src.domain.telemetry import EvalScore

        with pytest.raises(ValidationError):
            EvalScore(
                eval_id="eval-bad",
                context_precision=-0.1,
                faithfulness=0.89,
                answer_relevancy=0.91,
                dataset_size=50,
            )

    def test_eval_score_quality_gate_with_custom_threshold(self):
        from apps.api.src.domain.telemetry import EvalScore

        score = EvalScore(
            eval_id="eval-custom",
            context_precision=0.92,
            faithfulness=0.91,
            answer_relevancy=0.93,
            dataset_size=50,
        )
        # All above 0.9 -> pass
        assert score.passes_quality_gate(threshold=0.9) is True
        # 0.91 is NOT > 0.93 threshold -> fail
        assert score.passes_quality_gate(threshold=0.93) is False


class TestCacheEntry:
    """CacheEntry represents a cached LLM response in Redis."""

    def test_cache_entry_creation(self):
        from apps.api.src.domain.telemetry import CacheEntry

        now = datetime.now(UTC)
        entry = CacheEntry(
            cache_key="key-001",
            query="What is the penalty for late delivery?",
            response="The penalty is 2% per day...",
            embedding=[0.1] * 1536,
            clearance_level=2,
            departments=["logistics"],
            entity_keys=["PharmaCorp"],
            source_doc_ids=["doc-001", "doc-002"],
            created_at=now,
            ttl_seconds=86400,
        )
        assert entry.clearance_level == 2
        assert entry.departments == ["logistics"]
        assert entry.entity_keys == ["PharmaCorp"]
        assert len(entry.embedding) == 1536

    def test_cache_entry_rbac_partition_key(self):
        """RBAC partition key MUST include clearance_level + sorted departments."""
        from apps.api.src.domain.telemetry import CacheEntry

        entry = CacheEntry(
            cache_key="key-002",
            query="test query",
            response="test response",
            embedding=[0.0] * 10,
            clearance_level=3,
            departments=["management", "hr"],
            entity_keys=[],
            source_doc_ids=["doc-003"],
            ttl_seconds=86400,
        )
        partition = entry.rbac_partition_key()
        # Must include clearance level
        assert "3" in partition
        # Departments must be sorted (deterministic)
        assert "hr" in partition
        assert "management" in partition
        # Different clearance = different partition
        entry2 = entry.model_copy(update={"clearance_level": 1})
        assert entry2.rbac_partition_key() != entry.rbac_partition_key()

    def test_cache_entry_departments_sorted_in_partition(self):
        """Same departments in different order must produce same partition key."""
        from apps.api.src.domain.telemetry import CacheEntry

        kwargs = dict(
            cache_key="key-sort",
            query="test",
            response="test",
            embedding=[0.0] * 10,
            clearance_level=2,
            entity_keys=[],
            source_doc_ids=[],
            ttl_seconds=86400,
        )
        entry1 = CacheEntry(departments=["logistics", "hr", "management"], **kwargs)
        entry2 = CacheEntry(departments=["management", "logistics", "hr"], **kwargs)
        assert entry1.rbac_partition_key() == entry2.rbac_partition_key()

    def test_cache_entry_entity_keys_in_partition(self):
        """Entity keys (client names) must be included in the partition key."""
        from apps.api.src.domain.telemetry import CacheEntry

        kwargs = dict(
            cache_key="key-ent",
            query="test",
            response="test",
            embedding=[0.0] * 10,
            clearance_level=2,
            departments=["logistics"],
            source_doc_ids=[],
            ttl_seconds=86400,
        )
        entry1 = CacheEntry(entity_keys=["PharmaCorp"], **kwargs)
        entry2 = CacheEntry(entity_keys=["FreshFoods"], **kwargs)
        assert entry1.rbac_partition_key() != entry2.rbac_partition_key()

    def test_cache_entry_is_stale(self):
        """Staleness check: if source docs updated after cache entry created."""
        from apps.api.src.domain.telemetry import CacheEntry

        old_time = datetime(2026, 3, 1, tzinfo=UTC)
        entry = CacheEntry(
            cache_key="key-stale",
            query="test",
            response="test",
            embedding=[0.0] * 10,
            clearance_level=1,
            departments=["warehouse"],
            entity_keys=[],
            source_doc_ids=["doc-001"],
            created_at=old_time,
            ttl_seconds=86400,
        )
        # Doc updated AFTER cache entry
        assert entry.is_stale(doc_updated_at=datetime(2026, 3, 5, tzinfo=UTC)) is True
        # Doc updated BEFORE cache entry
        assert entry.is_stale(doc_updated_at=datetime(2026, 2, 28, tzinfo=UTC)) is False

    def test_cache_entry_clearance_validation(self):
        from apps.api.src.domain.telemetry import CacheEntry

        with pytest.raises(ValidationError):
            CacheEntry(
                cache_key="key-bad",
                query="test",
                response="test",
                embedding=[0.0] * 10,
                clearance_level=5,  # max is 4
                departments=["logistics"],
                entity_keys=[],
                source_doc_ids=[],
                ttl_seconds=86400,
            )


class TestModelRoute:
    """ModelRoute captures a routing decision with cost justification."""

    def test_model_route_simple(self):
        from apps.api.src.domain.telemetry import ModelRoute, QueryComplexity

        route = ModelRoute(
            query="What is shipment status?",
            complexity=QueryComplexity.SIMPLE,
            selected_model="gpt-5-nano",
            confidence=0.95,
            routing_reason="LLM classification: simple lookup",
        )
        assert route.complexity == QueryComplexity.SIMPLE
        assert route.selected_model == "gpt-5-nano"
        assert route.keyword_override is False

    def test_model_route_keyword_override(self):
        """Financial keywords force COMPLEX routing regardless of LLM classification."""
        from apps.api.src.domain.telemetry import ModelRoute, QueryComplexity

        route = ModelRoute(
            query="What is the penalty rate in the contract?",
            complexity=QueryComplexity.COMPLEX,
            selected_model="gpt-5.2",
            confidence=1.0,
            routing_reason="keyword_override: contract, penalty",
            keyword_override=True,
        )
        assert route.keyword_override is True
        assert route.complexity == QueryComplexity.COMPLEX

    def test_model_route_confidence_escalation(self):
        """Low confidence (< 0.7) should escalate one tier."""
        from apps.api.src.domain.telemetry import ModelRoute, QueryComplexity

        route = ModelRoute(
            query="explain the implications of clause 7",
            complexity=QueryComplexity.MEDIUM,
            selected_model="gpt-5.2",
            confidence=0.55,
            routing_reason="confidence < 0.7, escalated MEDIUM -> COMPLEX",
            escalated=True,
        )
        assert route.escalated is True
        assert route.confidence == 0.55

    def test_query_complexity_enum_values(self):
        from apps.api.src.domain.telemetry import QueryComplexity

        assert QueryComplexity.SIMPLE == "SIMPLE"
        assert QueryComplexity.MEDIUM == "MEDIUM"
        assert QueryComplexity.COMPLEX == "COMPLEX"

    def test_model_route_confidence_bounds(self):
        from apps.api.src.domain.telemetry import ModelRoute, QueryComplexity

        with pytest.raises(ValidationError):
            ModelRoute(
                query="test",
                complexity=QueryComplexity.SIMPLE,
                selected_model="gpt-5-nano",
                confidence=1.5,
                routing_reason="test",
            )
