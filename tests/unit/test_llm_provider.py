"""Tests for LLM provider infrastructure (Phase 6 -- Air-Gapped Vault).

Covers:
- Settings fields for provider toggle
- LLMProvider Protocol and LLMResponse
- Azure OpenAI and Ollama LLM providers
- LLM provider factory
"""

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
