"""Phase 1 LIVE E2E: Real Azure OpenAI embeddings + Real Qdrant.

Tests the full pipeline with actual embeddings — verifies semantic search quality
and RBAC filtering works with real vectors, not mocks.

Requires:
- Docker: qdrant running on localhost:6333
- Azure OpenAI credentials in .env (text-embedding-3-small deployment)

Run manually:
    uv run pytest tests/e2e/test_phase1_live.py -v -m live

NOT run as part of the normal test suite (expensive, needs credentials).
"""

import pytest
from qdrant_client import AsyncQdrantClient

from apps.api.src.domain.document import UserContext
from apps.api.src.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    ensure_collection,
)
from apps.api.src.rag.embeddings import get_embeddings
from apps.api.src.rag.ingestion import ingest_document
from apps.api.src.rag.retriever import hybrid_search

pytestmark = pytest.mark.live

# -- Demo users from the Phase 1 scenario --
WAREHOUSE_WORKER = UserContext(user_id="max.weber", clearance_level=1, departments=["warehouse"])
HR_DIRECTOR = UserContext(
    user_id="katrin.fischer", clearance_level=3, departments=["hr", "management"]
)
CEO = UserContext(
    user_id="eva.richter",
    clearance_level=4,
    departments=["hr", "management", "legal", "logistics", "warehouse", "executive"],
)
LOGISTICS_MANAGER = UserContext(
    user_id="anna.schmidt", clearance_level=2, departments=["logistics", "warehouse"]
)

# -- Document corpus --
DOCS = [
    (
        "ISO 9001 Quality Management Manual. Section 4.2: Quality management "
        "requirements for warehouse operations. All incoming goods must be "
        "inspected within 4 hours of receipt. Temperature-sensitive cargo "
        "requires continuous monitoring. Vehicle maintenance follows a "
        "10,000 km interval schedule.",
        "DOC-SAFETY-001",
        "warehouse",
        1,
        "quality-manual.txt",
    ),
    (
        "Driver Safety Protocol. Pre-trip inspection checklist. EU Regulation "
        "(EC) No 561/2006 applies to all LogiCore drivers. Maximum daily "
        "driving: 9 hours. Continuous driving break: 45 minutes after 4.5 hours. "
        "Pharmaceutical shipments: maintain 2-8 degrees Celsius at all times.",
        "DOC-HR-003",
        "warehouse",
        1,
        "driver-safety.txt",
    ),
    (
        "Executive Compensation Policy CONFIDENTIAL. CEO salary EUR 280,000 "
        "per annum. Performance bonus up to 40% of base salary. Stock options: "
        "50,000 shares vesting over 4 years. CFO salary EUR 220,000. "
        "CTO salary EUR 240,000. Technology education budget EUR 15,000/year.",
        "DOC-HR-002",
        "hr",
        4,
        "exec-compensation.txt",
    ),
    (
        "Employee Termination Procedures HR CONFIDENTIAL. Performance-based "
        "termination: two consecutive quarterly reviews below 2.0/5.0. "
        "Notice periods per Kodeks Pracy Art. 36. Severance formula: 0.5 months "
        "salary per year of service. Works Council (Zwiazki Zawodowe) must be "
        "notified per Art. 38 KP.",
        "DOC-HR-004",
        "hr",
        3,
        "termination.txt",
    ),
    (
        "PharmaCorp Service Agreement CTR-2024-001. Temperature-controlled "
        "pharmaceutical logistics. SLA: on-time delivery >= 98.5%. "
        "Penalty: EUR 500 per late shipment. Temperature excursion: EUR 2,000 "
        "per incident. Annual contract value: EUR 1,200,000. "
        "GDP and Arzneimittelgesetz compliance required.",
        "DOC-LEGAL-001",
        "legal",
        2,
        "pharmacorp-contract.txt",
    ),
    (
        "FreshFoods Logistics Agreement CTR-2024-002. Refrigerated transport "
        "of fresh produce. 12 fixed routes, 180 retail locations. "
        "Delivery windows: 05:00-09:00. Penalty: EUR 200 per late store. "
        "Temperature range: 2-6 degrees fresh, -18 degrees frozen. "
        "Annual value: EUR 650,000.",
        "DOC-LEGAL-002",
        "legal",
        2,
        "freshfoods-contract.txt",
    ),
]


@pytest.fixture(scope="module")
async def qdrant():
    """Qdrant client for the entire test module."""
    client = AsyncQdrantClient(host="localhost", port=6333, check_compatibility=False)
    yield client
    await client.close()


@pytest.fixture(scope="module")
async def embeddings():
    """Real Azure OpenAI embeddings."""
    return get_embeddings()


@pytest.fixture(scope="module")
async def seeded_collection(qdrant, embeddings):
    """Seed Qdrant with real embeddings. Runs once per module."""
    # Clean slate
    if await qdrant.collection_exists(COLLECTION_NAME):
        await qdrant.delete_collection(COLLECTION_NAME)

    await ensure_collection(qdrant)

    for text, doc_id, dept, clearance, source in DOCS:
        result = await ingest_document(
            text=text,
            document_id=doc_id,
            department_id=dept,
            clearance_level=clearance,
            source_file=source,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_documents,
            chunk_size=400,
            chunk_overlap=50,
        )
        print(f"  Ingested {doc_id}: {result.chunks_created} chunks")

    # Return qdrant client + embeddings for use in tests
    yield qdrant, embeddings

    # Cleanup
    await qdrant.delete_collection(COLLECTION_NAME)


class TestLiveRBACFiltering:
    """RBAC filtering with real embeddings — the core security guarantee."""

    async def test_warehouse_worker_cannot_see_ceo_compensation(self, seeded_collection):
        """Max Weber searches 'compensation' — MUST return zero results."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="CEO compensation salary bonus",
            user=WAREHOUSE_WORKER,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-HR-002" not in doc_ids, (
            "SECURITY FAILURE: Warehouse worker saw CEO compensation!"
        )
        # Should also not see HR-only docs
        assert "DOC-HR-004" not in doc_ids, (
            "SECURITY FAILURE: Warehouse worker saw termination procedures!"
        )

    async def test_hr_director_sees_termination_not_ceo_comp(self, seeded_collection):
        """Katrin Fischer searches HR topics — sees clearance 3, not clearance 4."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="employee termination severance notice period",
            user=HR_DIRECTOR,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-HR-004" in doc_ids, (
            "HR director should see termination procedures (clearance 3)"
        )
        assert "DOC-HR-002" not in doc_ids, (
            "SECURITY FAILURE: HR director (clearance 3) saw CEO compensation (clearance 4)!"
        )

    async def test_ceo_sees_compensation(self, seeded_collection):
        """Eva Richter searches 'compensation' — MUST see DOC-HR-002."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="CEO compensation salary bonus stock options",
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-HR-002" in doc_ids, "CEO should see executive compensation document"

    async def test_ceo_sees_all_departments(self, seeded_collection):
        """CEO can access docs from every department."""
        qdrant, embeddings = seeded_collection

        # Search for legal contract
        results = await hybrid_search(
            query="PharmaCorp contract penalty delivery",
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-LEGAL-001" in doc_ids, "CEO should see legal contracts"


class TestLiveSemanticSearch:
    """Verify semantic search quality with real embeddings."""

    async def test_semantic_match_quality_standards(self, seeded_collection):
        """'quality standards' should find the ISO 9001 manual via meaning."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="quality standards inspection requirements",
            user=WAREHOUSE_WORKER,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=5,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-SAFETY-001" in doc_ids, (
            "Semantic search should find ISO 9001 quality manual for 'quality standards'"
        )

    async def test_semantic_match_driving_regulations(self, seeded_collection):
        """'driving hours rules' should find the driver safety protocol."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="how many hours can a driver work per day",
            user=WAREHOUSE_WORKER,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=5,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-HR-003" in doc_ids, (
            "Semantic search should find driver safety for driving hours question"
        )

    async def test_contract_search_by_company_name(self, seeded_collection):
        """'PharmaCorp' should find CTR-2024-001 via keyword/semantic match."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="PharmaCorp delivery penalties",
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=5,
        )

        doc_ids = {r.document_id for r in results}
        assert "DOC-LEGAL-001" in doc_ids, "Should find PharmaCorp contract by company name"

    async def test_temperature_search_cross_documents(self, seeded_collection):
        """'temperature requirements' should find docs mentioning temperature."""
        qdrant, embeddings = seeded_collection

        results = await hybrid_search(
            query="temperature requirements cold chain pharmaceutical",
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )

        doc_ids = {r.document_id for r in results}
        # PharmaCorp contract and driver safety both mention temperature
        temp_docs = doc_ids & {"DOC-LEGAL-001", "DOC-HR-003", "DOC-LEGAL-002"}
        assert len(temp_docs) >= 1, (
            f"Temperature search should find temperature-related docs, got: {doc_ids}"
        )


class TestLiveSearchDifferentUsersComparison:
    """The 'aha' moment: same query, different users, different results."""

    async def test_same_query_different_results(self, seeded_collection):
        """Same search term, 3 users, progressively more results."""
        qdrant, embeddings = seeded_collection
        query = "salary compensation termination employee"

        # Warehouse worker — clearance 1, warehouse only
        r_max = await hybrid_search(
            query=query,
            user=WAREHOUSE_WORKER,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )
        ids_max = {r.document_id for r in r_max}

        # HR director — clearance 3, hr + management
        r_katrin = await hybrid_search(
            query=query,
            user=HR_DIRECTOR,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )
        ids_katrin = {r.document_id for r in r_katrin}

        # CEO — clearance 4, all departments
        r_eva = await hybrid_search(
            query=query,
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embeddings.aembed_query,
            top_k=10,
        )
        ids_eva = {r.document_id for r in r_eva}

        # Key assertions:
        # 1. CEO sees strictly more than or equal to HR director
        assert ids_katrin <= ids_eva, (
            f"CEO should see everything HR sees. HR: {ids_katrin}, CEO: {ids_eva}"
        )

        # 2. Warehouse worker should NOT see HR-only docs
        assert "DOC-HR-002" not in ids_max, "Warehouse worker must not see CEO comp"
        assert "DOC-HR-004" not in ids_max, "Warehouse worker must not see termination procs"

        # 3. CEO should see the executive compensation
        assert "DOC-HR-002" in ids_eva, "CEO must see executive compensation"

        print(f"\n  Max (clearance 1, warehouse): {sorted(ids_max)}")
        print(f"  Katrin (clearance 3, hr+mgmt): {sorted(ids_katrin)}")
        print(f"  Eva (clearance 4, all):        {sorted(ids_eva)}")
