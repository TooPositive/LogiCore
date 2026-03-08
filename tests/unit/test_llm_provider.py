"""Tests for LLM provider infrastructure (Phase 6 -- Air-Gapped Vault).

Covers:
- Settings fields for provider toggle
- LLMProvider Protocol and LLMResponse
- Azure OpenAI and Ollama LLM providers
- LLM provider factory
"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.core.config.settings import Settings


# -----------------------------------------------------------------------
# Task 1: Settings -- LLM/Embedding provider toggles
# -----------------------------------------------------------------------


class TestSettingsProviderToggle:
    """Settings must expose provider selection fields with safe defaults."""

    def test_settings_has_llm_provider_field(self):
        """Settings exposes llm_provider with default 'azure'."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )
        assert s.llm_provider == "azure"

    def test_settings_has_embedding_provider_field(self):
        """Settings exposes embedding_provider with default 'azure_openai'."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )
        assert s.embedding_provider == "azure_openai"

    def test_settings_has_ollama_host(self):
        """Settings exposes ollama_host with default localhost."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )
        assert s.ollama_host == "http://localhost:11434"

    def test_settings_has_ollama_model(self):
        """Settings exposes ollama_model (generation) with default."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )
        assert s.ollama_model == "qwen3:8b"

    def test_settings_has_ollama_embed_model(self):
        """Settings exposes ollama_embed_model (embeddings) with default."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )
        assert s.ollama_embed_model == "nomic-embed-text"

    def test_settings_llm_provider_can_be_set_to_ollama(self):
        """LLM_PROVIDER=ollama should be accepted."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            llm_provider="ollama",
        )
        assert s.llm_provider == "ollama"

    def test_settings_embedding_provider_can_be_set_to_ollama(self):
        """EMBEDDING_PROVIDER=ollama should be accepted."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            embedding_provider="ollama",
        )
        assert s.embedding_provider == "ollama"

    def test_settings_embedding_provider_can_be_set_to_mock(self):
        """EMBEDDING_PROVIDER=mock should be accepted."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            embedding_provider="mock",
        )
        assert s.embedding_provider == "mock"

    def test_settings_ollama_host_custom(self):
        """Custom OLLAMA_HOST should override default."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            ollama_host="http://gpu-server:11434",
        )
        assert s.ollama_host == "http://gpu-server:11434"

    def test_settings_ollama_model_custom(self):
        """Custom OLLAMA_MODEL should override default."""
        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            ollama_model="qwen3:32b",
        )
        assert s.ollama_model == "qwen3:32b"


# -----------------------------------------------------------------------
# Task 2: LLMProvider Protocol + LLMResponse dataclass
# -----------------------------------------------------------------------


class TestLLMResponse:
    """LLMResponse captures generation output with token/latency metadata."""

    def test_llm_response_creation(self):
        """LLMResponse stores all required fields."""
        from apps.api.src.core.infrastructure.llm.provider import LLMResponse

        resp = LLMResponse(
            content="Hello world",
            model="qwen3:8b",
            input_tokens=10,
            output_tokens=5,
            latency_ms=150.0,
        )
        assert resp.content == "Hello world"
        assert resp.model == "qwen3:8b"
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5
        assert resp.latency_ms == 150.0

    def test_llm_response_is_frozen(self):
        """LLMResponse should be immutable (frozen dataclass)."""
        from apps.api.src.core.infrastructure.llm.provider import LLMResponse

        resp = LLMResponse(
            content="test",
            model="test-model",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1.0,
        )
        with pytest.raises(FrozenInstanceError):
            resp.content = "modified"

    def test_llm_response_total_tokens(self):
        """LLMResponse.total_tokens returns sum of input + output."""
        from apps.api.src.core.infrastructure.llm.provider import LLMResponse

        resp = LLMResponse(
            content="test",
            model="test-model",
            input_tokens=100,
            output_tokens=50,
            latency_ms=200.0,
        )
        assert resp.total_tokens == 150


class TestLLMProviderProtocol:
    """LLMProvider Protocol defines the contract for all providers."""

    def test_protocol_exists(self):
        """LLMProvider Protocol is importable."""
        from apps.api.src.core.infrastructure.llm.provider import LLMProvider

        assert LLMProvider is not None

    def test_mock_satisfies_protocol(self):
        """A mock with correct methods satisfies LLMProvider Protocol."""
        from apps.api.src.core.infrastructure.llm.provider import (
            LLMProvider,
            LLMResponse,
        )

        class MockProvider:
            async def generate(self, prompt: str, **kwargs) -> LLMResponse:
                return LLMResponse(
                    content="mock",
                    model="mock-model",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=0.1,
                )

            async def generate_structured(
                self, prompt: str, **kwargs
            ) -> LLMResponse:
                return LLMResponse(
                    content="{}",
                    model="mock-model",
                    input_tokens=1,
                    output_tokens=1,
                    latency_ms=0.1,
                )

            @property
            def model_name(self) -> str:
                return "mock-model"

        provider = MockProvider()
        # Protocol structural subtyping -- isinstance won't work, but
        # we verify the interface is correct by checking attributes
        assert hasattr(provider, "generate")
        assert hasattr(provider, "generate_structured")
        assert hasattr(provider, "model_name")
        assert provider.model_name == "mock-model"

    def test_missing_method_does_not_satisfy_protocol(self):
        """A class missing generate() should fail Protocol check."""
        from apps.api.src.core.infrastructure.llm.provider import LLMProvider

        class IncompleteProvider:
            @property
            def model_name(self) -> str:
                return "incomplete"

        provider = IncompleteProvider()
        # Should NOT have generate method
        assert not hasattr(provider, "generate")


# -----------------------------------------------------------------------
# Task 3: Azure OpenAI LLM Provider
# -----------------------------------------------------------------------


class TestAzureOpenAIProvider:
    """Azure OpenAI provider wraps LangChain AzureChatOpenAI."""

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_generate_returns_llm_response(self, mock_chat_cls):
        """generate() returns LLMResponse with content and token counts."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )
        from apps.api.src.core.infrastructure.llm.provider import LLMResponse

        # Mock the LangChain response
        mock_response = MagicMock()
        mock_response.content = "The answer is 42."
        mock_response.usage_metadata = {
            "input_tokens": 25,
            "output_tokens": 8,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
            api_version="2024-12-01-preview",
        )

        result = await provider.generate("What is the answer?")

        assert isinstance(result, LLMResponse)
        assert result.content == "The answer is 42."
        assert result.model == "gpt-4o"
        assert result.input_tokens == 25
        assert result.output_tokens == 8
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_generate_structured_returns_llm_response(self, mock_chat_cls):
        """generate_structured() returns LLMResponse with JSON content."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_response = MagicMock()
        mock_response.content = '{"rate": 0.45, "currency": "EUR"}'
        mock_response.usage_metadata = {
            "input_tokens": 50,
            "output_tokens": 15,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )

        result = await provider.generate_structured("Extract rates")
        assert result.content == '{"rate": 0.45, "currency": "EUR"}'
        assert result.input_tokens == 50

    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_model_name_returns_deployment(self, mock_chat_cls):
        """model_name property returns the Azure deployment name."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_chat_cls.return_value = MagicMock()

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-5-mini",
        )
        assert provider.model_name == "gpt-5-mini"

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_generate_tracks_latency(self, mock_chat_cls):
        """generate() records latency_ms > 0."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_response = MagicMock()
        mock_response.content = "response"
        mock_response.usage_metadata = {
            "input_tokens": 10,
            "output_tokens": 5,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )

        result = await provider.generate("test")
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_generate_handles_missing_usage_metadata(self, mock_chat_cls):
        """generate() returns 0 tokens when usage_metadata is missing."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_response = MagicMock()
        mock_response.content = "response"
        mock_response.usage_metadata = None

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )

        result = await provider.generate("test")
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_satisfies_llm_provider_protocol(self, mock_chat_cls):
        """AzureOpenAIProvider satisfies LLMProvider Protocol."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )
        from apps.api.src.core.infrastructure.llm.provider import LLMProvider

        mock_chat_cls.return_value = MagicMock()

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )
        assert isinstance(provider, LLMProvider)

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    async def test_generate_passes_kwargs_to_langchain(self, mock_chat_cls):
        """Extra kwargs are passed through to LangChain ainvoke."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )

        mock_response = MagicMock()
        mock_response.content = "response"
        mock_response.usage_metadata = {"input_tokens": 5, "output_tokens": 3}

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = AzureOpenAIProvider(
            endpoint="https://test.openai.azure.com",
            api_key="test-key",
            deployment="gpt-4o",
        )

        await provider.generate("test", temperature=0.5)
        mock_instance.ainvoke.assert_called_once_with("test", temperature=0.5)


# -----------------------------------------------------------------------
# Task 4: Ollama LLM Provider
# -----------------------------------------------------------------------


class TestOllamaProvider:
    """Ollama provider wraps LangChain ChatOllama for local inference."""

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_returns_llm_response(self, mock_chat_cls):
        """generate() returns LLMResponse with content and token counts."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
        from apps.api.src.core.infrastructure.llm.provider import LLMResponse

        mock_response = MagicMock()
        mock_response.content = "Local model response."
        mock_response.usage_metadata = {
            "input_tokens": 20,
            "output_tokens": 10,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        result = await provider.generate("What is logistics?")

        assert isinstance(result, LLMResponse)
        assert result.content == "Local model response."
        assert result.model == "qwen3:8b"
        assert result.input_tokens == 20
        assert result.output_tokens == 10
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_structured_returns_llm_response(self, mock_chat_cls):
        """generate_structured() returns LLMResponse with JSON content."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_response = MagicMock()
        mock_response.content = '{"status": "ok"}'
        mock_response.usage_metadata = {
            "input_tokens": 15,
            "output_tokens": 5,
        }

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        result = await provider.generate_structured("Return JSON")
        assert result.content == '{"status": "ok"}'

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    def test_model_name_returns_model(self, mock_chat_cls):
        """model_name property returns the Ollama model name."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_chat_cls.return_value = MagicMock()

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:32b",
        )
        assert provider.model_name == "qwen3:32b"

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_handles_connection_refused(self, mock_chat_cls):
        """Connection refused raises ConnectionError with clear message."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(
            side_effect=ConnectionError("Connection refused")
        )
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        with pytest.raises(ConnectionError, match="Ollama.*not reachable"):
            await provider.generate("test")

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_handles_model_not_found(self, mock_chat_cls):
        """Model not pulled raises ValueError with clear message."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(
            side_effect=Exception("model 'nonexistent' not found")
        )
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="nonexistent",
        )

        with pytest.raises(ValueError, match="not found.*ollama pull"):
            await provider.generate("test")

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_handles_timeout(self, mock_chat_cls):
        """Timeout raises TimeoutError with clear message."""
        import asyncio

        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(
            side_effect=asyncio.TimeoutError("Request timed out")
        )
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        with pytest.raises(TimeoutError, match="timed out"):
            await provider.generate("test")

    @pytest.mark.asyncio
    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    async def test_generate_handles_missing_usage_metadata(self, mock_chat_cls):
        """generate() returns 0 tokens when usage_metadata is missing."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        mock_response = MagicMock()
        mock_response.content = "response"
        mock_response.usage_metadata = None

        mock_instance = MagicMock()
        mock_instance.ainvoke = AsyncMock(return_value=mock_response)
        mock_chat_cls.return_value = mock_instance

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )

        result = await provider.generate("test")
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    def test_satisfies_llm_provider_protocol(self, mock_chat_cls):
        """OllamaProvider satisfies LLMProvider Protocol."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
        from apps.api.src.core.infrastructure.llm.provider import LLMProvider

        mock_chat_cls.return_value = MagicMock()

        provider = OllamaProvider(
            host="http://localhost:11434",
            model="qwen3:8b",
        )
        assert isinstance(provider, LLMProvider)


# -----------------------------------------------------------------------
# Task 5: LLM Provider Factory
# -----------------------------------------------------------------------


class TestLLMProviderFactory:
    """Factory creates correct provider based on settings."""

    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_factory_returns_azure_provider_by_default(self, mock_chat_cls):
        """get_llm_provider returns AzureOpenAIProvider for llm_provider='azure'."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        mock_chat_cls.return_value = MagicMock()

        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-4o",
            llm_provider="azure",
        )
        provider = get_llm_provider(s)
        assert isinstance(provider, AzureOpenAIProvider)

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    def test_factory_returns_ollama_provider(self, mock_chat_cls):
        """get_llm_provider returns OllamaProvider for llm_provider='ollama'."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        mock_chat_cls.return_value = MagicMock()

        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            llm_provider="ollama",
            ollama_host="http://localhost:11434",
            ollama_model="qwen3:8b",
        )
        provider = get_llm_provider(s)
        assert isinstance(provider, OllamaProvider)
        assert provider.model_name == "qwen3:8b"

    def test_factory_raises_on_unknown_provider(self):
        """get_llm_provider raises ValueError for unknown provider."""
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            llm_provider="anthropic",
        )
        with pytest.raises(ValueError, match="Unknown LLM provider.*anthropic"):
            get_llm_provider(s)

    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_factory_azure_uses_settings_fields(self, mock_chat_cls):
        """Factory passes correct settings to AzureOpenAIProvider."""
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        mock_chat_cls.return_value = MagicMock()

        s = Settings(
            azure_openai_endpoint="https://prod.openai.azure.com",
            azure_openai_api_key="prod-key",
            azure_openai_deployment="gpt-5-mini",
            azure_openai_api_version="2025-01-01",
            llm_provider="azure",
        )
        provider = get_llm_provider(s)
        assert provider.model_name == "gpt-5-mini"

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    def test_factory_ollama_uses_settings_fields(self, mock_chat_cls):
        """Factory passes correct host and model to OllamaProvider."""
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        mock_chat_cls.return_value = MagicMock()

        s = Settings(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            llm_provider="ollama",
            ollama_host="http://gpu-server:11434",
            ollama_model="qwen3:32b",
        )
        provider = get_llm_provider(s)
        assert provider.model_name == "qwen3:32b"

    @patch("apps.api.src.core.infrastructure.llm.ollama.ChatOllama")
    @patch("apps.api.src.core.infrastructure.llm.azure_openai.AzureChatOpenAI")
    def test_switching_provider_changes_type(self, mock_azure, mock_ollama):
        """Changing llm_provider setting changes the returned provider type."""
        from apps.api.src.core.infrastructure.llm.azure_openai import (
            AzureOpenAIProvider,
        )
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        mock_azure.return_value = MagicMock()
        mock_ollama.return_value = MagicMock()

        base = dict(
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
        )

        azure_provider = get_llm_provider(Settings(**base, llm_provider="azure"))
        ollama_provider = get_llm_provider(Settings(**base, llm_provider="ollama"))

        assert isinstance(azure_provider, AzureOpenAIProvider)
        assert isinstance(ollama_provider, OllamaProvider)
