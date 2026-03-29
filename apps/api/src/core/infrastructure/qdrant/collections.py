"""Qdrant collection schemas for the Corporate Brain."""

from qdrant_client import AsyncQdrantClient, models

COLLECTION_NAME = "corporate_knowledge"
DENSE_VECTOR_SIZE = 1536  # text-embedding-3-small (default)
DENSE_LARGE_VECTOR_SIZE = 3072  # text-embedding-3-large (benchmark)


async def ensure_collection(
    client: AsyncQdrantClient,
    dense_size: int = DENSE_VECTOR_SIZE,
) -> None:
    """Create the corporate_knowledge collection if it doesn't exist."""
    exists = await client.collection_exists(COLLECTION_NAME)
    if exists:
        return

    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": models.VectorParams(
                size=dense_size,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
        },
    )

    # Create payload indexes for RBAC filtering
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="department_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="clearance_level",
        field_schema=models.PayloadSchemaType.INTEGER,
    )
    await client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="document_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
