"""Configurable re-ranking module with circuit breaker pattern.

Five reranker implementations:
1. NoOpReranker      — pass-through (baseline benchmarks)
2. CohereReranker    — cloud re-ranking via Cohere Rerank API (httpx, not SDK)
3. LocalCrossEncoderReranker — local cross-encoder (sentence-transformers)
4. CircuitBreakerReranker    — wraps primary + fallback with circuit breaker
5. BaseReranker      — ABC defining the interface

All rerankers are async. All accept configurable parameters (model, top_k,
confidence_threshold, circuit breaker thresholds). No hardcoded values.

RerankResult carries both original_score (from vector search) and
rerank_score (from cross-encoder) for A/B comparison.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None  # type: ignore[assignment,misc]


class RerankerStrategy(StrEnum):
    COHERE = "cohere"
    LOCAL_CROSS_ENCODER = "local_cross_encoder"
    NOOP = "noop"


class RerankerError(Exception):
    """Raised when re-ranking fails."""


@dataclass
class RerankResult:
    """A re-ranked document with both original and new scores/ranks."""

    content: str
    original_score: float
    rerank_score: float
    source: str
    document_id: str
    chunk_index: int
    original_rank: int
    new_rank: int


class BaseReranker(ABC):
    """Abstract base class for all re-ranking strategies."""

    @abstractmethod
    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        """Re-rank search results.

        Input: objects with content, score, source, document_id, chunk_index.
        Output: RerankResult list sorted by rerank_score descending.
        """
        ...


def _to_rerank_results(
    results: list[Any],
    scores: list[float],
    top_k: int,
    confidence_threshold: float,
) -> list[RerankResult]:
    """Build RerankResult list from original results + new scores.

    Sorts by score descending, applies top_k and confidence filtering.
    """
    indexed = list(zip(range(len(results)), results, scores))
    # Sort by rerank score descending
    indexed.sort(key=lambda x: x[2], reverse=True)

    # Apply confidence threshold
    indexed = [(i, r, s) for i, r, s in indexed if s >= confidence_threshold]

    # Apply top_k
    indexed = indexed[:top_k]

    return [
        RerankResult(
            content=r.content,
            original_score=r.score,
            rerank_score=s,
            source=r.source,
            document_id=r.document_id,
            chunk_index=r.chunk_index,
            original_rank=orig_rank,
            new_rank=new_rank,
        )
        for new_rank, (orig_rank, r, s) in enumerate(indexed)
    ]


# ---------------------------------------------------------------------------
# NoOpReranker
# ---------------------------------------------------------------------------


class NoOpReranker(BaseReranker):
    """Pass-through. No re-ranking. For baseline comparison."""

    def __init__(self, confidence_threshold: float = 0.0) -> None:
        self.confidence_threshold = confidence_threshold

    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        if not results:
            return []

        scores = [r.score for r in results]
        return _to_rerank_results(results, scores, top_k, self.confidence_threshold)


# ---------------------------------------------------------------------------
# CohereReranker
# ---------------------------------------------------------------------------

COHERE_RERANK_URL = "https://api.cohere.com/v2/rerank"


class CohereReranker(BaseReranker):
    """Cloud re-ranking via Cohere Rerank API.

    Uses httpx directly (not the cohere SDK) to keep dependencies minimal.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "rerank-v3.5",
        confidence_threshold: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.confidence_threshold = confidence_threshold

    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        if not results:
            return []

        documents = [r.content for r in results]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    COHERE_RERANK_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": query,
                        "documents": documents,
                        "model": self.model,
                        "top_n": len(documents),
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise RerankerError(f"Cohere rerank API failed: {exc}") from exc

        # Map API results back: build per-index score mapping
        score_map: dict[int, float] = {}
        for item in data["results"]:
            score_map[item["index"]] = item["relevance_score"]

        scores = [score_map.get(i, 0.0) for i in range(len(results))]
        return _to_rerank_results(results, scores, top_k, self.confidence_threshold)


# ---------------------------------------------------------------------------
# LocalCrossEncoderReranker
# ---------------------------------------------------------------------------


class LocalCrossEncoderReranker(BaseReranker):
    """Local cross-encoder for air-gapped deployments or fallback.

    Uses sentence-transformers CrossEncoder. The model is loaded lazily
    on the first rerank() call.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2",
        confidence_threshold: float = 0.0,
    ) -> None:
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self._model = None

    def _load_model(self):
        """Lazy-load the cross-encoder model."""
        if CrossEncoder is None:
            raise RerankerError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers"
            )
        self._model = CrossEncoder(self.model_name)

    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        if not results:
            return []

        try:
            if self._model is None:
                self._load_model()

            pairs = [[query, r.content] for r in results]
            raw_scores = self._model.predict(pairs)
            scores = [float(s) for s in raw_scores]
        except RerankerError:
            raise
        except Exception as exc:
            raise RerankerError(
                f"Local cross-encoder re-ranking failed: {exc}"
            ) from exc

        return _to_rerank_results(results, scores, top_k, self.confidence_threshold)


# ---------------------------------------------------------------------------
# CircuitBreakerReranker (uses generic CircuitBreaker from Phase 7)
# ---------------------------------------------------------------------------


class CircuitBreakerReranker(BaseReranker):
    """Wraps a primary reranker with circuit breaker + fallback.

    Uses the generic CircuitBreaker from core/infrastructure/llm/circuit_breaker.py.
    On primary failure or circuit open, falls back to the fallback reranker.

    States (managed by CircuitBreaker):
    - CLOSED:    Normal operation, using primary. Tracks consecutive failures.
    - OPEN:      Primary is down. All calls go to fallback. After
                 recovery_timeout, transitions to HALF_OPEN.
    - HALF_OPEN: Tries primary once. If success -> CLOSED. If fail -> OPEN.
    """

    def __init__(
        self,
        primary: BaseReranker,
        fallback: BaseReranker,
        failure_threshold: int = 3,
        recovery_timeout: float = 60.0,
    ) -> None:
        from apps.api.src.core.infrastructure.llm.circuit_breaker import (
            CircuitBreaker,
        )

        self.primary = primary
        self.fallback = fallback
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._breaker = CircuitBreaker(
            name="reranker",
            failure_threshold=failure_threshold,
            reset_timeout=recovery_timeout,
            success_threshold=1,  # Original behavior: one success closes
        )

    async def rerank(
        self, query: str, results: list[Any], top_k: int = 5
    ) -> list[RerankResult]:
        from apps.api.src.core.infrastructure.llm.circuit_breaker import (
            CircuitOpenError,
        )

        try:
            return await self._breaker.call(
                self.primary.rerank, query, results, top_k
            )
        except CircuitOpenError:
            return await self.fallback.rerank(query, results, top_k)
        except Exception:
            return await self.fallback.rerank(query, results, top_k)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_reranker(strategy: RerankerStrategy | str, **kwargs) -> BaseReranker:
    """Factory function to create a reranker by strategy name.

    All parameters are passed through as kwargs to the reranker constructor.
    """
    strategy_str = str(strategy)

    constructors: dict[str, type[BaseReranker]] = {
        RerankerStrategy.COHERE: CohereReranker,
        RerankerStrategy.LOCAL_CROSS_ENCODER: LocalCrossEncoderReranker,
        RerankerStrategy.NOOP: NoOpReranker,
    }

    if strategy_str not in constructors:
        raise ValueError(
            f"Unknown reranker strategy: {strategy_str!r}. "
            f"Valid strategies: {list(constructors.keys())}"
        )

    return constructors[strategy_str](**kwargs)
