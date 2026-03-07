"""Tests for multi-provider embedding module — models, providers, factory, benchmark.

RED phase: all tests written before implementation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.src.rag.embeddings import (
    EMBEDDING_LARGE,
    EMBEDDING_MODELS,
    EMBEDDING_SMALL,
    AzureOpenAIEmbedder,
    BaseEmbedder,
    CohereEmbedder,
    EmbeddingBenchmarkResult,
    EmbeddingError,
    EmbeddingModel,
    EmbeddingProvider,
    MockEmbedder,
    get_embedder,
    get_embeddings,
)

# ===========================================================================
# EmbeddingProvider enum tests
# ===========================================================================


class TestEmbeddingProvider:
    def test_azure_openai_value(self):
        assert EmbeddingProvider.AZURE_OPENAI == "azure_openai"

    def test_cohere_value(self):
        assert EmbeddingProvider.COHERE == "cohere"

    def test_nomic_value(self):
        assert EmbeddingProvider.NOMIC == "nomic"

    def test_mock_value(self):
        assert EmbeddingProvider.MOCK == "mock"


# ===========================================================================
# EmbeddingModel dataclass tests
# ===========================================================================


class TestEmbeddingModel:
    def test_all_fields_present(self):
        model = EmbeddingModel(
            name="test-model",
            provider=EmbeddingProvider.AZURE_OPENAI,
            dimensions=1536,
            cost_per_1m_tokens=0.02,
        )
        assert model.name == "test-model"
        assert model.provider == EmbeddingProvider.AZURE_OPENAI
        assert model.dimensions == 1536
        assert model.cost_per_1m_tokens == 0.02

    def test_registry_has_text_embedding_3_small(self):
        m = EMBEDDING_MODELS["text-embedding-3-small"]
        assert m.name == "text-embedding-3-small"
        assert m.provider == EmbeddingProvider.AZURE_OPENAI
        assert m.dimensions == 1536
        assert m.cost_per_1m_tokens == 0.02

    def test_registry_has_text_embedding_3_large(self):
        m = EMBEDDING_MODELS["text-embedding-3-large"]
        assert m.name == "text-embedding-3-large"
        assert m.provider == EmbeddingProvider.AZURE_OPENAI
        assert m.dimensions == 3072
        assert m.cost_per_1m_tokens == 0.13

    def test_registry_has_cohere_embed_v4(self):
        m = EMBEDDING_MODELS["cohere-embed-v4"]
        assert m.name == "cohere-embed-v4"
        assert m.provider == EmbeddingProvider.COHERE
        assert m.dimensions == 1024
        assert m.cost_per_1m_tokens == 0.10

    def test_registry_has_nomic_embed_text_v15(self):
        m = EMBEDDING_MODELS["nomic-embed-text-v1.5"]
        assert m.name == "nomic-embed-text-v1.5"
        assert m.provider == EmbeddingProvider.NOMIC
        assert m.dimensions == 768
        assert m.cost_per_1m_tokens == 0.00


# ===========================================================================
# EmbeddingBenchmarkResult dataclass tests
# ===========================================================================


class TestEmbeddingBenchmarkResult:
    def test_all_fields_present(self):
        result = EmbeddingBenchmarkResult(
            model_name="text-embedding-3-small",
            provider="azure_openai",
            dimensions=1536,
            precision_at_k={5: 0.85, 10: 0.92},
            recall_at_k={5: 0.70, 10: 0.88},
            mrr=0.82,
            avg_latency_ms=45.3,
            cost_per_1m_tokens=0.02,
            total_queries=26,
        )
        assert result.model_name == "text-embedding-3-small"
        assert result.provider == "azure_openai"
        assert result.dimensions == 1536
        assert result.precision_at_k[5] == 0.85
        assert result.recall_at_k[10] == 0.88
        assert result.mrr == 0.82
        assert result.avg_latency_ms == 45.3
        assert result.cost_per_1m_tokens == 0.02
        assert result.total_queries == 26

    def test_default_notes_is_empty_string(self):
        result = EmbeddingBenchmarkResult(
            model_name="m",
            provider="p",
            dimensions=768,
            precision_at_k={},
            recall_at_k={},
            mrr=0.0,
            avg_latency_ms=0.0,
            cost_per_1m_tokens=0.0,
            total_queries=0,
        )
        assert result.notes == ""

    def test_custom_notes(self):
        result = EmbeddingBenchmarkResult(
            model_name="m",
            provider="p",
            dimensions=768,
            precision_at_k={},
            recall_at_k={},
            mrr=0.0,
            avg_latency_ms=0.0,
            cost_per_1m_tokens=0.0,
            total_queries=0,
            notes="Not viable at small corpus scale",
        )
        assert result.notes == "Not viable at small corpus scale"


# ===========================================================================
# BaseEmbedder ABC tests
# ===========================================================================


class TestBaseEmbedder:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseEmbedder()

    def test_subclass_must_implement_all_abstract_methods(self):
        class PartialEmbedder(BaseEmbedder):
            async def embed_query(self, text: str) -> list[float]:
                return []

            # Missing embed_documents and dimensions

        with pytest.raises(TypeError):
            PartialEmbedder()

    @pytest.mark.asyncio
    async def test_subclass_with_all_methods_works(self):
        class GoodEmbedder(BaseEmbedder):
            async def embed_query(self, text: str) -> list[float]:
                return [0.1, 0.2]

            async def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1, 0.2] for _ in texts]

            @property
            def dimensions(self) -> int:
                return 2

        embedder = GoodEmbedder()
        result = await embedder.embed_query("test")
        assert result == [0.1, 0.2]
        assert embedder.dimensions == 2


# ===========================================================================
# MockEmbedder tests
# ===========================================================================


class TestMockEmbedder:
    @pytest.mark.asyncio
    async def test_returns_correct_dimensionality(self):
        """Vectors must have exactly the configured number of dimensions."""
        embedder = MockEmbedder(dimensions=1536)
        vector = await embedder.embed_query("test text")
        assert len(vector) == 1536

    @pytest.mark.asyncio
    async def test_deterministic_same_text_same_vector(self):
        """Same text must always produce the same vector (for reproducible tests)."""
        embedder = MockEmbedder(dimensions=768)
        v1 = await embedder.embed_query("logistics contract")
        v2 = await embedder.embed_query("logistics contract")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_different_texts_different_vectors(self):
        """Different texts must produce different vectors."""
        embedder = MockEmbedder(dimensions=512)
        v1 = await embedder.embed_query("logistics contract")
        v2 = await embedder.embed_query("warehouse operations")
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_embed_query_returns_list_of_floats(self):
        embedder = MockEmbedder(dimensions=100)
        vector = await embedder.embed_query("test")
        assert isinstance(vector, list)
        assert all(isinstance(v, float) for v in vector)

    @pytest.mark.asyncio
    async def test_embed_documents_returns_list_of_lists(self):
        embedder = MockEmbedder(dimensions=256)
        texts = ["doc one", "doc two", "doc three"]
        vectors = await embedder.embed_documents(texts)
        assert len(vectors) == 3
        assert all(len(v) == 256 for v in vectors)

    @pytest.mark.asyncio
    async def test_embed_documents_each_doc_different(self):
        embedder = MockEmbedder(dimensions=128)
        texts = ["alpha", "beta", "gamma"]
        vectors = await embedder.embed_documents(texts)
        # All vectors should be unique
        assert vectors[0] != vectors[1]
        assert vectors[1] != vectors[2]
        assert vectors[0] != vectors[2]

    @pytest.mark.asyncio
    async def test_configurable_dimensions(self):
        """dimensions parameter controls vector size."""
        for dim in [64, 256, 1024, 3072]:
            embedder = MockEmbedder(dimensions=dim)
            vector = await embedder.embed_query("test")
            assert len(vector) == dim

    def test_dimensions_property(self):
        embedder = MockEmbedder(dimensions=1536)
        assert embedder.dimensions == 1536

    @pytest.mark.asyncio
    async def test_embed_documents_empty_list(self):
        embedder = MockEmbedder(dimensions=128)
        vectors = await embedder.embed_documents([])
        assert vectors == []

    @pytest.mark.asyncio
    async def test_vectors_are_normalized(self):
        """Vectors should have values in a reasonable range (not all zeros)."""
        embedder = MockEmbedder(dimensions=256)
        vector = await embedder.embed_query("test normalization")
        # At least some values should be non-zero
        assert any(v != 0.0 for v in vector)
        # Values should be in a reasonable range (like real embeddings)
        assert all(-2.0 <= v <= 2.0 for v in vector)


# ===========================================================================
# AzureOpenAIEmbedder tests (mocked langchain)
# ===========================================================================


class TestAzureOpenAIEmbedder:
    @pytest.mark.asyncio
    async def test_embed_query_delegates_to_langchain(self):
        """Should call langchain AzureOpenAIEmbeddings.aembed_query."""
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.aembed_query = AsyncMock(
                return_value=[0.1] * 1536
            )
            mock_cls.return_value = mock_instance

            embedder = AzureOpenAIEmbedder(
                model="text-embedding-3-small",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
                api_version="2024-12-01-preview",
            )
            result = await embedder.embed_query("test query")

            mock_instance.aembed_query.assert_called_once_with("test query")
            assert len(result) == 1536

    @pytest.mark.asyncio
    async def test_embed_documents_delegates_to_langchain(self):
        """Should call langchain AzureOpenAIEmbeddings.aembed_documents."""
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.aembed_documents = AsyncMock(
                return_value=[[0.1] * 1536, [0.2] * 1536]
            )
            mock_cls.return_value = mock_instance

            embedder = AzureOpenAIEmbedder(
                model="text-embedding-3-small",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
                api_version="2024-12-01-preview",
            )
            result = await embedder.embed_documents(["doc1", "doc2"])

            mock_instance.aembed_documents.assert_called_once_with(["doc1", "doc2"])
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_langchain(self):
        """Constructor should pass model, endpoint, key, version to langchain."""
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings") as mock_cls:
            mock_cls.return_value = MagicMock()

            AzureOpenAIEmbedder(
                model="text-embedding-3-large",
                endpoint="https://custom.openai.azure.com",
                api_key="my-key-123",
                api_version="2024-06-01",
            )

            mock_cls.assert_called_once_with(
                azure_endpoint="https://custom.openai.azure.com",
                api_key="my-key-123",
                api_version="2024-06-01",
                azure_deployment="text-embedding-3-large",
            )

    def test_dimensions_property_small_model(self):
        """Should return dimensions from EMBEDDING_MODELS registry."""
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"):
            embedder = AzureOpenAIEmbedder(
                model="text-embedding-3-small",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
            )
            assert embedder.dimensions == 1536

    def test_dimensions_property_large_model(self):
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"):
            embedder = AzureOpenAIEmbedder(
                model="text-embedding-3-large",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
            )
            assert embedder.dimensions == 3072

    def test_dimensions_property_unknown_model_defaults(self):
        """Unknown model name should use a sensible default dimension."""
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"):
            embedder = AzureOpenAIEmbedder(
                model="custom-deployment-xyz",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
            )
            # Unknown models should default to 1536 (most common)
            assert embedder.dimensions == 1536


# ===========================================================================
# CohereEmbedder tests (mocked httpx)
# ===========================================================================


class TestCohereEmbedder:
    @pytest.mark.asyncio
    async def test_calls_cohere_embed_api_correctly(self):
        """Should POST to Cohere Embed API with correct body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": {"float": [[0.1] * 1024]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(api_key="test-key", model="embed-v4.0")
            await embedder.embed_query("test query")

            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["texts"] == ["test query"]
            assert body["model"] == "embed-v4.0"
            assert body["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_embed_query_returns_correct_dimensions(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": {"float": [[0.1] * 1024]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(api_key="test-key")
            result = await embedder.embed_query("test")

            assert len(result) == 1024
            assert isinstance(result, list)
            assert all(isinstance(v, float) for v in result)

    @pytest.mark.asyncio
    async def test_embed_documents_returns_multiple_vectors(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": {"float": [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(api_key="test-key")
            result = await embedder.embed_documents(["a", "b", "c"])

            assert len(result) == 3
            # embed_documents should use "search_document" input_type
            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["input_type"] == "search_document"

    @pytest.mark.asyncio
    async def test_api_error_raises_embedding_error(self):
        """HTTP errors from Cohere should raise EmbeddingError."""
        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(api_key="test-key")
            with pytest.raises(EmbeddingError):
                await embedder.embed_query("test")

    @pytest.mark.asyncio
    async def test_configurable_model_name(self):
        """Model name should be passed through to API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": {"float": [[0.1] * 1024]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(
                api_key="key", model="embed-multilingual-v3.0"
            )
            await embedder.embed_query("test")

            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["model"] == "embed-multilingual-v3.0"

    @pytest.mark.asyncio
    async def test_configurable_input_type(self):
        """input_type should be configurable for different use cases."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "embeddings": {"float": [[0.1] * 1024]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("apps.api.src.rag.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            embedder = CohereEmbedder(
                api_key="key", input_type="classification"
            )
            await embedder.embed_query("test")

            call_kwargs = mock_client.post.call_args
            body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert body["input_type"] == "classification"

    def test_dimensions_property(self):
        embedder = CohereEmbedder(api_key="key", model="embed-v4.0")
        assert embedder.dimensions == 1024

    def test_dimensions_property_unknown_model(self):
        """Unknown model should default to 1024."""
        embedder = CohereEmbedder(api_key="key", model="custom-cohere-model")
        assert embedder.dimensions == 1024


# ===========================================================================
# Factory function tests
# ===========================================================================


class TestGetEmbedder:
    def test_returns_mock_embedder(self):
        embedder = get_embedder("mock", dimensions=512)
        assert isinstance(embedder, MockEmbedder)
        assert embedder.dimensions == 512

    def test_returns_azure_openai_embedder(self):
        with patch("apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"):
            embedder = get_embedder(
                "azure_openai",
                model="text-embedding-3-small",
                endpoint="https://test.openai.azure.com",
                api_key="test-key",
            )
            assert isinstance(embedder, AzureOpenAIEmbedder)

    def test_returns_cohere_embedder(self):
        embedder = get_embedder("cohere", api_key="test-key")
        assert isinstance(embedder, CohereEmbedder)

    def test_invalid_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_embedder("nonexistent_provider")

    def test_passes_kwargs_to_mock(self):
        embedder = get_embedder("mock", dimensions=3072)
        assert embedder.dimensions == 3072

    def test_passes_kwargs_to_cohere(self):
        embedder = get_embedder(
            "cohere",
            api_key="my-key",
            model="embed-multilingual-v3.0",
            input_type="classification",
        )
        assert isinstance(embedder, CohereEmbedder)

    def test_accepts_enum_value(self):
        embedder = get_embedder(EmbeddingProvider.MOCK, dimensions=256)
        assert isinstance(embedder, MockEmbedder)


# ===========================================================================
# Backward compatibility tests
# ===========================================================================


class TestBackwardCompatibility:
    def test_get_embeddings_still_works(self):
        """Phase 1 code depends on get_embeddings() returning langchain object."""
        with patch("apps.api.src.rag.embeddings.settings") as mock_settings:
            mock_settings.azure_openai_endpoint = "https://test.openai.azure.com"
            mock_settings.azure_openai_api_key = "test-key"
            mock_settings.azure_openai_api_version = "2024-12-01-preview"

            with patch(
                "apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"
            ) as mock_cls:
                mock_cls.return_value = MagicMock()
                get_embeddings()
                mock_cls.assert_called_once()

    def test_get_embeddings_with_model_param(self):
        """get_embeddings(model=...) should still work for Phase 1 benchmarks."""
        with patch("apps.api.src.rag.embeddings.settings") as mock_settings:
            mock_settings.azure_openai_endpoint = "https://test.openai.azure.com"
            mock_settings.azure_openai_api_key = "test-key"
            mock_settings.azure_openai_api_version = "2024-12-01-preview"

            with patch(
                "apps.api.src.rag.embeddings.AzureOpenAIEmbeddings"
            ) as mock_cls:
                mock_cls.return_value = MagicMock()
                get_embeddings(model="text-embedding-3-large")
                call_kwargs = mock_cls.call_args
                assert (
                    call_kwargs.kwargs.get("azure_deployment")
                    == "text-embedding-3-large"
                )

    def test_embedding_small_constant_still_exported(self):
        assert EMBEDDING_SMALL == "text-embedding-3-small"

    def test_embedding_large_constant_still_exported(self):
        assert EMBEDDING_LARGE == "text-embedding-3-large"


# ===========================================================================
# EmbeddingError tests
# ===========================================================================


class TestEmbeddingError:
    def test_is_exception(self):
        assert issubclass(EmbeddingError, Exception)

    def test_has_message(self):
        err = EmbeddingError("API call failed")
        assert str(err) == "API call failed"
