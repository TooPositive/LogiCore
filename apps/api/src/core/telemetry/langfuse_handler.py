"""Langfuse callback handler for LLM call tracing.

Traces every LLM call with: prompt, response, model, tokens, latency, cost.
Works with LangGraph agents.

CRITICAL: Langfuse failure must NOT block the LLM call.
Fallback: when Langfuse is unreachable, write full trace to fallback store.
Reconciliation: backfill Langfuse from fallback store after recovery.
"""

import logging
from typing import Any

from apps.api.src.core.domain.telemetry import TraceRecord
from apps.api.src.core.telemetry.cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class InMemoryFallbackStore:
    """In-memory fallback store for traces when Langfuse is unavailable.

    In production, replace with PostgreSQL-backed store for persistence
    across restarts. This implementation is sufficient for single-process
    use and testing.
    """

    def __init__(self) -> None:
        self._traces: list[TraceRecord] = []

    def store_trace(self, trace: TraceRecord) -> None:
        self._traces.append(trace)

    def get_pending(self) -> list[TraceRecord]:
        return list(self._traces)

    def count(self) -> int:
        return len(self._traces)

    def drain(self) -> None:
        """Clear all pending traces (after successful reconciliation)."""
        self._traces.clear()


def reconcile_fallback(
    langfuse_client: Any,
    fallback_store: InMemoryFallbackStore,
) -> int:
    """Backfill Langfuse from fallback store after recovery.

    Returns the number of traces successfully reconciled.
    """
    pending = fallback_store.get_pending()
    reconciled = 0
    for trace in pending:
        langfuse_client.trace(
            name=trace.agent_name,
            id=trace.trace_id,
            metadata={
                "run_id": trace.run_id,
                "model": trace.model,
                "prompt_tokens": trace.prompt_tokens,
                "completion_tokens": trace.completion_tokens,
                "latency_ms": trace.latency_ms,
                "cost_eur": str(trace.cost_eur),
                "cache_hit": trace.cache_hit,
                "reconciled": True,
            },
        )
        reconciled += 1

    fallback_store.drain()
    return reconciled


class LangfuseHandler:
    """Callback handler that traces every LLM call to Langfuse.

    Non-blocking: Langfuse failure logs a warning and writes to
    fallback_store, but never blocks the LLM call result.
    """

    def __init__(
        self,
        langfuse_client: Any,
        cost_tracker: CostTracker,
        fallback_store: InMemoryFallbackStore | None = None,
    ) -> None:
        self._langfuse = langfuse_client
        self._cost_tracker = cost_tracker
        self._fallback = fallback_store or InMemoryFallbackStore()

    def on_llm_end(
        self,
        trace_id: str,
        run_id: str,
        agent_name: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record an LLM call completion.

        1. Calculate cost via cost tracker
        2. Attempt to write trace to Langfuse
        3. On Langfuse failure: write full trace to fallback store
        4. Never raise -- non-blocking
        """
        cost = self._cost_tracker.record(
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            user_id=user_id,
        )

        trace = TraceRecord(
            trace_id=trace_id,
            run_id=run_id,
            agent_name=agent_name,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            cost_eur=cost,
            user_id=user_id,
            metadata=metadata,
        )

        try:
            self._langfuse.trace(
                name=agent_name,
                id=trace_id,
                input=prompt,
                output=response,
                metadata={
                    "run_id": run_id,
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "latency_ms": latency_ms,
                    "cost_eur": str(cost),
                    **(metadata or {}),
                },
            )
        except Exception:
            logger.warning(
                "Langfuse unavailable for trace %s, writing to fallback",
                trace_id,
            )
            try:
                self._fallback.store_trace(trace)
            except Exception:
                logger.error(
                    "Both Langfuse and fallback store failed for trace %s",
                    trace_id,
                )

    def on_cache_hit(
        self,
        trace_id: str,
        run_id: str,
        agent_name: str,
        query: str,
        response: str,
        latency_ms: float,
        user_id: str | None = None,
    ) -> None:
        """Record a cache hit (EUR 0.00 cost)."""
        self._cost_tracker.record(
            agent_name=agent_name,
            model="cache",
            prompt_tokens=0,
            completion_tokens=0,
            user_id=user_id,
            cache_hit=True,
        )

        try:
            self._langfuse.trace(
                name=f"{agent_name}:cache_hit",
                id=trace_id,
                input=query,
                output=response,
                metadata={
                    "run_id": run_id,
                    "cache_hit": True,
                    "latency_ms": latency_ms,
                    "cost_eur": "0.00",
                },
            )
        except Exception:
            logger.warning(
                "Langfuse unavailable for cache hit trace %s", trace_id
            )
