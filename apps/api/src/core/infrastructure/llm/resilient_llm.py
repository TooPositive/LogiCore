"""Factory for building a resilient ProviderChain from Settings.

Combines CircuitBreaker + RetryPolicy + ProviderChain + ResponseQualityGate
into a single factory function. The chain is configured based on which
provider is set as primary in settings.

Primary = azure -> fallback = ollama (and vice versa).
Each provider gets its own CircuitBreaker with settings-driven thresholds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.api.src.core.infrastructure.llm.azure_openai import AzureOpenAIProvider
from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderEntry,
    ResponseQualityGate,
)
from apps.api.src.core.infrastructure.llm.retry import RetryPolicy

if TYPE_CHECKING:
    from apps.api.src.core.config.settings import Settings
    from apps.api.src.core.infrastructure.llm.provider_chain import CacheLookupFn


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
