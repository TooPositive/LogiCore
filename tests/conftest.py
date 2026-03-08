"""Shared test fixtures for LogiCore."""

import sys
from pathlib import Path

# Add project root to sys.path so `apps.api.src.*` imports work in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def test_settings():
    """Test settings with local Docker service defaults."""
    from apps.api.src.core.config.settings import Settings

    return Settings(
        azure_openai_endpoint="https://test.openai.azure.com",
        azure_openai_api_key="test-key-not-real",
        azure_openai_deployment="gpt-4o",
        postgres_host="localhost",
        postgres_port=5432,
        postgres_user="logicore",
        postgres_password="changeme",
        postgres_db="logicore",
        qdrant_host="localhost",
        qdrant_port=6333,
        redis_host="localhost",
        redis_port=6379,
        langfuse_host="http://localhost:3001",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM that returns configurable responses."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content="mock response"))
    return llm


@pytest.fixture
def mock_embeddings():
    """Mock embedding model that returns fixed-dimension vectors."""
    import random

    embeddings = MagicMock()
    embeddings.aembed_query = AsyncMock(return_value=[random.random() for _ in range(1536)])
    embeddings.aembed_documents = AsyncMock(
        side_effect=lambda docs: [[random.random() for _ in range(1536)] for _ in docs]
    )
    return embeddings
