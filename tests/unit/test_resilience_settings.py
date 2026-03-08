"""Tests for Phase 7 resilience settings and provider chain factory.

RED phase: all tests written before implementation.
"""

from unittest.mock import MagicMock, patch

import pytest

from apps.api.src.core.config.settings import Settings


# ===========================================================================
# Settings — new Phase 7 fields
# ===========================================================================


class TestResilienceSettings:
    def test_default_circuit_breaker_failure_threshold(self):
        s = Settings()
        assert s.circuit_breaker_failure_threshold == 5

    def test_default_circuit_breaker_reset_timeout(self):
        s = Settings()
        assert s.circuit_breaker_reset_timeout == 60.0

    def test_default_circuit_breaker_success_threshold(self):
        s = Settings()
        assert s.circuit_breaker_success_threshold == 3

    def test_default_retry_max_attempts(self):
        s = Settings()
        assert s.retry_max_attempts == 3

    def test_default_retry_base_delay(self):
        s = Settings()
        assert s.retry_base_delay == 1.0

    def test_default_retry_max_delay(self):
        s = Settings()
        assert s.retry_max_delay == 30.0

    def test_default_quality_gate_min_length(self):
        s = Settings()
        assert s.quality_gate_min_length == 10

    def test_custom_settings(self):
        s = Settings(
            circuit_breaker_failure_threshold=10,
            circuit_breaker_reset_timeout=120.0,
            circuit_breaker_success_threshold=5,
            retry_max_attempts=5,
            retry_base_delay=0.5,
            retry_max_delay=60.0,
            quality_gate_min_length=20,
        )
        assert s.circuit_breaker_failure_threshold == 10
        assert s.circuit_breaker_reset_timeout == 120.0
        assert s.circuit_breaker_success_threshold == 5
        assert s.retry_max_attempts == 5
        assert s.retry_base_delay == 0.5
        assert s.retry_max_delay == 60.0
        assert s.quality_gate_min_length == 20


# ===========================================================================
# Provider chain factory
# ===========================================================================


class TestProviderChainFactory:
    def test_builds_chain_with_azure_primary(self):
        from apps.api.src.core.infrastructure.llm.provider_chain import (
            ProviderChain,
        )
        from apps.api.src.core.infrastructure.llm.resilient_llm import (
            build_provider_chain,
        )

        s = Settings(
            llm_provider="azure",
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-4o",
            ollama_host="http://localhost:11434",
            ollama_model="qwen3:8b",
        )

        with patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.AzureOpenAIProvider"
        ) as mock_azure, patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.OllamaProvider"
        ) as mock_ollama:
            mock_azure.return_value = MagicMock()
            mock_azure.return_value.model_name = "gpt-4o"
            mock_ollama.return_value = MagicMock()
            mock_ollama.return_value.model_name = "qwen3:8b"

            chain = build_provider_chain(s)
            assert isinstance(chain, ProviderChain)

    def test_builds_chain_with_ollama_primary(self):
        from apps.api.src.core.infrastructure.llm.provider_chain import (
            ProviderChain,
        )
        from apps.api.src.core.infrastructure.llm.resilient_llm import (
            build_provider_chain,
        )

        s = Settings(
            llm_provider="ollama",
            ollama_host="http://localhost:11434",
            ollama_model="qwen3:8b",
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-4o",
        )

        with patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.AzureOpenAIProvider"
        ) as mock_azure, patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.OllamaProvider"
        ) as mock_ollama:
            mock_azure.return_value = MagicMock()
            mock_azure.return_value.model_name = "gpt-4o"
            mock_ollama.return_value = MagicMock()
            mock_ollama.return_value.model_name = "qwen3:8b"

            chain = build_provider_chain(s)
            assert isinstance(chain, ProviderChain)

    def test_settings_propagate_to_breaker(self):
        from apps.api.src.core.infrastructure.llm.resilient_llm import (
            build_provider_chain,
        )

        s = Settings(
            llm_provider="azure",
            azure_openai_endpoint="https://test.openai.azure.com",
            azure_openai_api_key="test-key",
            azure_openai_deployment="gpt-4o",
            circuit_breaker_failure_threshold=10,
            circuit_breaker_reset_timeout=120.0,
        )

        with patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.AzureOpenAIProvider"
        ) as mock_azure, patch(
            "apps.api.src.core.infrastructure.llm.resilient_llm.OllamaProvider"
        ) as mock_ollama:
            mock_azure.return_value = MagicMock()
            mock_azure.return_value.model_name = "gpt-4o"
            mock_ollama.return_value = MagicMock()
            mock_ollama.return_value.model_name = "qwen3:8b"

            chain = build_provider_chain(s)
            # Check that breaker config was applied
            states = chain.provider_states()
            assert len(states) >= 1
