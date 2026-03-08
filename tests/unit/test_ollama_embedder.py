"""Tests for OllamaEmbedder (Phase 6 -- Air-Gapped Vault).

Tests embedding via Ollama's /api/embed endpoint using httpx.
All tests mock the HTTP calls -- no real Ollama needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.api.src.core.rag.embeddings import (
    EMBEDDING_MODELS,
    BaseEmbedder,
    EmbeddingError,
    EmbeddingProvider,
    get_embedder,
)


# -----------------------------------------------------------------------
# OllamaEmbedder unit tests
# -----------------------------------------------------------------------


class TestOllamaEmbedder:
    """OllamaEmbedder calls Ollama /api/embed for local embeddings."""

    def test_ollama_in_embedding_provider_enum(self):
        """EmbeddingProvider has OLLAMA variant."""
        assert EmbeddingProvider.OLLAMA == "ollama"

    def test_nomic_embed_text_in_embedding_models(self):
        """nomic-embed-text registered in EMBEDDING_MODELS."""
        assert "nomic-embed-text" in EMBEDDING_MODELS
        model = EMBEDDING_MODELS["nomic-embed-text"]
        assert model.dimensions == 768
        assert model.cost_per_1m_tokens == 0.00
        assert model.provider == EmbeddingProvider.OLLAMA

    def test_ollama_embedder_is_base_embedder(self):
        """OllamaEmbedder extends BaseEmbedder ABC."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
        )
        assert isinstance(embedder, BaseEmbedder)

    def test_ollama_embedder_dimensions(self):
        """OllamaEmbedder reports correct dimensions."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )
        assert embedder.dimensions == 768

    def test_ollama_embedder_custom_dimensions(self):
        """OllamaEmbedder supports custom dimension count."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=512,
        )
        assert embedder.dimensions == 512

    @pytest.mark.asyncio
    async def test_embed_query_returns_correct_dimensions(self):
        """embed_query returns vector with correct dimension count."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        fake_embedding = [0.1] * 768

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [fake_embedding],
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await embedder.embed_query("test query")

        assert len(result) == 768
        assert result == fake_embedding

    @pytest.mark.asyncio
    async def test_embed_documents_returns_list_of_vectors(self):
        """embed_documents returns list of vectors, one per document."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        fake_embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=768,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "embeddings": fake_embeddings,
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await embedder.embed_documents(
                ["doc 1", "doc 2", "doc 3"]
            )

        assert len(result) == 3
        assert all(len(v) == 768 for v in result)

    @pytest.mark.asyncio
    async def test_embed_query_calls_correct_endpoint(self):
        """embed_query calls /api/embed with correct payload."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://gpu-server:11434",
            model="nomic-embed-text",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768],
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await embedder.embed_query("test")

            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "http://gpu-server:11434/api/embed"
            payload = call_args[1]["json"]
            assert payload["model"] == "nomic-embed-text"
            assert payload["input"] == ["test"]

    @pytest.mark.asyncio
    async def test_embed_query_connection_refused_raises_embedding_error(self):
        """Connection refused raises EmbeddingError."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nomic-embed-text",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(EmbeddingError, match="Ollama.*failed"):
                await embedder.embed_query("test")

    @pytest.mark.asyncio
    async def test_embed_query_model_not_found_raises_embedding_error(self):
        """Model not found raises EmbeddingError with pull suggestion."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = OllamaEmbedder(
            host="http://localhost:11434",
            model="nonexistent-model",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(EmbeddingError, match="Ollama.*failed"):
                await embedder.embed_query("test")


class TestOllamaEmbedderFactory:
    """OllamaEmbedder is registered in the get_embedder factory."""

    def test_get_embedder_returns_ollama_embedder(self):
        """get_embedder('ollama') returns OllamaEmbedder."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = get_embedder(
            "ollama",
            host="http://localhost:11434",
            model="nomic-embed-text",
        )
        assert isinstance(embedder, OllamaEmbedder)

    def test_get_embedder_ollama_with_enum(self):
        """get_embedder(EmbeddingProvider.OLLAMA) works."""
        from apps.api.src.core.rag.embeddings import OllamaEmbedder

        embedder = get_embedder(
            EmbeddingProvider.OLLAMA,
            host="http://localhost:11434",
            model="nomic-embed-text",
        )
        assert isinstance(embedder, OllamaEmbedder)

    def test_get_embedder_ollama_dimensions(self):
        """get_embedder('ollama') respects custom dimensions."""
        embedder = get_embedder(
            "ollama",
            host="http://localhost:11434",
            model="nomic-embed-text",
            dimensions=512,
        )
        assert embedder.dimensions == 512
