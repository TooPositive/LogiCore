"""Tests for response quality gate in ProviderChain.

The analysis identified 200-OK-garbage as the most expensive silent failure
(EUR 500-5,000/incident). If a provider returns an empty, too-short, or
malformed response, it should count as a failure and trigger fallback.

RED phase: all tests written before implementation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderChainResponse,
    ProviderEntry,
    ResponseQualityGate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_with_response(name: str, content: str) -> MagicMock:
    """Create a mock provider returning a specific content string."""
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
    provider.generate_structured = AsyncMock(
        return_value=LLMResponse(
            content=content,
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    return provider


# ===========================================================================
# ResponseQualityGate tests
# ===========================================================================


class TestResponseQualityGate:
    def test_valid_response_passes(self):
        gate = ResponseQualityGate(min_length=10)
        response = LLMResponse(
            content="This is a valid response with enough characters.",
            model="gpt-5",
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
        assert gate.is_acceptable(response) is True

    def test_empty_response_fails(self):
        gate = ResponseQualityGate(min_length=10)
        response = LLMResponse(
            content="",
            model="gpt-5",
            input_tokens=10,
            output_tokens=0,
            latency_ms=100.0,
        )
        assert gate.is_acceptable(response) is False

    def test_too_short_response_fails(self):
        gate = ResponseQualityGate(min_length=10)
        response = LLMResponse(
            content="short",
            model="gpt-5",
            input_tokens=10,
            output_tokens=5,
            latency_ms=100.0,
        )
        assert gate.is_acceptable(response) is False

    def test_whitespace_only_response_fails(self):
        gate = ResponseQualityGate(min_length=10)
        response = LLMResponse(
            content="     \n\n\t  ",
            model="gpt-5",
            input_tokens=10,
            output_tokens=5,
            latency_ms=100.0,
        )
        assert gate.is_acceptable(response) is False

    def test_configurable_min_length(self):
        gate = ResponseQualityGate(min_length=5)
        response = LLMResponse(
            content="hello",
            model="gpt-5",
            input_tokens=10,
            output_tokens=5,
            latency_ms=100.0,
        )
        assert gate.is_acceptable(response) is True

    def test_default_min_length(self):
        gate = ResponseQualityGate()
        assert gate.min_length == 10


# ===========================================================================
# ProviderChain with quality gate — integration
# ===========================================================================


class TestProviderChainQualityGate:
    @pytest.mark.asyncio
    async def test_empty_response_triggers_fallback(self):
        """Provider returns 200 OK but empty content -> try next provider."""
        primary = _make_provider_with_response("azure", "")
        fallback = _make_provider_with_response("ollama", "valid response content")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=5),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("hello")
        assert result.content == "valid response content"
        assert result.provider_name == "ollama"
        assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_short_response_triggers_fallback(self):
        """Provider returns 200 OK but very short content -> fallback."""
        primary = _make_provider_with_response("azure", "ok")
        fallback = _make_provider_with_response("ollama", "This is a proper response")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure", failure_threshold=5),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("hello")
        assert result.provider_name == "ollama"

    @pytest.mark.asyncio
    async def test_valid_response_passes_gate(self):
        """Valid response passes the quality gate, no fallback."""
        primary = _make_provider_with_response(
            "azure", "This is a perfectly valid and long response."
        )

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("hello")
        assert result.provider_name == "azure"
        assert result.fallback_used is False

    @pytest.mark.asyncio
    async def test_no_quality_gate_allows_anything(self):
        """Without quality gate, any response is accepted."""
        primary = _make_provider_with_response("azure", "ok")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=primary,
                    breaker=CircuitBreaker(name="azure"),
                ),
            ],
        )

        result = await chain.generate("hello")
        assert result.content == "ok"
        assert result.provider_name == "azure"

    @pytest.mark.asyncio
    async def test_quality_gate_failure_counts_as_provider_failure(self):
        """Quality gate failure should count in circuit breaker metrics."""
        primary = _make_provider_with_response("azure", "")
        fallback = _make_provider_with_response("ollama", "valid response content")

        breaker = CircuitBreaker(name="azure", failure_threshold=5)

        chain = ProviderChain(
            providers=[
                ProviderEntry(provider=primary, breaker=breaker),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="ollama"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        await chain.generate("hello")
        # The quality gate failure should have registered
        assert breaker.metrics.total_failures >= 1
