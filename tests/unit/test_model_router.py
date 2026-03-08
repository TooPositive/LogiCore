"""Unit tests for Phase 4 model router.

Tests: LLM-based classification, keyword overrides, confidence escalation,
routing decisions, cost impact.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.domain.telemetry import QueryComplexity


class TestKeywordOverride:
    """Financial keywords force COMPLEX routing regardless of LLM classification."""

    FINANCIAL_KEYWORDS = [
        "contract", "invoice", "rate", "penalty", "amendment",
        "surcharge", "annex", "audit", "compliance", "discrepancy",
    ]

    @pytest.mark.parametrize("keyword", FINANCIAL_KEYWORDS)
    def test_financial_keyword_forces_complex(self, keyword):
        from apps.api.src.core.infrastructure.llm.router import (
            OVERRIDE_KEYWORDS,
            check_keyword_override,
        )

        query = f"What is the {keyword} for PharmaCorp?"
        result = check_keyword_override(query)
        assert result is True
        assert keyword.lower() in [k.lower() for k in OVERRIDE_KEYWORDS]

    def test_keyword_check_case_insensitive(self):
        from apps.api.src.core.infrastructure.llm.router import check_keyword_override

        assert check_keyword_override("What is the CONTRACT rate?") is True
        assert check_keyword_override("INVOICE details") is True

    def test_no_keyword_returns_false(self):
        from apps.api.src.core.infrastructure.llm.router import check_keyword_override

        assert check_keyword_override("What is the weather today?") is False
        assert check_keyword_override("Hello world") is False

    def test_keyword_override_list_is_configurable(self):
        """Domain-agnostic: custom keywords can be passed."""
        from apps.api.src.core.infrastructure.llm.router import check_keyword_override

        custom = ["medical", "prescription", "diagnosis"]
        assert check_keyword_override("patient diagnosis", custom_keywords=custom) is True
        assert check_keyword_override("hello world", custom_keywords=custom) is False


class TestModelRouterClassification:
    """LLM-based query classification with GPT-5 nano."""

    @pytest.mark.asyncio
    async def test_classify_simple_query(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        result = await router.classify("What is shipment status?")
        assert result.complexity == QueryComplexity.SIMPLE
        assert result.confidence >= 0.0

    @pytest.mark.asyncio
    async def test_classify_medium_query(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="MEDIUM")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        result = await router.classify("Summarize the delivery report for March")
        assert result.complexity == QueryComplexity.MEDIUM

    @pytest.mark.asyncio
    async def test_classify_complex_query(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="COMPLEX")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        result = await router.classify(
            "Compare base rate vs Q4 amendment for PharmaCorp"
        )
        assert result.complexity == QueryComplexity.COMPLEX

    @pytest.mark.asyncio
    async def test_keyword_override_bypasses_llm(self):
        """When keyword override triggers, LLM is NOT called."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        result = await router.classify("What is the penalty rate in the contract?")
        assert result.complexity == QueryComplexity.COMPLEX
        assert result.keyword_override is True
        # LLM should NOT have been called
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_confidence_escalates_one_tier(self):
        """Confidence < 0.7 escalates SIMPLE -> MEDIUM."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        # Return SIMPLE with low confidence indicator
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.5")
        )
        router = ModelRouter(
            classifier_llm=mock_llm,
            confidence_threshold=0.7,
        )
        result = await router.classify("What does clause 7 mean?")
        # Should be escalated from SIMPLE to MEDIUM
        assert result.escalated is True
        assert result.complexity in (QueryComplexity.MEDIUM, QueryComplexity.COMPLEX)

    @pytest.mark.asyncio
    async def test_medium_low_confidence_escalates_to_complex(self):
        """Confidence < 0.7 escalates MEDIUM -> COMPLEX (with keyword override)."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="MEDIUM 0.4")
        )
        router = ModelRouter(
            classifier_llm=mock_llm,
            confidence_threshold=0.7,
        )
        # "amendment" is a keyword, so this tests keyword override path
        route = await router.classify("How does the amendment affect pricing?")
        assert route.complexity == QueryComplexity.COMPLEX
        assert route.keyword_override is True

    @pytest.mark.asyncio
    async def test_medium_escalation_without_keyword(self):
        """Non-keyword query: MEDIUM + low confidence -> COMPLEX."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="MEDIUM 0.5")
        )
        router = ModelRouter(
            classifier_llm=mock_llm,
            confidence_threshold=0.7,
        )
        result = await router.classify("Explain the implications of this clause")
        assert result.escalated is True
        assert result.complexity == QueryComplexity.COMPLEX


class TestModelSelection:
    """Router selects the correct model based on complexity."""

    @pytest.mark.asyncio
    async def test_simple_routes_to_nano(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.95")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("What is shipment status?")
        assert route.selected_model == "gpt-5-nano"

    @pytest.mark.asyncio
    async def test_medium_routes_to_mini(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="MEDIUM 0.85")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("Summarize the weekly delivery report")
        assert route.selected_model == "gpt-5-mini"

    @pytest.mark.asyncio
    async def test_complex_routes_to_gpt52(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="COMPLEX 0.9")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("Analyze the multi-hop implications")
        assert route.selected_model == "gpt-5.2"

    @pytest.mark.asyncio
    async def test_keyword_override_routes_to_gpt52(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("What is the invoice discrepancy?")
        assert route.selected_model == "gpt-5.2"
        assert route.keyword_override is True

    @pytest.mark.asyncio
    async def test_model_map_is_configurable(self):
        """Domain-agnostic: model selection map can be customized."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        custom_models = {
            QueryComplexity.SIMPLE: "local-llama-7b",
            QueryComplexity.MEDIUM: "local-llama-13b",
            QueryComplexity.COMPLEX: "local-llama-70b",
        }
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.9")
        )
        router = ModelRouter(
            classifier_llm=mock_llm,
            model_map=custom_models,
        )
        route = await router.route("Hello world")
        assert route.selected_model == "local-llama-7b"

    @pytest.mark.asyncio
    async def test_route_includes_routing_reason(self):
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="SIMPLE 0.92")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("What is the shipment ETA?")
        assert route.routing_reason != ""
        assert len(route.routing_reason) > 0

    @pytest.mark.asyncio
    async def test_llm_returns_garbage_defaults_to_complex(self):
        """If LLM returns unparseable response, default to COMPLEX (safe)."""
        from apps.api.src.core.infrastructure.llm.router import ModelRouter

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="I don't understand the question")
        )
        router = ModelRouter(classifier_llm=mock_llm)
        route = await router.route("Some weird query")
        assert route.selected_model == "gpt-5.2"
        assert route.complexity == QueryComplexity.COMPLEX
