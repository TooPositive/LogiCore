"""Embedding wrappers for Azure OpenAI.

Supports both text-embedding-3-small (1536d) and text-embedding-3-large (3072d)
for benchmarking quality vs cost tradeoffs.
"""

from langchain_openai import AzureOpenAIEmbeddings

from apps.api.src.config.settings import settings

EMBEDDING_SMALL = "text-embedding-3-small"  # 1536d, ~$0.02/1M tokens
EMBEDDING_LARGE = "text-embedding-3-large"  # 3072d, ~$0.13/1M tokens


def get_embeddings(model: str = EMBEDDING_SMALL) -> AzureOpenAIEmbeddings:
    """Create an Azure OpenAI embeddings instance.

    Args:
        model: Deployment name — "text-embedding-3-small" or "text-embedding-3-large"
    """
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        azure_deployment=model,
    )
