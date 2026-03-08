"""Tests for ProviderChain — ordered fallback across LLM providers.

Tries providers in order, each with its own CircuitBreaker + RetryPolicy.
Last resort: SemanticCache lookup with disclaimer text.

RED phase: all tests written before implementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    AllProvidersDownError,
    ProviderChain,
    ProviderChainResponse,
    ProviderEntry,
)
from apps.api.src.core.infrastructure.llm.retry import RetryPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(name: str, response_content: str = "response") -> MagicMock:
    """Create a mock LLMProvider."""
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(
            content=response_content,
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    provider.generate_structured = AsyncMock(
        return_value=LLMResponse(
            content='{"key": "value"}',
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    return provider


def _make_failing_provider(name: str, error: Exception | None = None) -> MagicMock:
    """Create a mock LLMProvider that always fails."""
    provider = MagicMock()
    provider.model_name = name
    exc = error or Exception(f"{name} is down")
    provider.generate = AsyncMock(side_effect=exc)
    provider.generate_structured = AsyncMock(side_effect=exc)
    return provider


# ===========================================================================
# ProviderChainResponse tests
# ===========================================================================


class TestProviderChainResponse:
    def test_extends_llm_response(self):
        r = ProviderChainResponse(
            content="hello",
            model="gpt-5",
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
            provider_name="azure",
            fallback_used=False,
            cache_used=False,
        )
        assert r.content == "hello"
        assert r.provider_name == "azure"
        assert r.fallback_used is False
        assert r.cache_used is False
        assert r.disclaimer is None

    def test_with_disclaimer(self):
        r = ProviderChainResponse(
            content="cached answer",
            model="cache",
            input_tokens=0,
            output_tokens=0,
            latency_ms=5.0,
            provider_name="cache",
            fallback_used=True,
            cache_used=True,
            disclaimer="Served from cache -- live providers unavailable",
        )
        assert r.cache_used is True
        assert "cache" in r.disclaimer

    def test_is_degraded_when_fallback(self):
        r = ProviderChainResponse(
            content="response",
            model="ollama",
            input_tokens=10,
            output_tokens=20,
            latency_ms=200.0,
            provider_name="ollama",
            fallback_used=True,
            cache_used=False,
        )
        assert r.is_degraded is True

    def test_is_not_degraded_when_primary(self):
        r = ProviderChainResponse(
            content="response",
            model="gpt-5",
            input_tokens=10,
            output_tokens=20,
            latency_ms=200.0,
            provider_name="azure",
            fallback_used=False,
            cache_used=False,
        )
        assert r.is_degraded is False


# ===========================================================================
# ProviderChain — happy path
# ===========================================================================


class TestProviderChainHappyPath:
    @pytest.mark.asyncio
    async def test_uses_first_provider(self):
        """When primary is healthy, use it directly."""
        primary = _make_provider("azure-gpt5", "primary response")
        fallback = _make_provider("ollama", "fallback response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
                ProviderEntry(provider=fallback, breaker=CircuitBreaker(name="ollama")),
            ]
        )

        result = await chain.generate("hello")
        assert result.content == "primary response"
        assert result.provider_name == "azure-gpt5"
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_passes_kwargs_to_provider(self):
        primary = _make_provider("azure-gpt5")
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
            ]
        )

        await chain.generate("hello", temperature=0.5)
        primary.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_includes_latency(self):
        primary = _make_provider("azure-gpt5")
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
            ]
        )
        result = await chain.generate("hello")
        assert result.latency_ms > 0


# ===========================================================================
# ProviderChain — fallback
# ===========================================================================


class TestProviderChainFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_primary_error(self):
        """If primary fails, try the next provider."""
        primary = _make_failing_provider("azure-gpt5")
        fallback = _make_provider("ollama", "fallback response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        result = await chain.generate("hello")
        assert result.content == "fallback response"
        assert result.provider_name == "ollama"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_falls_back_on_circuit_open(self):
        """If primary circuit is open, skip to fallback."""
        primary = _make_failing_provider("azure-gpt5")
        fallback = _make_provider("ollama", "fallback response")

        breaker = CircuitBreaker(name="azure", failure_threshold=1, reset_timeout=60.0)

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=breaker),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        # First call: trips the breaker
        result1 = await chain.generate("hello")
        assert result1.provider_name == "ollama"

        # Second call: breaker is open, should skip directly to fallback
        result2 = await chain.generate("world")
        assert result2.provider_name == "ollama"
        assert result2.fallback_used is True

    @pytest.mark.asyncio
    async def test_three_provider_cascade(self):
        """If first two fail, use third."""
        p1 = _make_failing_provider("azure")
        p2 = _make_failing_provider("ollama")
        p3 = _make_provider("local-backup", "backup response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="p1", failure_threshold=1)),
                ProviderEntry(provider=p2, breaker=CircuitBreaker(name="p2", failure_threshold=1)),
                ProviderEntry(provider=p3, breaker=CircuitBreaker(name="p3")),
            ]
        )

        result = await chain.generate("hello")
        assert result.content == "backup response"
        assert result.provider_name == "local-backup"
        assert result.fallback_used is True


# ===========================================================================
# ProviderChain — cache fallback
# ===========================================================================


class TestProviderChainCacheFallback:
    @pytest.mark.asyncio
    async def test_cache_fallback_when_all_providers_down(self):
        """All providers fail -> try cache."""
        p1 = _make_failing_provider("azure")
        p2 = _make_failing_provider("ollama")

        mock_cache = AsyncMock(return_value="cached answer")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="p1", failure_threshold=1)),
                ProviderEntry(provider=p2, breaker=CircuitBreaker(name="p2", failure_threshold=1)),
            ],
            cache_lookup=mock_cache,
        )

        result = await chain.generate("hello")
        assert result.content == "cached answer"
        assert result.cache_used is True
        assert result.fallback_used is True
        assert result.disclaimer is not None
        assert "cache" in result.disclaimer.lower() or "unavailable" in result.disclaimer.lower()

    @pytest.mark.asyncio
    async def test_all_fail_no_cache_raises_all_providers_down(self):
        """All providers fail + no cache -> raise AllProvidersDownError."""
        p1 = _make_failing_provider("azure")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="p1", failure_threshold=1)),
            ]
        )

        with pytest.raises(AllProvidersDownError):
            await chain.generate("hello")

    @pytest.mark.asyncio
    async def test_cache_miss_raises_all_providers_down(self):
        """All providers fail + cache miss -> AllProvidersDownError."""
        p1 = _make_failing_provider("azure")

        mock_cache = AsyncMock(return_value=None)  # cache miss

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="p1", failure_threshold=1)),
            ],
            cache_lookup=mock_cache,
        )

        with pytest.raises(AllProvidersDownError):
            await chain.generate("hello")


# ===========================================================================
# ProviderChain — retry integration
# ===========================================================================


class TestProviderChainRetry:
    @pytest.mark.asyncio
    async def test_retry_before_fallback(self):
        """Provider with retry should retry before falling back."""
        call_count = 0

        async def flaky_generate(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError("timeout")
            return LLMResponse(
                content="recovered",
                model="azure",
                input_tokens=10,
                output_tokens=20,
                latency_ms=100.0,
            )

        primary = MagicMock()
        primary.model_name = "azure"
        primary.generate = flaky_generate

        fallback = _make_provider("ollama", "fallback")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=5),
                    retry=RetryPolicy(max_retries=3, base_delay=0.01, jitter=False),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        result = await chain.generate("hello")
        assert result.content == "recovered"
        assert result.provider_name == "azure"
        assert call_count == 3


# ===========================================================================
# ProviderChain — structured generation
# ===========================================================================


class TestProviderChainStructured:
    @pytest.mark.asyncio
    async def test_generate_structured_uses_first_provider(self):
        primary = _make_provider("azure-gpt5")
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
            ]
        )

        result = await chain.generate_structured("give me JSON")
        assert result.content == '{"key": "value"}'
        assert result.provider_name == "azure-gpt5"

    @pytest.mark.asyncio
    async def test_generate_structured_falls_back(self):
        primary = _make_failing_provider("azure")
        fallback = _make_provider("ollama", '{"result": true}')
        fallback.generate_structured = AsyncMock(
            return_value=LLMResponse(
                content='{"result": true}',
                model="ollama",
                input_tokens=10,
                output_tokens=20,
                latency_ms=200.0,
            )
        )

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ]
        )

        result = await chain.generate_structured("give me JSON")
        assert result.provider_name == "ollama"
        assert result.fallback_used is True


# ===========================================================================
# ProviderChain — provider states
# ===========================================================================


class TestProviderChainStates:
    @pytest.mark.asyncio
    async def test_provider_states_snapshot(self):
        """Can get current state of all providers."""
        p1 = _make_provider("azure")
        p2 = _make_provider("ollama")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="azure")),
                ProviderEntry(provider=p2, breaker=CircuitBreaker(name="ollama")),
            ]
        )

        states = chain.provider_states()
        assert len(states) == 2
        assert states[0]["name"] == "azure"
        assert states[0]["state"] == "CLOSED"
        assert states[1]["name"] == "ollama"

    @pytest.mark.asyncio
    async def test_stats_tracks_routing(self):
        """Stats should track which providers served requests."""
        p1 = _make_provider("azure", "primary")
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=p1, breaker=CircuitBreaker(name="azure")),
            ]
        )

        await chain.generate("hello")
        await chain.generate("world")

        stats = chain.stats()
        assert stats["total_requests"] == 2
        assert stats["by_provider"]["azure"] == 2
        assert stats["fallback_count"] == 0
        assert stats["cache_fallback_count"] == 0
