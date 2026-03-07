"""Integration test fixtures — require Docker services running."""

import pytest


@pytest.fixture
async def qdrant_client():
    """Real Qdrant client for integration tests."""
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(host="localhost", port=6333, check_compatibility=False)
    yield client
    await client.close()


@pytest.fixture
async def pg_pool():
    """Real PostgreSQL connection pool."""
    import asyncpg

    pool = await asyncpg.create_pool(
        user="logicore",
        password="changeme",
        database="logicore",
        host="localhost",
        port=5432,
        min_size=1,
        max_size=5,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def redis_client():
    """Real Redis client."""
    import redis.asyncio as aioredis

    client = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    yield client
    await client.aclose()
