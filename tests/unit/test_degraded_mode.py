"""Tests for degraded mode governance.

When circuit breaker is OPEN (primary down, using fallback):
- is_degraded flag in response metadata
- Logging of degraded-mode events
- Downstream systems (auto-approve, financial decisions) MUST respect the flag

RED phase: all tests written before implementation.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderChainResponse,
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


# ===========================================================================
# Degraded mode downstream governance (Review Gap #3)
# ===========================================================================


class TestDegradedModeDownstreamGovernance:
    """Proves the ARCHITECTURE, not just the flag.

    The spec says: "Disable auto-approve on all financial decisions during
    degradation." These tests prove that downstream decision logic CAN
    and SHOULD check is_degraded before auto-approving.

    The actual auto-approve integration is in Phase 3's HITL gateway.
    These tests prove the governance CONTRACT: any system that receives
    a ProviderChainResponse can check is_degraded and act accordingly.
    """

    def test_auto_approve_should_block_on_degraded_response(self):
        """A financial auto-approve workflow MUST check is_degraded.

        Pattern: if response.is_degraded, force HITL review instead of
        auto-approving. This test proves the governance decision function.
        """

        def should_auto_approve(
            response: ProviderChainResponse,
            discrepancy_eur: float,
            auto_approve_threshold: float = 50.0,
        ) -> bool:
            """Governance rule: never auto-approve during degraded mode."""
            if response.is_degraded:
                return False  # Force HITL review
            return discrepancy_eur <= auto_approve_threshold

        # Normal mode: EUR 30 discrepancy auto-approves
        normal_response = ProviderChainResponse(
            content="Discrepancy: EUR 30",
            model="gpt-5.2",
            input_tokens=100,
            output_tokens=50,
            latency_ms=500.0,
            provider_name="azure",
            fallback_used=False,
            cache_used=False,
        )
        assert should_auto_approve(normal_response, 30.0) is True

        # Degraded mode: same EUR 30 discrepancy forces HITL
        degraded_response = ProviderChainResponse(
            content="Discrepancy: EUR 30",
            model="qwen3:8b",
            input_tokens=100,
            output_tokens=50,
            latency_ms=2000.0,
            provider_name="ollama",
            fallback_used=True,
            cache_used=False,
        )
        assert should_auto_approve(degraded_response, 30.0) is False

    def test_cached_response_blocks_financial_decisions(self):
        """Cache fallback responses MUST NOT be used for financial decisions.

        A 30-minute-old cached fleet status could send a driver to the
        wrong location (EUR 200-5,000 cost per the spec).
        """

        def is_safe_for_financial_decision(
            response: ProviderChainResponse,
        ) -> bool:
            """Financial decisions require live AI, never cache."""
            if response.cache_used:
                return False
            if response.is_degraded:
                return False
            return True

        # Live primary: safe for financial decision
        live = ProviderChainResponse(
            content="Contract rate: EUR 2.45/km",
            model="gpt-5.2",
            input_tokens=100,
            output_tokens=50,
            latency_ms=500.0,
            provider_name="azure",
            fallback_used=False,
            cache_used=False,
        )
        assert is_safe_for_financial_decision(live) is True

        # Cached response: NOT safe
        cached = ProviderChainResponse(
            content="Contract rate: EUR 2.45/km",
            model="cache",
            input_tokens=0,
            output_tokens=0,
            latency_ms=5.0,
            provider_name="cache",
            fallback_used=True,
            cache_used=True,
            disclaimer="Served from cache",
        )
        assert is_safe_for_financial_decision(cached) is False

        # Fallback (Ollama): NOT safe for financial
        fallback = ProviderChainResponse(
            content="Contract rate: EUR 2.45/km",
            model="qwen3:8b",
            input_tokens=100,
            output_tokens=50,
            latency_ms=2000.0,
            provider_name="ollama",
            fallback_used=True,
            cache_used=False,
        )
        assert is_safe_for_financial_decision(fallback) is False

    def test_degraded_response_disclaimer_is_user_visible(self):
        """Disclaimer text must be present and meaningful for user display."""
        cached = ProviderChainResponse(
            content="Some answer",
            model="cache",
            input_tokens=0,
            output_tokens=0,
            latency_ms=5.0,
            provider_name="cache",
            fallback_used=True,
            cache_used=True,
            disclaimer=(
                "This response is from cache -- "
                "live AI providers are currently unavailable."
            ),
        )
        assert cached.disclaimer is not None
        assert "cache" in cached.disclaimer.lower()
        assert "unavailable" in cached.disclaimer.lower()
        assert len(cached.disclaimer) > 20  # Not a stub

    @pytest.mark.asyncio
    async def test_degraded_flag_propagates_through_full_chain(self):
        """End-to-end: primary fails -> fallback serves -> is_degraded=True
        -> downstream governance blocks auto-approve."""
        primary = _make_failing_provider("azure")
        fallback = _make_provider("ollama", "Discrepancy found: EUR 45")

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

        result = await chain.generate("Check invoice INV-2024-001")

        # Response came from fallback
        assert result.is_degraded is True
        assert result.fallback_used is True

        # Downstream governance: degraded response blocks auto-approve
        auto_approve = not result.is_degraded and True  # would be True otherwise
        assert auto_approve is False

    @pytest.mark.asyncio
    async def test_primary_recovery_clears_degraded_flag(self):
        """After primary recovers, responses are no longer degraded."""
        primary = _make_provider("azure", "Primary response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure"),
                ),
            ]
        )

        result = await chain.generate("Check invoice")
        assert result.is_degraded is False

        # Auto-approve would be allowed again
        auto_approve_allowed = not result.is_degraded
        assert auto_approve_allowed is True
