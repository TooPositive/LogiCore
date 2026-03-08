"""Ordered fallback chain for LLM providers.

Tries providers in order, each with its own CircuitBreaker + optional
RetryPolicy. If all providers fail, falls back to a cache lookup
function with disclaimer text. If cache also misses, raises
AllProvidersDownError.

Domain-agnostic: works for any LLM provider that satisfies the
LLMProvider Protocol.

Response metadata includes: which provider served, whether fallback
was used, whether cache was used, and optional disclaimer text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.retry import RetryPolicy

logger = logging.getLogger(__name__)

# Type alias for the async cache lookup function
CacheLookupFn = Callable[[str], Coroutine[Any, Any, str | None]]


class AllProvidersDownError(Exception):
    """Raised when all providers in the chain have failed and cache missed."""

    pass


class ResponseQualityGate:
    """Validates response quality to catch 200-OK-garbage.

    If a provider returns an empty or too-short response, it should
    count as a failure and trigger fallback to the next provider.
    The analysis identified this as the most expensive silent failure
    mode (EUR 500-5,000/incident).

    Args:
        min_length: Minimum response length (after stripping whitespace).
    """

    def __init__(self, min_length: int = 10) -> None:
        self.min_length = min_length

    def is_acceptable(self, response: LLMResponse) -> bool:
        """Check if response meets minimum quality standards."""
        content = response.content.strip()
        if len(content) < self.min_length:
            return False
        return True


@dataclass(frozen=True)
class ProviderChainResponse:
    """Response from the provider chain with routing metadata.

    Extends the concept of LLMResponse with fallback/cache information.
    """

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    provider_name: str
    fallback_used: bool
    cache_used: bool
    disclaimer: str | None = None

    @property
    def is_degraded(self) -> bool:
        """True if response came from a fallback or cache."""
        return self.fallback_used or self.cache_used

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed."""
        return self.input_tokens + self.output_tokens


@dataclass
class ProviderEntry:
    """A provider with its circuit breaker and optional retry policy."""

    provider: Any  # LLMProvider (structural subtyping)
    breaker: CircuitBreaker
    retry: RetryPolicy | None = None


class ProviderChain:
    """Try providers in order until one succeeds.

    Args:
        providers: Ordered list of ProviderEntry (primary first).
        cache_lookup: Optional async function that returns a cached
                      response string or None on miss.
    """

    def __init__(
        self,
        providers: list[ProviderEntry],
        cache_lookup: CacheLookupFn | None = None,
        quality_gate: ResponseQualityGate | None = None,
    ) -> None:
        self._providers = providers
        self._cache_lookup = cache_lookup
        self._quality_gate = quality_gate

        # Stats tracking
        self._total_requests = 0
        self._by_provider: dict[str, int] = {}
        self._fallback_count = 0
        self._cache_fallback_count = 0

    async def generate(self, prompt: str, **kwargs: Any) -> ProviderChainResponse:
        """Generate a response, trying providers in order.

        Falls back through the chain on failure. Last resort: cache.
        """
        return await self._try_providers(
            prompt, method="generate", **kwargs
        )

    async def generate_structured(
        self, prompt: str, **kwargs: Any
    ) -> ProviderChainResponse:
        """Generate a structured response, trying providers in order."""
        return await self._try_providers(
            prompt, method="generate_structured", **kwargs
        )

    async def _try_providers(
        self, prompt: str, method: str = "generate", **kwargs: Any
    ) -> ProviderChainResponse:
        """Try each provider in order. Fall back on failure."""
        self._total_requests += 1
        is_fallback = False

        for i, entry in enumerate(self._providers):
            if i > 0:
                is_fallback = True

            try:
                result = await self._call_provider(entry, prompt, method, **kwargs)

                # Quality gate check: catch 200-OK-garbage
                if self._quality_gate and not self._quality_gate.is_acceptable(result):
                    logger.warning(
                        "Provider '%s' returned low-quality response "
                        "(length=%d, min=%d). Trying next.",
                        entry.provider.model_name,
                        len(result.content.strip()),
                        self._quality_gate.min_length,
                    )
                    # Count as failure in the circuit breaker
                    entry.breaker._on_failure()
                    continue

                # Track stats
                provider_name = entry.provider.model_name
                self._by_provider[provider_name] = (
                    self._by_provider.get(provider_name, 0) + 1
                )
                if is_fallback:
                    self._fallback_count += 1

                return ProviderChainResponse(
                    content=result.content,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    latency_ms=result.latency_ms,
                    provider_name=provider_name,
                    fallback_used=is_fallback,
                    cache_used=False,
                )
            except (CircuitOpenError, Exception) as exc:
                logger.warning(
                    "Provider '%s' failed: %s. Trying next.",
                    entry.provider.model_name,
                    exc,
                )
                continue

        # All providers failed — try cache
        if self._cache_lookup is not None:
            cached = await self._cache_lookup(prompt)
            if cached is not None:
                self._cache_fallback_count += 1
                self._fallback_count += 1
                return ProviderChainResponse(
                    content=cached,
                    model="cache",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0.0,
                    provider_name="cache",
                    fallback_used=True,
                    cache_used=True,
                    disclaimer=(
                        "This response is from cache -- "
                        "live AI providers are currently unavailable."
                    ),
                )

        raise AllProvidersDownError(
            "All LLM providers are down and no cached response available."
        )

    async def _call_provider(
        self,
        entry: ProviderEntry,
        prompt: str,
        method: str,
        **kwargs: Any,
    ) -> LLMResponse:
        """Call a provider through its circuit breaker and optional retry."""
        provider_method = getattr(entry.provider, method)

        async def call_fn(p: str, **kw: Any) -> LLMResponse:
            return await entry.breaker.call(provider_method, p, **kw)

        if entry.retry is not None:
            return await entry.retry.execute(call_fn, prompt, **kwargs)
        else:
            return await call_fn(prompt, **kwargs)

    def provider_states(self) -> list[dict[str, Any]]:
        """Get current state of all providers."""
        return [entry.breaker.metrics_snapshot() for entry in self._providers]

    def stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        return {
            "total_requests": self._total_requests,
            "by_provider": dict(self._by_provider),
            "fallback_count": self._fallback_count,
            "cache_fallback_count": self._cache_fallback_count,
        }
