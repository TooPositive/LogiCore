"""Tests for ResilientLLM — combines ModelRouter + ProviderChain.

The ResilientLLM orchestrator:
1. Classifies query complexity via existing ModelRouter
2. Routes to the appropriate ProviderChain tier
3. Returns ProviderChainResponse with full metadata

RED phase: all tests written before implementation.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.domain.telemetry import ModelRoute, QueryComplexity
from apps.api.src.core.infrastructure.llm.circuit_breaker import CircuitBreaker
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderChainResponse,
    ProviderEntry,
)
from apps.api.src.core.infrastructure.llm.resilient_llm import ResilientLLM

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
    provider.generate_structured = AsyncMock(
        return_value=LLMResponse(
            content='{"result": true}',
            model=name,
            input_tokens=10,
            output_tokens=20,
            latency_ms=100.0,
        )
    )
    return provider


def _make_chain(provider_name: str = "azure", content: str = "response") -> ProviderChain:
    """Build a simple ProviderChain with one provider."""
    provider = _make_provider(provider_name, content)
    return ProviderChain(
        providers=[
            ProviderEntry(provider=provider, breaker=CircuitBreaker(name=provider_name)),
        ]
    )


def _make_router(complexity: QueryComplexity = QueryComplexity.SIMPLE) -> MagicMock:
    """Mock ModelRouter that returns a fixed classification."""
    router = MagicMock()
    router.classify = AsyncMock(
        return_value=ModelRoute(
            query="test query",
            complexity=complexity,
            selected_model="gpt-5-nano" if complexity == QueryComplexity.SIMPLE else "gpt-5.2",
            confidence=0.95,
            routing_reason=f"test: {complexity.value}",
        )
    )
    return router


# ===========================================================================
# ResilientLLM — basic routing
# ===========================================================================


class TestResilientLLMBasic:
    @pytest.mark.asyncio
    async def test_simple_query_uses_default_chain(self):
        """Simple queries should route through the default chain."""
        router = _make_router(QueryComplexity.SIMPLE)
        chain = _make_chain("nano", "simple answer")

        llm = ResilientLLM(router=router, default_chain=chain)
        result = await llm.generate("What is the status of truck-0892?")
        assert result.content == "simple answer"
        router.classify.assert_called_once()

    @pytest.mark.asyncio
    async def test_complex_query_uses_default_chain(self):
        """Complex queries also route through the chain."""
        router = _make_router(QueryComplexity.COMPLEX)
        chain = _make_chain("gpt5", "complex answer")

        llm = ResilientLLM(router=router, default_chain=chain)
        result = await llm.generate("Analyze CTR-2024-004 against EU regulations")
        assert result.content == "complex answer"

    @pytest.mark.asyncio
    async def test_returns_provider_chain_response(self):
        router = _make_router()
        chain = _make_chain("azure")

        llm = ResilientLLM(router=router, default_chain=chain)
        result = await llm.generate("hello")
        assert isinstance(result, ProviderChainResponse)

    @pytest.mark.asyncio
    async def test_structured_generation(self):
        router = _make_router()
        chain = _make_chain("azure")

        llm = ResilientLLM(router=router, default_chain=chain)
        result = await llm.generate_structured("give me JSON")
        assert isinstance(result, ProviderChainResponse)


# ===========================================================================
# ResilientLLM — tier-specific chains
# ===========================================================================


class TestResilientLLMTierChains:
    @pytest.mark.asyncio
    async def test_tier_specific_chain_used(self):
        """Can configure different chains per complexity tier."""
        router = _make_router(QueryComplexity.COMPLEX)
        default_chain = _make_chain("default-model", "default answer")
        complex_chain = _make_chain("gpt-5.2", "complex tier answer")

        llm = ResilientLLM(
            router=router,
            default_chain=default_chain,
            tier_chains={QueryComplexity.COMPLEX: complex_chain},
        )
        result = await llm.generate("Analyze contract")
        assert result.content == "complex tier answer"

    @pytest.mark.asyncio
    async def test_falls_back_to_default_chain_for_unconfigured_tier(self):
        """If tier has no specific chain, use default."""
        router = _make_router(QueryComplexity.MEDIUM)
        default_chain = _make_chain("default-model", "default answer")
        complex_chain = _make_chain("gpt-5.2", "complex answer")

        llm = ResilientLLM(
            router=router,
            default_chain=default_chain,
            tier_chains={QueryComplexity.COMPLEX: complex_chain},
        )
        result = await llm.generate("Summarize the report")
        assert result.content == "default answer"


# ===========================================================================
# ResilientLLM — routing metadata
# ===========================================================================


class TestResilientLLMMetadata:
    @pytest.mark.asyncio
    async def test_routing_stats_available(self):
        router = _make_router()
        chain = _make_chain("azure")

        llm = ResilientLLM(router=router, default_chain=chain)
        await llm.generate("hello")
        await llm.generate("world")

        stats = llm.stats()
        assert stats["total_routed"] == 2
        assert stats["by_complexity"]["SIMPLE"] == 2

    @pytest.mark.asyncio
    async def test_provider_states_available(self):
        router = _make_router()
        chain = _make_chain("azure")

        llm = ResilientLLM(router=router, default_chain=chain)
        states = llm.provider_states()
        assert isinstance(states, dict)


# ===========================================================================
# ResilientLLM — fallback behavior
# ===========================================================================


class TestResilientLLMFallback:
    @pytest.mark.asyncio
    async def test_fallback_in_chain_still_returns(self):
        """If primary in chain fails, chain falls back internally."""
        router = _make_router()

        primary = MagicMock()
        primary.model_name = "azure"
        primary.generate = AsyncMock(side_effect=Exception("azure down"))

        fallback = _make_provider("ollama", "fallback answer")

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

        llm = ResilientLLM(router=router, default_chain=chain)
        result = await llm.generate("hello")
        assert result.content == "fallback answer"
        assert result.is_degraded is True
