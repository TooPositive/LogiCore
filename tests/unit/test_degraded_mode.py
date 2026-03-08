"""Tests for degraded mode governance.

When circuit breaker is OPEN (primary down, using fallback):
- is_degraded flag in response metadata
- Logging of degraded-mode events

RED phase: all tests written before implementation.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderEntry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(name: str, content: str = "response") -> MagicMock:
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(
            content=content,
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    return provider


def _make_failing_provider(name: str) -> MagicMock:
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(side_effect=Exception(f"{name} down"))
    return provider


# ===========================================================================
# Degraded mode flag
# ===========================================================================


class TestDegradedModeFlag:
    @pytest.mark.asyncio
    async def test_primary_response_not_degraded(self):
        primary = _make_provider("azure", "primary response")
        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
            ]
        )
        result = await chain.generate("hello")
        assert result.is_degraded is False
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_fallback_response_is_degraded(self):
        primary = _make_failing_provider("azure")
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
        assert result.is_degraded is True
        assert result.fallback_used is True
        assert result.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_cache_response_is_degraded(self):
        primary = _make_failing_provider("azure")
        mock_cache = AsyncMock(return_value="cached answer")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=mock_cache,
        )
        result = await chain.generate("hello")
        assert result.is_degraded is True
        assert result.cache_used is True


# ===========================================================================
# Degraded mode logging
# ===========================================================================


class TestDegradedModeLogging:
    @pytest.mark.asyncio
    async def test_logs_degraded_event_on_fallback(self, caplog):
        """When falling back, should log a warning with provider names."""
        primary = _make_failing_provider("azure")
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

        with caplog.at_level(logging.WARNING):
            await chain.generate("hello")

        # Should have logged a warning about the failed provider
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("azure" in msg.lower() for msg in warning_messages)

    @pytest.mark.asyncio
    async def test_logs_cache_fallback_event(self, caplog):
        """When falling to cache, should log it."""
        primary = _make_failing_provider("azure")
        mock_cache = AsyncMock(return_value="cached answer")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=mock_cache,
        )

        with caplog.at_level(logging.WARNING):
            await chain.generate("hello")

        # The chain already logs warnings for failed providers
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_messages) >= 1

    @pytest.mark.asyncio
    async def test_no_warning_on_primary_success(self, caplog):
        """Successful primary call should not log warnings."""
        primary = _make_provider("azure", "primary response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=CircuitBreaker(name="azure")),
            ]
        )

        with caplog.at_level(logging.WARNING):
            await chain.generate("hello")

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warning_messages) == 0
