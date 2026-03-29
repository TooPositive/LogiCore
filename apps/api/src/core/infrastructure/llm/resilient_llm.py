"""Resilient LLM infrastructure: factory + orchestrator.

Two main exports:
1. build_provider_chain() — factory that builds a ProviderChain from Settings
2. ResilientLLM — orchestrator combining ModelRouter + ProviderChain

The ResilientLLM is the top-level entry point for LLM calls in the system.
It classifies query complexity, selects the appropriate provider chain
for the tier, and returns a response with full routing metadata.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.api.src.core.domain.telemetry import QueryComplexity
from apps.api.src.core.infrastructure.llm.azure_openai import AzureOpenAIProvider
from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderChainResponse,
    ProviderEntry,
    ResponseQualityGate,
)
from apps.api.src.core.infrastructure.llm.retry import RetryPolicy

if TYPE_CHECKING:
    from apps.api.src.core.config.settings import Settings
    from apps.api.src.core.infrastructure.llm.provider_chain import CacheLookupFn
    from apps.api.src.core.infrastructure.llm.router import ModelRouter

logger = logging.getLogger(__name__)


def build_provider_chain(
    settings: Settings,
    cache_lookup: CacheLookupFn | None = None,
) -> ProviderChain:
    """Build a resilient ProviderChain from application settings.

    Provider order depends on settings.llm_provider:
    - 'azure': Azure primary, Ollama fallback
    - 'ollama': Ollama primary, Azure fallback

    Each provider gets:
    - CircuitBreaker with settings-driven thresholds
    - RetryPolicy with exponential backoff + jitter
    """
    from apps.api.src.core.config.settings import Settings

    if not isinstance(settings, Settings):
        raise TypeError(f"Expected Settings, got {type(settings)}")

    # Build retry policy
    retry = RetryPolicy(
        max_retries=settings.retry_max_attempts,
        base_delay=settings.retry_base_delay,
        max_delay=settings.retry_max_delay,
        jitter=True,
        retriable_exceptions=(TimeoutError, ConnectionError),
    )

    # Build quality gate
    quality_gate = ResponseQualityGate(
        min_length=settings.quality_gate_min_length,
    )

    # Build providers
    azure_provider = AzureOpenAIProvider(
        endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
    )
    azure_breaker = CircuitBreaker(
        name="azure",
        failure_threshold=settings.circuit_breaker_failure_threshold,
        reset_timeout=settings.circuit_breaker_reset_timeout,
        success_threshold=settings.circuit_breaker_success_threshold,
    )

    ollama_provider = OllamaProvider(
        host=settings.ollama_host,
        model=settings.ollama_model,
    )
    ollama_breaker = CircuitBreaker(
        name="ollama",
        failure_threshold=settings.circuit_breaker_failure_threshold,
        reset_timeout=settings.circuit_breaker_reset_timeout,
        success_threshold=settings.circuit_breaker_success_threshold,
    )

    # Order depends on which is primary
    if settings.llm_provider == "azure":
        providers = [
            ProviderEntry(provider=azure_provider, breaker=azure_breaker, retry=retry),
            ProviderEntry(provider=ollama_provider, breaker=ollama_breaker, retry=retry),
        ]
    else:
        providers = [
            ProviderEntry(provider=ollama_provider, breaker=ollama_breaker, retry=retry),
            ProviderEntry(provider=azure_provider, breaker=azure_breaker, retry=retry),
        ]

    return ProviderChain(
        providers=providers,
        cache_lookup=cache_lookup,
        quality_gate=quality_gate,
    )


class ResilientLLM:
    """Orchestrator combining ModelRouter + ProviderChain.

    The top-level entry point for LLM calls. Flow:
    1. ModelRouter classifies query complexity (SIMPLE/MEDIUM/COMPLEX)
    2. Tier-specific or default ProviderChain handles the call
    3. ProviderChain manages fallback, circuit breaking, retry, quality gate

    Args:
        router: ModelRouter for query complexity classification.
        default_chain: Default ProviderChain for all tiers without a specific chain.
        tier_chains: Optional per-tier ProviderChains (e.g., COMPLEX -> GPT-5.2 chain).
    """

    def __init__(
        self,
        router: ModelRouter,
        default_chain: ProviderChain,
        tier_chains: dict[QueryComplexity, ProviderChain] | None = None,
    ) -> None:
        self._router = router
        self._default_chain = default_chain
        self._tier_chains = tier_chains or {}

        # Routing stats
        self._total_routed = 0
        self._by_complexity: dict[str, int] = {}

    async def generate(self, prompt: str, **kwargs: Any) -> ProviderChainResponse:
        """Classify query and generate response via the appropriate chain."""
        route = await self._router.classify(prompt)
        chain = self._tier_chains.get(route.complexity, self._default_chain)

        self._total_routed += 1
        complexity_key = route.complexity.value
        self._by_complexity[complexity_key] = (
            self._by_complexity.get(complexity_key, 0) + 1
        )

        logger.info(
            "Routing query to %s tier (complexity=%s, model=%s, reason=%s)",
            complexity_key,
            route.complexity.value,
            route.selected_model,
            route.routing_reason,
        )

        return await chain.generate(prompt, **kwargs)

    async def generate_structured(
        self, prompt: str, **kwargs: Any
    ) -> ProviderChainResponse:
        """Classify query and generate structured response."""
        route = await self._router.classify(prompt)
        chain = self._tier_chains.get(route.complexity, self._default_chain)

        self._total_routed += 1
        complexity_key = route.complexity.value
        self._by_complexity[complexity_key] = (
            self._by_complexity.get(complexity_key, 0) + 1
        )

        return await chain.generate_structured(prompt, **kwargs)

    def stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        return {
            "total_routed": self._total_routed,
            "by_complexity": dict(self._by_complexity),
            "chain_stats": self._default_chain.stats(),
        }

    def provider_states(self) -> dict[str, Any]:
        """Get provider states across all chains."""
        states: dict[str, Any] = {
            "default": self._default_chain.provider_states(),
        }
        for tier, chain in self._tier_chains.items():
            states[tier.value] = chain.provider_states()
        return states
