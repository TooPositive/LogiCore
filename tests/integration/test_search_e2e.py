"""Integration test: end-to-end search with real Qdrant.

Requires: docker compose up qdrant
Run: uv run pytest tests/integration/test_search_e2e.py -v -m integration
"""

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models

from apps.api.src.domain.document import UserContext
from apps.api.src.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    DENSE_VECTOR_SIZE,
)
from apps.api.src.security.rbac import build_qdrant_filter

pytestmark = pytest.mark.integration

TEST_COLLECTION = f"test_{COLLECTION_NAME}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def qdrant_with_data(qdrant_client: AsyncQdrantClient):
    """Set up a test collection with seeded data, tear down after."""
    # Create test collection
    await qdrant_client.create_collection(
        collection_name=TEST_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=models.Distance.COSINE,
            ),
        },
    )
    await qdrant_client.create_payload_index(
        collection_name=TEST_COLLECTION,
        field_name="department_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    await qdrant_client.create_payload_index(
        collection_name=TEST_COLLECTION,
        field_name="clearance_level",
        field_schema=models.PayloadSchemaType.INTEGER,
    )

    # Seed test data with fake embeddings
    import random

    random.seed(42)

    test_docs = [
        # Warehouse docs (clearance 1)
        {
            "content": "ISO 9001 quality management requirements for warehouse operations",
            "document_id": "DOC-SAFETY-001",
            "department_id": "warehouse",
            "clearance_level": 1,
            "source_file": "quality-manual.pdf",
            "chunk_index": 0,
        },
        {
            "content": "Driver safety protocol and pre-trip inspection checklist",
            "document_id": "DOC-HR-003",
            "department_id": "warehouse",
            "clearance_level": 1,
            "source_file": "driver-safety.pdf",
            "chunk_index": 0,
        },
        # HR docs (clearance 3)
        {
            "content": "Employee termination procedures and notice periods under German labor law",
            "document_id": "DOC-HR-004",
            "department_id": "hr",
            "clearance_level": 3,
            "source_file": "termination.pdf",
            "chunk_index": 0,
        },
        # Executive docs (clearance 4)
        {
            "content": "CEO compensation package including salary, bonus, and stock options",
            "document_id": "DOC-HR-002",
            "department_id": "hr",
            "clearance_level": 4,
            "source_file": "exec-compensation.pdf",
            "chunk_index": 0,
        },
        # Legal docs (clearance 2)
        {
            "content": "PharmaCorp contract CTR-2024-001 penalty clause for late delivery",
            "document_id": "DOC-LEGAL-001",
            "department_id": "legal",
            "clearance_level": 2,
            "source_file": "pharmacorp-contract.pdf",
            "chunk_index": 0,
        },
    ]

    points = []
    for i, doc in enumerate(test_docs):
        vec = [random.random() for _ in range(DENSE_VECTOR_SIZE)]
        points.append(
            models.PointStruct(
                id=str(uuid.uuid4()),
                vector={"dense": vec},
                payload=doc,
            )
        )

    await qdrant_client.upsert(collection_name=TEST_COLLECTION, points=points)

    yield qdrant_client

    # Cleanup
    await qdrant_client.delete_collection(TEST_COLLECTION)


class TestRBACFilterIntegration:
    """Test that RBAC filters correctly restrict search results in real Qdrant."""

    async def test_warehouse_worker_sees_only_clearance_1_warehouse(
        self, qdrant_with_data: AsyncQdrantClient
    ):
        user = UserContext(user_id="max.weber", clearance_level=1, departments=["warehouse"])
        rbac_filter = build_qdrant_filter(user)

        results = await qdrant_with_data.scroll(
            collection_name=TEST_COLLECTION,
            scroll_filter=rbac_filter,
            limit=100,
        )

        points, _ = results
        for point in points:
            assert point.payload["clearance_level"] <= 1
            assert point.payload["department_id"] == "warehouse"

        doc_ids = {p.payload["document_id"] for p in points}
        assert "DOC-HR-002" not in doc_ids  # CEO compensation — never visible
        assert "DOC-HR-004" not in doc_ids  # Termination procs — wrong dept + clearance

    async def test_hr_director_sees_hr_docs_up_to_clearance_3(
        self, qdrant_with_data: AsyncQdrantClient
    ):
        user = UserContext(
            user_id="katrin.fischer",
            clearance_level=3,
            departments=["hr", "management"],
        )
        rbac_filter = build_qdrant_filter(user)

        results = await qdrant_with_data.scroll(
            collection_name=TEST_COLLECTION,
            scroll_filter=rbac_filter,
            limit=100,
        )

        points, _ = results
        for point in points:
            assert point.payload["clearance_level"] <= 3

        doc_ids = {p.payload["document_id"] for p in points}
        assert "DOC-HR-004" in doc_ids  # Termination — HR, clearance 3
        assert "DOC-HR-002" not in doc_ids  # CEO comp — clearance 4, filtered out

    async def test_ceo_sees_all_matching_departments(self, qdrant_with_data: AsyncQdrantClient):
        user = UserContext(
            user_id="eva.richter",
            clearance_level=4,
            departments=["hr", "management", "legal", "logistics", "warehouse", "executive"],
        )
        rbac_filter = build_qdrant_filter(user)

        results = await qdrant_with_data.scroll(
            collection_name=TEST_COLLECTION,
            scroll_filter=rbac_filter,
            limit=100,
        )

        points, _ = results
        doc_ids = {p.payload["document_id"] for p in points}
        # CEO should see everything
        assert "DOC-SAFETY-001" in doc_ids
        assert "DOC-HR-002" in doc_ids
        assert "DOC-HR-003" in doc_ids
        assert "DOC-HR-004" in doc_ids
        assert "DOC-LEGAL-001" in doc_ids
