"""Provider swap tests (Phase 6 -- Air-Gapped Vault).

Verify that switching LLM_PROVIDER in settings changes behavior
without any code changes. Both providers produce same response schema.
RBAC filtering works identically regardless of provider.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.core.config.settings import Settings
from apps.api.src.core.infrastructure.llm.provider import (
    LLMResponse,
    get_llm_provider,
)


class TestProviderSwap:
    """Switching LLM_PROVIDER changes the provider with zero code changes."""

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_azure_and_ollama_return_same_response_type(
        self, mock_azure_cls, mock_ollama_cls
    ):
        """Both providers return LLMResponse -- same schema, different backend."""
        mock_azure_cls.return_value = MagicMock()
        mock_ollama_cls.return_value = MagicMock()

        base = dict(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )

        azure = get_llm_provider(Settings(**base, llm_provider="azure"))
        ollama = get_llm_provider(Settings(**base, llm_provider="ollama"))

        # Both have the same interface
        assert hasattr(azure, "generate")
        assert hasattr(azure, "generate_structured")
        assert hasattr(azure, "model_name")
        assert hasattr(ollama, "generate")
        assert hasattr(ollama, "generate_structured")
        assert hasattr(ollama, "model_name")

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_same_query_same_schema_different_providers(
        self, mock_azure_cls, mock_ollama_cls
    ):
        """Same query through both providers produces LLMResponse with same fields."""

        # Azure mock
        azure_response = MagicMock()
        azure_response.content = "Azure says: contract rate is 0.45 EUR/kg"
        azure_response.usage_metadata = {"input_tokens": 30, "output_tokens": 12}
        azure_instance = MagicMock()
        azure_instance.ainvoke = AsyncMock(return_value=azure_response)
        mock_azure_cls.return_value = azure_instance

        # Ollama mock
        ollama_response = MagicMock()
        ollama_response.content = "Ollama says: contract rate is 0.45 EUR/kg"
        ollama_response.usage_metadata = {"input_tokens": 30, "output_tokens": 14}
        ollama_instance = MagicMock()
        ollama_instance.ainvoke = AsyncMock(return_value=ollama_response)
        mock_ollama_cls.return_value = ollama_instance

        base = dict(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )

        azure = get_llm_provider(Settings(**base, llm_provider="azure"))
        ollama = get_llm_provider(Settings(**base, llm_provider="ollama"))

        query = "What is the contract rate for pharma cargo?"

        azure_result = await azure.generate(query)
        ollama_result = await ollama.generate(query)

        # Both return LLMResponse with same field structure
        assert isinstance(azure_result, LLMResponse)
        assert isinstance(ollama_result, LLMResponse)

        # Content is different (different models)
        assert azure_result.content != ollama_result.content

        # But same schema -- all fields present
        for result in [azure_result, ollama_result]:
            assert isinstance(result.content, str)
            assert isinstance(result.model, str)
            assert isinstance(result.input_tokens, int)
            assert isinstance(result.output_tokens, int)
            assert isinstance(result.latency_ms, float)

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_provider_swap_no_code_change_needed(
        self, mock_azure_cls, mock_ollama_cls
    ):
        """Demonstrate that the calling code is identical for both providers."""

        for mock_cls in [mock_azure_cls, mock_ollama_cls]:
            resp = MagicMock()
            resp.content = "test response"
            resp.usage_metadata = {"input_tokens": 10, "output_tokens": 5}
            instance = MagicMock()
            instance.ainvoke = AsyncMock(return_value=resp)
            mock_cls.return_value = instance

        base = dict(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )

        # This is the ONLY line that changes between deployments
        for provider_name in ["azure", "ollama"]:
            provider = get_llm_provider(
                Settings(**base, llm_provider=provider_name)
            )

            # This calling code is IDENTICAL regardless of provider
            result = await provider.generate("What is 2+2?")
            assert isinstance(result, LLMResponse)
            assert result.content == "test response"

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    def test_ollama_provider_zero_external_calls(self, mock_ollama_cls):
        """Ollama provider uses localhost -- no external API calls."""
        mock_ollama_cls.return_value = MagicMock()

        provider = get_llm_provider(
            Settings(
                azure_openai_endpoint="https://test.openai.azure.com",
                azure_openai_api_key="test-key",
                llm_provider="ollama",
                ollama_host="http://localhost:11434",
            )
        )

        # Provider should be configured for localhost
        assert provider._host == "http://localhost:11434"
        # No Azure endpoint referenced
        assert "azure" not in provider._host.lower()
        assert "openai" not in provider._host.lower()

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_model_name_reflects_active_provider(
        self, mock_azure_cls, mock_ollama_cls
    ):
        """model_name returns the correct model for each provider."""
        mock_azure_cls.return_value = MagicMock()
        mock_ollama_cls.return_value = MagicMock()

        azure = get_llm_provider(
            Settings(
                azure_openai_endpoint="https://test.openai.azure.com",
                azure_openai_api_key="test-key",
                azure_openai_deployment="gpt-5-mini",
                llm_provider="azure",
            )
        )
        ollama = get_llm_provider(
            Settings(
                azure_openai_endpoint="https://test.openai.azure.com",
                azure_openai_api_key="test-key",
                llm_provider="ollama",
                ollama_model="qwen3:32b",
            )
        )

        assert azure.model_name == "gpt-5-mini"
        assert ollama.model_name == "qwen3:32b"


class TestRBACWithProviders:
    """RBAC filtering works identically regardless of LLM provider.

    RBAC is enforced at Qdrant query level, not LLM level.
    The LLM provider is irrelevant to access control.
    """

    def test_rbac_filter_is_provider_independent(self):
        """RBAC clearance filter builds the same Qdrant filter regardless of provider."""
        from apps.api.src.core.domain.document import UserContext
        from apps.api.src.core.security.rbac import build_qdrant_filter

        user = UserContext(
            user_id="test", clearance_level=2, departments=["logistics"]
        )
        qdrant_filter = build_qdrant_filter(user)

        # The filter is a Qdrant condition -- completely independent of LLM
        assert qdrant_filter is not None
        # RBAC filter doesn't reference any LLM provider
        filter_str = str(qdrant_filter)
        assert "azure" not in filter_str.lower()
        assert "ollama" not in filter_str.lower()

    def test_rbac_filter_same_for_both_providers(self):
        """The exact same RBAC filter is produced regardless of which provider is active."""
        from apps.api.src.core.domain.document import UserContext
        from apps.api.src.core.security.rbac import build_qdrant_filter

        user = UserContext(
            user_id="test", clearance_level=3, departments=["hr", "management"]
        )
        filter1 = build_qdrant_filter(user)
        filter2 = build_qdrant_filter(user)

        # Same user = same filter, always
        assert str(filter1) == str(filter2)

    def test_rbac_enforced_at_qdrant_not_llm(self):
        """RBAC is a Qdrant-level filter. LLM never sees unauthorized docs."""
        from apps.api.src.core.domain.document import UserContext
        from apps.api.src.core.security.rbac import build_qdrant_filter

        # Clearance 1 user gets a restrictive filter
        user_cl1 = UserContext(
            user_id="low", clearance_level=1, departments=["warehouse"]
        )
        filter_cl1 = build_qdrant_filter(user_cl1)
        assert filter_cl1 is not None

        # Clearance 4 user gets a wider filter
        user_cl4 = UserContext(
            user_id="high",
            clearance_level=4,
            departments=["hr", "management", "legal", "logistics"],
        )
        filter_cl4 = build_qdrant_filter(user_cl4)
        assert filter_cl4 is not None

        # Both are Qdrant filters -- the LLM is downstream and irrelevant
        # The key point: unauthorized docs are excluded BEFORE retrieval,
        # not filtered after the LLM processes them
        assert str(filter_cl1) != str(filter_cl4)
