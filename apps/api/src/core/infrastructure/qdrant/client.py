"""Qdrant client factory."""

from qdrant_client import AsyncQdrantClient

from apps.api.src.core.config.settings import settings

_client: AsyncQdrantClient | None = None


async def get_qdrant_client() -> AsyncQdrantClient:
    """Get or create the singleton Qdrant client."""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
    return _client


async def close_qdrant_client() -> None:
    """Close the Qdrant client connection."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
