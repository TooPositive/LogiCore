"""Integration tests for local inference with Ollama (Phase 6).

These tests require a running Ollama instance on localhost:11434
with qwen3:8b and nomic-embed-text models pulled.

Run: pytest tests/integration/test_local_inference.py -v -m integration

Skip if Ollama is not running -- tests are marked with @pytest.mark.integration.
"""

from __future__ import annotations

import httpx
import pytest

# Check if Ollama is available before running tests
OLLAMA_HOST = "http://localhost:11434"


def ollama_available() -> bool:
    """Check if Ollama is running and reachable."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not ollama_available(),
        reason="Ollama not running at localhost:11434",
    ),
]


class TestOllamaLLMIntegration:
    """Integration tests for OllamaProvider with real Ollama."""

    @pytest.mark.asyncio
    async def test_generate_simple_query(self):
        """OllamaProvider can generate a response to a simple query."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host=OLLAMA_HOST,
            model="qwen3:8b",
        )

        result = await provider.generate(
            "What is 2 + 2? Answer with just the number."
        )

        assert result.content is not None
        assert len(result.content) > 0
        assert result.model == "qwen3:8b"
        assert result.input_tokens > 0
        assert result.output_tokens > 0
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_generate_structured_json(self):
        """OllamaProvider can generate structured JSON output."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host=OLLAMA_HOST,
            model="qwen3:8b",
        )

        result = await provider.generate_structured(
            "Return a JSON object with fields: name (string), value (number). "
            "Use name='test' and value=42. Return ONLY the JSON, nothing else."
        )

        assert result.content is not None
        assert result.model == "qwen3:8b"
        # Should contain JSON-like content
        assert "{" in result.content

    @pytest.mark.asyncio
    async def test_model_name_correct(self):
        """model_name matches the configured model."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host=OLLAMA_HOST,
            model="qwen3:8b",
        )

        assert provider.model_name == "qwen3:8b"

    @pytest.mark.asyncio
    async def test_latency_is_reasonable(self):
        """Response completes within 60 seconds for a simple query."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host=OLLAMA_HOST,
            model="qwen3:8b",
        )

        result = await provider.generate("Say 'hello' in Polish.")

        assert result.latency_ms < 60_000  # 60 seconds max
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_token_counts_are_positive(self):
        """Token counts are positive for a successful generation."""
        from apps.api.src.core.infrastructure.llm.ollama import OllamaProvider

        provider = OllamaProvider(
            host=OLLAMA_HOST,
            model="qwen3:8b",
        )

        result = await provider.generate("What color is the sky?")

        assert result.input_tokens > 0
        assert result.output_tokens > 0
        assert result.total_tokens > 0


class TestOllamaEmbeddingIntegration:
    """Integration tests for OllamaEmbedder with real Ollama."""

    @pytest.mark.asyncio
    async def test_embed_query_returns_vector(self):
        """OllamaEmbedder returns a vector for a query."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host=OLLAMA_HOST,
            model="nomic-embed-text",
            dimensions=768,
        )

        try:
            vector = await embedder.embed_query("test query")
            assert isinstance(vector, list)
            assert len(vector) == 768
            assert all(isinstance(v, float) for v in vector)
        except Exception as e:
            if "not found" in str(e).lower():
                pytest.skip(
                    "nomic-embed-text not pulled. "
                    "Run: ollama pull nomic-embed-text"
                )
            raise

    @pytest.mark.asyncio
    async def test_embed_documents_returns_vectors(self):
        """OllamaEmbedder returns vectors for multiple documents."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host=OLLAMA_HOST,
            model="nomic-embed-text",
            dimensions=768,
        )

        try:
            vectors = await embedder.embed_documents(
                ["document one", "document two"]
            )
            assert len(vectors) == 2
            assert all(len(v) == 768 for v in vectors)
        except Exception as e:
            if "not found" in str(e).lower():
                pytest.skip(
                    "nomic-embed-text not pulled. "
                    "Run: ollama pull nomic-embed-text"
                )
            raise

    @pytest.mark.asyncio
    async def test_embed_same_text_produces_same_vector(self):
        """Same text produces the same embedding (deterministic)."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host=OLLAMA_HOST,
            model="nomic-embed-text",
            dimensions=768,
        )

        try:
            v1 = await embedder.embed_query("test query")
            v2 = await embedder.embed_query("test query")
            # Vectors should be identical (deterministic)
            assert v1 == v2
        except Exception as e:
            if "not found" in str(e).lower():
                pytest.skip(
                    "nomic-embed-text not pulled. "
                    "Run: ollama pull nomic-embed-text"
                )
            raise

    @pytest.mark.asyncio
    async def test_different_texts_produce_different_vectors(self):
        """Different texts produce different embeddings."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host=OLLAMA_HOST,
            model="nomic-embed-text",
            dimensions=768,
        )

        try:
            v1 = await embedder.embed_query("logistics transport")
            v2 = await embedder.embed_query("quantum physics")
            # Vectors should be different
            assert v1 != v2
        except Exception as e:
            if "not found" in str(e).lower():
                pytest.skip(
                    "nomic-embed-text not pulled. "
                    "Run: ollama pull nomic-embed-text"
                )
            raise


class TestProviderFactoryIntegration:
    """Factory produces working providers with real backends."""

    @pytest.mark.asyncio
    async def test_factory_creates_working_ollama_provider(self):
        """get_llm_provider with ollama creates a functional provider."""
        from apps.api.src.core.config.settings import Settings
        from apps.api.src.core.infrastructure.llm.provider import (
            get_llm_provider,
        )

        settings = Settings(
            azure_openai_endpoint="https://unused.openai.azure.com",
            azure_openai_api_key="unused",
            llm_provider="ollama",
            ollama_host=OLLAMA_HOST,
            ollama_model="qwen3:8b",
        )

        provider = get_llm_provider(settings)
        result = await provider.generate("Say hello.")

        assert result.content is not None
        assert len(result.content) > 0
