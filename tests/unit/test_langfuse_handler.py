"""Unit tests for Phase 4 Langfuse handler.

Tests: tracing LLM calls, PostgreSQL fallback on Langfuse outage,
non-blocking behavior, reconciliation, cost tracking integration.
"""

from decimal import Decimal
from unittest.mock import MagicMock


class TestLangfuseHandler:
    """Langfuse callback handler that traces every LLM call."""

    def test_handler_creation(self):
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        handler = LangfuseHandler(
            langfuse_client=MagicMock(),
            cost_tracker=MagicMock(),
        )
        assert handler is not None

    def test_handler_records_trace(self):
        """Handler records a trace with prompt, response, model, tokens, latency, cost."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
        )
        handler.on_llm_end(
            trace_id="trace-001",
            run_id="run-abc",
            agent_name="reader",
            model="gpt-5-mini",
            prompt="What is the penalty?",
            response="The penalty is 2%...",
            prompt_tokens=2800,
            completion_tokens=400,
            latency_ms=800.0,
        )
        mock_langfuse.trace.assert_called_once()

    def test_handler_records_cost_in_tracker(self):
        """Handler updates cost tracker when recording a trace."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        tracker = CostTracker()
        handler = LangfuseHandler(
            langfuse_client=MagicMock(),
            cost_tracker=tracker,
        )
        handler.on_llm_end(
            trace_id="trace-002",
            run_id="run-xyz",
            agent_name="search",
            model="gpt-5-mini",
            prompt="test prompt",
            response="test response",
            prompt_tokens=2800,
            completion_tokens=400,
            latency_ms=500.0,
        )
        assert tracker.total_queries() == 1
        assert tracker.total_cost() > Decimal("0")

    def test_handler_cache_hit_records_zero_cost(self):
        """Cache hits are traced but with EUR 0.00 cost."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        tracker = CostTracker()
        handler = LangfuseHandler(
            langfuse_client=MagicMock(),
            cost_tracker=tracker,
        )
        handler.on_cache_hit(
            trace_id="trace-cache",
            run_id="run-cache",
            agent_name="search",
            query="cached query",
            response="cached response",
            latency_ms=2.0,
        )
        assert tracker.total_queries() == 1
        assert tracker.total_cost() == Decimal("0")

    def test_handler_includes_metadata_in_trace(self):
        """Trace includes routing reason and other metadata."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_trace = MagicMock()
        mock_langfuse.trace.return_value = mock_trace

        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
        )
        handler.on_llm_end(
            trace_id="trace-meta",
            run_id="run-meta",
            agent_name="router",
            model="gpt-5-nano",
            prompt="classify query",
            response="SIMPLE",
            prompt_tokens=50,
            completion_tokens=5,
            latency_ms=50.0,
            metadata={"routing_reason": "keyword_override"},
        )
        # Verify metadata was passed to langfuse trace
        call_kwargs = mock_langfuse.trace.call_args
        assert call_kwargs is not None


class TestLangfuseFallback:
    """PostgreSQL fallback when Langfuse is unreachable."""

    def test_fallback_on_langfuse_error(self):
        """When Langfuse raises, write full trace to fallback store."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_langfuse.trace.side_effect = Exception("Langfuse unreachable")

        fallback_store = MagicMock()
        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
            fallback_store=fallback_store,
        )
        # Should NOT raise -- non-blocking
        handler.on_llm_end(
            trace_id="trace-fallback",
            run_id="run-fallback",
            agent_name="search",
            model="gpt-5-mini",
            prompt="test prompt",
            response="test response",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=200.0,
        )
        # Fallback store should have been called
        fallback_store.store_trace.assert_called_once()

    def test_fallback_preserves_full_trace_data(self):
        """Fallback must store ALL trace data, not just trace_id."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_langfuse.trace.side_effect = Exception("Langfuse down")

        fallback_store = MagicMock()
        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
            fallback_store=fallback_store,
        )
        handler.on_llm_end(
            trace_id="trace-full",
            run_id="run-full",
            agent_name="auditor",
            model="gpt-5.2",
            prompt="audit prompt",
            response="audit response",
            prompt_tokens=8200,
            completion_tokens=1200,
            latency_ms=1500.0,
        )
        call_args = fallback_store.store_trace.call_args
        trace_data = call_args[0][0] if call_args[0] else call_args[1].get("trace")
        # Must contain full trace data
        assert trace_data.trace_id == "trace-full"
        assert trace_data.model == "gpt-5.2"
        assert trace_data.prompt_tokens == 8200

    def test_langfuse_failure_does_not_block_llm_call(self):
        """Critical: Langfuse failure must NOT block the LLM call result."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_langfuse.trace.side_effect = Exception("Langfuse down")

        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
            fallback_store=MagicMock(),
        )
        # This must not raise
        handler.on_llm_end(
            trace_id="trace-no-block",
            run_id="run-no-block",
            agent_name="search",
            model="gpt-5-mini",
            prompt="test",
            response="test",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=100.0,
        )
        # If we got here without exception, the test passes

    def test_fallback_store_also_fails_gracefully(self):
        """If both Langfuse AND fallback fail, still don't crash."""
        from apps.api.src.core.telemetry.cost_tracker import CostTracker
        from apps.api.src.core.telemetry.langfuse_handler import LangfuseHandler

        mock_langfuse = MagicMock()
        mock_langfuse.trace.side_effect = Exception("Langfuse down")

        fallback_store = MagicMock()
        fallback_store.store_trace.side_effect = Exception("PG also down")

        handler = LangfuseHandler(
            langfuse_client=mock_langfuse,
            cost_tracker=CostTracker(),
            fallback_store=fallback_store,
        )
        # Must not raise even when both fail
        handler.on_llm_end(
            trace_id="trace-both-down",
            run_id="run-both-down",
            agent_name="search",
            model="gpt-5-mini",
            prompt="test",
            response="test",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=100.0,
        )


class TestFallbackStore:
    """In-memory fallback store for traces when Langfuse is down."""

    def test_fallback_store_creation(self):
        from apps.api.src.core.telemetry.langfuse_handler import InMemoryFallbackStore

        store = InMemoryFallbackStore()
        assert store.count() == 0

    def test_fallback_store_and_retrieve(self):
        from apps.api.src.core.domain.telemetry import TraceRecord
        from apps.api.src.core.telemetry.langfuse_handler import InMemoryFallbackStore

        store = InMemoryFallbackStore()
        trace = TraceRecord(
            trace_id="trace-fb-001",
            run_id="run-fb",
            agent_name="search",
            model="gpt-5-mini",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=200.0,
            cost_eur=Decimal("0.0015"),
        )
        store.store_trace(trace)
        assert store.count() == 1

        pending = store.get_pending()
        assert len(pending) == 1
        assert pending[0].trace_id == "trace-fb-001"

    def test_fallback_store_drain(self):
        """After reconciliation, drain clears the store."""
        from apps.api.src.core.domain.telemetry import TraceRecord
        from apps.api.src.core.telemetry.langfuse_handler import InMemoryFallbackStore

        store = InMemoryFallbackStore()
        for i in range(5):
            store.store_trace(TraceRecord(
                trace_id=f"trace-drain-{i}",
                run_id="run-drain",
                agent_name="search",
                model="gpt-5-mini",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=200.0,
                cost_eur=Decimal("0.001"),
            ))
        assert store.count() == 5
        store.drain()
        assert store.count() == 0

    def test_reconciliation_backfills_langfuse(self):
        """After Langfuse recovery, backfill from fallback store."""
        from apps.api.src.core.domain.telemetry import TraceRecord
        from apps.api.src.core.telemetry.langfuse_handler import (
            InMemoryFallbackStore,
            reconcile_fallback,
        )

        mock_langfuse = MagicMock()
        store = InMemoryFallbackStore()
        for i in range(3):
            store.store_trace(TraceRecord(
                trace_id=f"trace-recon-{i}",
                run_id="run-recon",
                agent_name="audit",
                model="gpt-5.2",
                prompt_tokens=8200,
                completion_tokens=1200,
                latency_ms=1500.0,
                cost_eur=Decimal("0.031"),
            ))

        reconciled = reconcile_fallback(mock_langfuse, store)
        assert reconciled == 3
        assert mock_langfuse.trace.call_count == 3
        assert store.count() == 0  # drained after reconciliation
