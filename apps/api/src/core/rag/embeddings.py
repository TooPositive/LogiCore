"""Multi-provider embedding module with benchmark harness.

Supports Azure OpenAI, Cohere, Nomic (placeholder), and Mock (testing) providers.
All providers implement BaseEmbedder ABC for uniform interface.

Phase 1 backward compatibility: get_embeddings() still returns langchain
AzureOpenAIEmbeddings directly. New code should use get_embedder() factory.
"""

from __future__ import annotations

import hashlib
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

import httpx
from langchain_openai import AzureOpenAIEmbeddings

from apps.api.src.core.config.settings import settings

# ---------------------------------------------------------------------------
# Legacy constants (Phase 1 backward compatibility)
# ---------------------------------------------------------------------------

EMBEDDING_SMALL = "text-embedding-3-small"  # 1536d, ~$0.02/1M tokens
EMBEDDING_LARGE = "text-embedding-3-large"  # 3072d, ~$0.13/1M tokens


# ---------------------------------------------------------------------------
# Provider enum
# ---------------------------------------------------------------------------


class EmbeddingProvider(StrEnum):
    AZURE_OPENAI = "azure_openai"
    COHERE = "cohere"
    NOMIC = "nomic"
    MOCK = "mock"


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class EmbeddingError(Exception):
    """Raised when embedding operations fail."""


# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingModel:
    """Metadata for a known embedding model."""

    name: str
    provider: EmbeddingProvider
    dimensions: int
    cost_per_1m_tokens: float  # USD


EMBEDDING_MODELS: dict[str, EmbeddingModel] = {
    "text-embedding-3-small": EmbeddingModel(
        "text-embedding-3-small", EmbeddingProvider.AZURE_OPENAI, 1536, 0.02
    ),
    "text-embedding-3-large": EmbeddingModel(
        "text-embedding-3-large", EmbeddingProvider.AZURE_OPENAI, 3072, 0.13
    ),
    "cohere-embed-v4": EmbeddingModel(
        "cohere-embed-v4", EmbeddingProvider.COHERE, 1024, 0.10
    ),
    "nomic-embed-text-v1.5": EmbeddingModel(
        "nomic-embed-text-v1.5", EmbeddingProvider.NOMIC, 768, 0.00
    ),
}


# ---------------------------------------------------------------------------
# Benchmark result
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingBenchmarkResult:
    """Captures benchmark results for a single embedding model."""

    model_name: str
    provider: str
    dimensions: int
    precision_at_k: dict[int, float]
    recall_at_k: dict[int, float]
    mrr: float
    avg_latency_ms: float
    cost_per_1m_tokens: float
    total_queries: int
    notes: str = ""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseEmbedder(ABC):
    """Abstract base class for all embedding providers."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple document texts."""
        ...

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Number of dimensions in the output vectors."""
        ...


# ---------------------------------------------------------------------------
# MockEmbedder
# ---------------------------------------------------------------------------


class MockEmbedder(BaseEmbedder):
    """Deterministic hash-based embeddings for testing.

    Same text always produces the same vector. Different texts produce
    different vectors. No external dependencies.
    """

    def __init__(self, dimensions: int = 1536) -> None:
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic vector via SHA-256 hash expansion."""
        # Generate enough hash bytes to fill all dimensions
        vectors: list[float] = []
        block = 0
        while len(vectors) < self._dimensions:
            h = hashlib.sha256(f"{text}:{block}".encode()).digest()
            # Each 4 bytes -> one float in [-1, 1]
            for i in range(0, len(h), 4):
                if len(vectors) >= self._dimensions:
                    break
                # Unpack as unsigned int, normalize to [-1, 1]
                val = struct.unpack(">I", h[i : i + 4])[0]
                normalized = (val / (2**32 - 1)) * 2.0 - 1.0
                vectors.append(normalized)
            block += 1
        return vectors[: self._dimensions]

    async def embed_query(self, text: str) -> list[float]:
        return self._hash_to_vector(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(t) for t in texts]


# ---------------------------------------------------------------------------
# AzureOpenAIEmbedder
# ---------------------------------------------------------------------------


class AzureOpenAIEmbedder(BaseEmbedder):
    """Wraps langchain AzureOpenAIEmbeddings behind BaseEmbedder interface."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        endpoint: str = "",
        api_key: str = "",
        api_version: str = "",
    ) -> None:
        self._model = model
        self._client = AzureOpenAIEmbeddings(
            azure_endpoint=endpoint or settings.azure_openai_endpoint,
            api_key=api_key or settings.azure_openai_api_key,
            api_version=api_version or settings.azure_openai_api_version,
            azure_deployment=model,
        )
        # Look up dimensions from registry, default to 1536
        model_info = EMBEDDING_MODELS.get(model)
        self._dimensions = model_info.dimensions if model_info else 1536

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_query(self, text: str) -> list[float]:
        return await self._client.aembed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)


# ---------------------------------------------------------------------------
# CohereEmbedder
# ---------------------------------------------------------------------------

COHERE_EMBED_URL = "https://api.cohere.com/v2/embed"


class CohereEmbedder(BaseEmbedder):
    """Cohere Embed API via httpx (not SDK).

    Uses Cohere v2 embed endpoint. input_type is automatically set:
    - embed_query: "search_query"
    - embed_documents: "search_document"
    Unless overridden via constructor.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "embed-v4.0",
        input_type: str = "search_query",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._input_type = input_type
        # Cohere embed-v4.0 defaults to 1024
        model_info = EMBEDDING_MODELS.get(model)
        self._dimensions = model_info.dimensions if model_info else 1024

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _call_api(
        self, texts: list[str], input_type: str
    ) -> list[list[float]]:
        """Call Cohere Embed API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    COHERE_EMBED_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "texts": texts,
                        "model": self._model,
                        "input_type": input_type,
                        "embedding_types": ["float"],
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise EmbeddingError(
                f"Cohere embed API failed: {exc}"
            ) from exc

        return data["embeddings"]["float"]

    async def embed_query(self, text: str) -> list[float]:
        results = await self._call_api([text], self._input_type)
        return results[0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._call_api(texts, "search_document")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_embedder(provider: str | EmbeddingProvider, **kwargs) -> BaseEmbedder:
    """Factory function to create an embedder by provider name.

    Args:
        provider: "azure_openai", "cohere", "mock", or EmbeddingProvider enum
        **kwargs: Passed through to the embedder constructor

    Returns:
        BaseEmbedder instance
    """
    provider_str = str(provider)

    constructors: dict[str, type[BaseEmbedder]] = {
        EmbeddingProvider.AZURE_OPENAI: AzureOpenAIEmbedder,
        EmbeddingProvider.COHERE: CohereEmbedder,
        EmbeddingProvider.MOCK: MockEmbedder,
    }

    if provider_str not in constructors:
        raise ValueError(
            f"Unknown embedding provider: {provider_str!r}. "
            f"Valid providers: {list(constructors.keys())}"
        )

    return constructors[provider_str](**kwargs)


# ---------------------------------------------------------------------------
# Legacy wrapper (Phase 1 backward compatibility)
# ---------------------------------------------------------------------------


def get_embeddings(model: str = EMBEDDING_SMALL) -> AzureOpenAIEmbeddings:
    """Create an Azure OpenAI embeddings instance.

    BACKWARD COMPATIBLE: Phase 1 code depends on this returning a
    langchain AzureOpenAIEmbeddings object directly (not BaseEmbedder).

    Args:
        model: Deployment name -- "text-embedding-3-small" or "text-embedding-3-large"
    """
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        azure_deployment=model,
    )
