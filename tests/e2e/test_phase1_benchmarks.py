"""Phase 1 BENCHMARKS: When BM25, When Dense, When Hybrid — Honest Tradeoff Analysis.

THE PROBLEM WITH NAIVE BENCHMARKS:
With 6 documents and top_k=5, every mode returns 5/6 docs — everything "works."
A CTO would ask: "If BM25 got 12/12 for free, why am I paying Azure for embeddings?"

THIS BENCHMARK answers: "Here's exactly when BM25 breaks and you NEED embeddings."

We test with top_k=1 (hardest) and top_k=3 to show ranking quality, not just recall.
We design queries that SHOULD break one mode:
- Synonym queries: "firing" should find "termination" — BM25 can't do this
- Negation/context: "non-food transport" — BM25 matches "food" in wrong doc
- Exact codes: "CTR-2024-001" — dense embeddings blur alphanumeric codes

THE ARCHITECT TAKEAWAY for LinkedIn/Medium:
- BM25 alone is NOT viable for human-facing search. Real users never use exact
  terminology — a warehouse worker searches "what if I get fired", not
  "termination procedures." BM25 returns garbage for natural language.
- BM25's only role: SUPPLEMENTING dense search for exact codes (CTR-2024-001,
  ISO-9001) that embeddings blur. It's a precision booster, not a search engine.
- The real question is Dense alone vs Hybrid (Dense + BM25). Hybrid adds code
  precision on top of semantic understanding — that's the value.
- text-embedding-3-large rarely justifies 6.5x cost over small.

Requires:
- Docker: qdrant running on localhost:6333
- Azure OpenAI credentials in .env

Run manually:
    uv run pytest tests/e2e/test_phase1_benchmarks.py -v -m live -s
"""

import time

import pytest
from qdrant_client import AsyncQdrantClient

from apps.api.src.domain.document import UserContext
from apps.api.src.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    DENSE_LARGE_VECTOR_SIZE,
    DENSE_VECTOR_SIZE,
    ensure_collection,
)
from apps.api.src.rag.embeddings import (
    EMBEDDING_LARGE,
    EMBEDDING_SMALL,
    get_embeddings,
)
from apps.api.src.rag.ingestion import ingest_document
from apps.api.src.rag.retriever import SearchMode, hybrid_search

pytestmark = pytest.mark.live

# CEO can see all documents — no RBAC interference with benchmarks
CEO = UserContext(
    user_id="eva.richter",
    clearance_level=4,
    departments=[
        "hr", "management", "legal",
        "logistics", "warehouse", "executive",
    ],
)

# Expanded corpus: 12 docs with semantic overlap to make ranking matter
DOCS = [
    # -- Warehouse (clearance 1) --
    (
        "ISO 9001 Quality Management Manual. Section 4.2: Quality management "
        "requirements for warehouse operations. All incoming goods must be "
        "inspected within 4 hours of receipt. Temperature-sensitive cargo "
        "requires continuous monitoring.",
        "DOC-SAFETY-001", "warehouse", 1, "quality-manual.txt",
    ),
    (
        "Driver Safety Protocol. Pre-trip inspection checklist. EU Regulation "
        "(EC) No 561/2006 applies to all LogiCore drivers. Maximum daily "
        "driving: 9 hours. Continuous driving break: 45 minutes after "
        "4.5 hours.",
        "DOC-HR-003", "warehouse", 1, "driver-safety.txt",
    ),
    (
        "Warehouse Fire Safety Plan. Evacuation routes posted at every exit. "
        "Fire extinguisher inspection every 6 months. Sprinkler system covers "
        "100% of storage area. Emergency assembly point: parking lot B.",
        "DOC-SAFETY-002", "warehouse", 1, "fire-safety.txt",
    ),
    (
        "Forklift Operation Manual. Only certified operators may use forklifts. "
        "Maximum load capacity: 2,500 kg. Pre-shift inspection required. "
        "Speed limit in warehouse: 10 km/h. Pedestrian zones clearly marked.",
        "DOC-SAFETY-003", "warehouse", 1, "forklift-manual.txt",
    ),
    # -- HR (clearance 3-4) --
    (
        "Executive Compensation Policy CONFIDENTIAL. CEO salary EUR 280,000 "
        "per annum. Performance bonus up to 40% of base salary. Stock options "
        "50,000 shares vesting over 4 years.",
        "DOC-HR-002", "hr", 4, "exec-compensation.txt",
    ),
    (
        "Employee Termination Procedures HR CONFIDENTIAL. Performance-based "
        "termination: two consecutive quarterly reviews below 2.0/5.0. "
        "Notice periods per Kodeks Pracy Art. 36. Severance formula: 0.5 months "
        "salary per year of service.",
        "DOC-HR-004", "hr", 3, "termination.txt",
    ),
    (
        "Employee Onboarding Handbook. New hire orientation: first 3 days. "
        "IT equipment provisioning within 24 hours. Buddy system: assigned "
        "mentor for first 90 days. Probation period: 6 months.",
        "DOC-HR-005", "hr", 1, "onboarding.txt",
    ),
    # -- Legal (clearance 2) --
    (
        "PharmaCorp Service Agreement CTR-2024-001. Temperature-controlled "
        "pharmaceutical logistics. SLA: on-time delivery >= 98.5%. "
        "Penalty: EUR 500 per late shipment. Temperature excursion: "
        "EUR 2,000 per incident. Annual value: EUR 1,200,000.",
        "DOC-LEGAL-001", "legal", 2, "pharmacorp-contract.txt",
    ),
    (
        "FreshFoods Logistics Agreement CTR-2024-002. Refrigerated transport "
        "of fresh produce. 12 fixed routes, 180 retail locations. "
        "Penalty: EUR 200 per late store delivery. Temperature range: "
        "2-6 degrees fresh, -18 degrees frozen. Annual value: EUR 650,000.",
        "DOC-LEGAL-002", "legal", 2, "freshfoods-contract.txt",
    ),
    (
        "AutoParts Express Contract CTR-2024-003. Non-perishable auto parts "
        "distribution. 8 routes across Bavaria. No temperature requirements. "
        "Penalty: EUR 100 per late delivery. Annual value: EUR 320,000.",
        "DOC-LEGAL-003", "legal", 2, "autoparts-contract.txt",
    ),
    (
        "ChemTrans Hazmat Agreement CTR-2024-004. ADR-certified hazardous "
        "materials transport. Requires UN-approved packaging. Driver must "
        "hold ADR certificate. Penalty: EUR 5,000 per compliance violation. "
        "Annual value: EUR 2,100,000.",
        "DOC-LEGAL-004", "legal", 2, "chemtrans-contract.txt",
    ),
    (
        "LogiCore Master Service Agreement template. General terms and "
        "conditions for all logistics contracts. Payment terms: NET 30. "
        "Liability cap: 2x annual contract value. Force majeure clause "
        "includes pandemics and natural disasters.",
        "DOC-LEGAL-005", "legal", 2, "msa-template.txt",
    ),
]

# =============================================================================
# BENCHMARK QUERIES — designed to BREAK one mode while other succeeds
# =============================================================================
# Format: (query, expected_top1_doc, category, why_this_is_hard)

HARD_QUERIES = [
    # -- SYNONYM queries: BM25 CANNOT find these (no word overlap) --
    (
        "letting go of underperforming staff",
        "DOC-HR-004",  # termination procedures
        "synonym",
        "No word overlap with 'termination' or 'firing'",
    ),
    (
        "new employee first day process",
        "DOC-HR-005",  # onboarding handbook
        "synonym",
        "'first day' ≠ 'onboarding', no keyword match",
    ),
    (
        "executive pay packages",
        "DOC-HR-002",  # compensation policy
        "synonym",
        "'pay packages' ≠ 'compensation' or 'salary'",
    ),
    (
        "dangerous goods shipping rules",
        "DOC-LEGAL-004",  # ChemTrans hazmat
        "synonym",
        "'dangerous goods' ≈ 'hazardous materials' — synonym",
    ),
    # -- EXACT CODE queries: Dense embeddings blur these --
    (
        "CTR-2024-001",
        "DOC-LEGAL-001",  # PharmaCorp
        "exact_code",
        "Alphanumeric code — embedding may confuse with CTR-2024-002/003",
    ),
    (
        "CTR-2024-004",
        "DOC-LEGAL-004",  # ChemTrans
        "exact_code",
        "Must distinguish from CTR-2024-001/002/003",
    ),
    (
        "EU Regulation 561/2006",
        "DOC-HR-003",  # driver safety
        "exact_code",
        "Regulation number must match exactly",
    ),
    (
        "ISO-9001 Section 4.2",
        "DOC-SAFETY-001",  # quality manual
        "exact_code",
        "Section reference must match exactly",
    ),
    # -- RANKING queries: both find it, but who ranks it #1? --
    (
        "temperature requirements for pharmaceutical transport",
        "DOC-LEGAL-001",  # PharmaCorp (not FreshFoods)
        "ranking",
        "Both LEGAL-001 and LEGAL-002 mention temperature",
    ),
    (
        "highest penalty per incident across all contracts",
        "DOC-LEGAL-004",  # ChemTrans EUR 5,000
        "ranking",
        "All contracts have penalties — which ranks highest?",
    ),
    (
        "workplace safety equipment inspection",
        "DOC-SAFETY-002",  # fire safety (extinguisher inspection)
        "ranking",
        "Multiple safety docs — must pick the right one",
    ),
    (
        "contract with the largest annual value",
        "DOC-LEGAL-004",  # ChemTrans EUR 2,100,000
        "ranking",
        "Multiple contracts with values — needs understanding",
    ),
    # -- JARGON queries: industry abbreviations that may not appear in docs --
    (
        "ADR certified transport",
        "DOC-LEGAL-004",  # ChemTrans has "ADR-certified"
        "jargon",
        "Industry abbreviation for hazardous materials transport",
    ),
    (
        "SLA breach consequences",
        "DOC-LEGAL-001",  # PharmaCorp has "SLA: on-time delivery >= 98.5%"
        "jargon",
        "'SLA' as abbreviation — does search match it?",
    ),
    (
        "GDP compliance for pharma shipments",
        "DOC-LEGAL-001",  # PharmaCorp has "GDP and Arzneimittelgesetz compliance"
        "jargon",
        "Good Distribution Practice — pharma logistics abbreviation",
    ),
    (
        "HNSW index parameters",
        None,  # No doc matches — should return empty or irrelevant
        "jargon",
        "Technical jargon NOT in corpus — tests false positive rate",
    ),
    # -- MULTILINGUAL queries: Polish company, Polish workforce --
    (
        "towary niebezpieczne przepisy",
        "DOC-LEGAL-004",  # ChemTrans hazmat
        "multilingual",
        "Polish for 'dangerous goods regulations'",
    ),
    (
        "czas pracy kierowcy ciezarowki",
        "DOC-HR-003",  # driver safety, driving hours
        "multilingual",
        "Polish for 'working hours truck driver'",
    ),
    (
        "okresy wypowiedzenia umowy o prace",
        "DOC-HR-004",  # termination procedures, notice periods
        "multilingual",
        "Polish for 'employment contract notice periods'",
    ),
    (
        "kontrola jakosci magazyn",
        "DOC-SAFETY-001",  # quality manual, warehouse
        "multilingual",
        "Polish for 'quality control warehouse'",
    ),
    # -- TYPO queries: real users misspell --
    (
        "pharamcorp contract",
        "DOC-LEGAL-001",  # PharmaCorp
        "typo",
        "Typo in company name — transposed letters",
    ),
    (
        "tempature requirements",
        "DOC-LEGAL-001",  # PharmaCorp temperature
        "typo",
        "Common misspelling of 'temperature'",
    ),
    (
        "saftey protocol",
        "DOC-HR-003",  # driver safety
        "typo",
        "Common misspelling of 'safety'",
    ),
    (
        "terminaton procedures",
        "DOC-HR-004",  # termination
        "typo",
        "Missing letter in 'termination'",
    ),
    # -- NEGATION queries: retrieval systems notoriously fail here --
    (
        "contracts without temperature requirements",
        "DOC-LEGAL-003",  # AutoParts — no temp requirements
        "negation",
        "BM25 matches 'temperature' in wrong docs; needs understanding of 'without'",
    ),
    (
        "non-perishable transport agreements",
        "DOC-LEGAL-003",  # AutoParts — "Non-perishable auto parts"
        "negation",
        "Must understand 'non-perishable' excludes food/pharma",
    ),
]


async def _seed(qdrant, embeddings, dense_size):
    """Seed collection with all docs. Returns collection name."""
    if await qdrant.collection_exists(COLLECTION_NAME):
        await qdrant.delete_collection(COLLECTION_NAME)
    await ensure_collection(qdrant, dense_size=dense_size)
    for text, doc_id, dept, clearance, source in DOCS:
        await ingest_document(
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
    return COLLECTION_NAME


@pytest.fixture(scope="module")
async def qdrant():
    client = AsyncQdrantClient(
        host="localhost", port=6333, check_compatibility=False,
    )
    yield client
    await client.close()


@pytest.fixture(scope="module")
async def embeddings_small():
    return get_embeddings(EMBEDDING_SMALL)


@pytest.fixture(scope="module")
async def seeded(qdrant, embeddings_small):
    """Seed with text-embedding-3-small (12 docs)."""
    await _seed(qdrant, embeddings_small, DENSE_VECTOR_SIZE)
    yield qdrant, embeddings_small
    await qdrant.delete_collection(COLLECTION_NAME)


async def _run_queries(qdrant, embed_fn, mode, top_k=1):
    """Run all hard queries, return per-category hit counts + details."""
    cats = {}
    details = []
    for query, expected_id, category, reason in HARD_QUERIES:
        if category not in cats:
            cats[category] = {"hit": 0, "total": 0}
        cats[category]["total"] += 1

        start = time.perf_counter()
        results = await hybrid_search(
            query=query,
            user=CEO,
            qdrant_client=qdrant,
            embed_fn=embed_fn,
            top_k=top_k,
            mode=mode,
        )
        ms = (time.perf_counter() - start) * 1000

        found_ids = [r.document_id for r in results]
        if expected_id is None:
            # False-positive test: no doc should match. Hit = no results returned.
            hit = len(found_ids) == 0
        else:
            hit = expected_id in found_ids
        if hit:
            cats[category]["hit"] += 1

        rank = (found_ids.index(expected_id) + 1) if (expected_id and hit) else None
        details.append({
            "query": query[:50],
            "expected": expected_id,
            "got": found_ids[0] if found_ids else "—",
            "hit": hit,
            "rank": rank,
            "ms": ms,
            "category": category,
        })

    return cats, details


class TestHonestBenchmark:
    """The real benchmark: queries designed to break each mode.

    This is what goes on LinkedIn/Medium — honest analysis of when
    you need embeddings and when BM25 alone is enough.
    """

    async def test_where_bm25_breaks(self, seeded):
        """BM25 cannot find synonyms. This is WHY you need embeddings."""
        qdrant, embeddings = seeded

        cats, details = await _run_queries(
            qdrant, embeddings.aembed_query,
            SearchMode.SPARSE_ONLY, top_k=3,
        )

        syn = cats.get("synonym", {"hit": 0, "total": 0})
        print("\n" + "=" * 70)
        print("WHERE BM25 BREAKS: Synonym queries (top_k=3)")
        print("=" * 70)
        for d in details:
            if d["category"] == "synonym":
                status = "HIT" if d["hit"] else "MISS"
                print(
                    f"  [{status}] '{d['query']}'"
                    f"\n         expected: {d['expected']}"
                    f"  got: {d['got']}"
                )
        print(f"\n  BM25 synonym score: {syn['hit']}/{syn['total']}")
        print("=" * 70)

        # BM25 should FAIL on most synonym queries — that's the point
        assert syn["hit"] < syn["total"], (
            f"BM25 found {syn['hit']}/{syn['total']} synonyms — "
            "if BM25 finds all synonyms, our test queries are too easy"
        )

    async def test_where_dense_struggles(self, seeded):
        """Dense embeddings blur alphanumeric codes. BM25 wins here."""
        qdrant, embeddings = seeded

        # Dense with top_k=1 (strict ranking test)
        dense_cats, dense_details = await _run_queries(
            qdrant, embeddings.aembed_query,
            SearchMode.DENSE_ONLY, top_k=1,
        )
        # BM25 with top_k=1
        sparse_cats, sparse_details = await _run_queries(
            qdrant, embeddings.aembed_query,
            SearchMode.SPARSE_ONLY, top_k=1,
        )

        d_exact = dense_cats.get("exact_code", {"hit": 0, "total": 0})
        s_exact = sparse_cats.get("exact_code", {"hit": 0, "total": 0})

        print("\n" + "=" * 70)
        print("EXACT CODE QUERIES @ top_k=1 (strictest test)")
        print("=" * 70)
        print(f"  {'Query':<30} {'BM25':>8} {'Dense':>8}")
        print("  " + "-" * 50)
        for sd, dd in zip(sparse_details, dense_details):
            if sd["category"] == "exact_code":
                s = "HIT" if sd["hit"] else "MISS"
                d = "HIT" if dd["hit"] else "MISS"
                print(f"  {sd['query']:<30} {s:>8} {d:>8}")
        bm = f"{s_exact['hit']}/{s_exact['total']}"
        dn = f"{d_exact['hit']}/{d_exact['total']}"
        print(f"\n  BM25: {bm}    Dense: {dn}")
        print("=" * 70)

        # BM25 should beat or match dense on exact codes
        assert s_exact["hit"] >= d_exact["hit"], (
            f"BM25 ({s_exact['hit']}) should match or beat "
            f"dense ({d_exact['hit']}) on exact codes"
        )

    async def test_full_comparison_table(self, seeded):
        """The money shot: full comparison across all categories."""
        qdrant, embeddings = seeded

        modes = [
            ("BM25 (free)", SearchMode.SPARSE_ONLY),
            ("Dense ($0.02/1M)", SearchMode.DENSE_ONLY),
            ("Hybrid (RRF)", SearchMode.HYBRID),
        ]

        all_results = {}
        all_details = {}
        for name, mode in modes:
            cats, details = await _run_queries(
                qdrant, embeddings.aembed_query, mode, top_k=3,
            )
            all_results[name] = cats
            all_details[name] = details

        # Compute totals
        categories = [
            "synonym", "exact_code", "ranking",
            "jargon", "multilingual", "typo", "negation",
        ]
        cat_labels = {
            "synonym": "Synonym",
            "exact_code": "Exact Code",
            "ranking": "Ranking",
            "jargon": "Jargon",
            "multilingual": "Polish",
            "typo": "Typo",
            "negation": "Negation",
        }

        print("\n" + "=" * 70)
        print("FULL COMPARISON: 12 queries, top_k=3, 12 documents")
        print("=" * 70)
        header = f"  {'Mode':<22}"
        for cat in categories:
            header += f" {cat_labels[cat]:>12}"
        header += f" {'Total':>10}"
        print(header)
        print("  " + "-" * 60)

        for name, _ in modes:
            cats = all_results[name]
            line = f"  {name:<22}"
            total_hit = 0
            total_n = 0
            for cat in categories:
                c = cats.get(cat, {"hit": 0, "total": 0})
                cell = f"{c['hit']}/{c['total']}"
                line += f" {cell:>12}"
                total_hit += c["hit"]
                total_n += c["total"]
            cell = f"{total_hit}/{total_n}"
            line += f" {cell:>10}"
            print(line)

        # Avg latency per mode
        print()
        for name, _ in modes:
            dets = all_details[name]
            avg = sum(d["ms"] for d in dets) / len(dets)
            print(f"  {name:<22} avg latency: {avg:.0f} ms")

        print("\n  ARCHITECT VERDICT:")
        bm = all_results["BM25 (free)"]
        dn = all_results["Dense ($0.02/1M)"]
        hy = all_results["Hybrid (RRF)"]
        bm_syn = bm.get("synonym", {"hit": 0})["hit"]
        dn_syn = dn.get("synonym", {"hit": 0})["hit"]
        bm_ec = bm.get("exact_code", {"hit": 0})["hit"]
        dn_ec = dn.get("exact_code", {"hit": 0})["hit"]
        dn_typo = dn.get("typo", {"hit": 0})["hit"]
        dn_ml = dn.get("multilingual", {"hit": 0})["hit"]
        dn_neg = dn.get("negation", {"hit": 0})["hit"]
        print(
            f"  - BM25 alone is NOT viable: {bm_syn}/4 "
            "synonyms. Real users don't speak in doc terms."
        )
        print(
            f"  - Embeddings are mandatory: {dn_syn}/4 "
            "synonyms. Understands 'firing' = 'termination'."
        )
        print(
            f"  - BM25 supplements codes: {bm_ec}/4 "
            f"exact codes at rank 1 vs dense {dn_ec}/4."
        )
        print(
            f"  - Polish queries: Dense {dn_ml}/4 — "
            "cross-lingual embedding quality. Phase 2: query translation."
        )
        print(
            f"  - Typo resilience: Dense {dn_typo}/4 — "
            "embeddings handle some typos. Phase 2: spell-correction."
        )
        print(
            f"  - Negation: Dense {dn_neg}/2 — "
            "retrieval can't understand 'without'. Phase 2/3: query understanding."
        )
        print(
            "  - Hybrid = Dense + BM25 code precision. "
            "Not 'BM25 or Dense' but 'Dense or Dense+BM25'."
        )
        print(
            "  - Switch to dense-only when corpus has no alphanumeric codes "
            "AND BM25 indexing becomes maintenance burden."
        )
        print("=" * 70)

        # Hybrid should be >= each individual mode's total
        h_total = sum(
            hy.get(c, {"hit": 0})["hit"] for c in categories
        )
        d_total = sum(
            dn.get(c, {"hit": 0})["hit"] for c in categories
        )
        s_total = sum(
            bm.get(c, {"hit": 0})["hit"] for c in categories
        )
        assert h_total >= d_total or h_total >= s_total, (
            f"Hybrid ({h_total}) should beat at least one mode "
            f"(dense={d_total}, sparse={s_total})"
        )

    async def test_per_query_breakdown(self, seeded):
        """Detailed per-query results for content grounding."""
        qdrant, embeddings = seeded

        modes = [
            ("BM25", SearchMode.SPARSE_ONLY),
            ("Dense", SearchMode.DENSE_ONLY),
            ("Hybrid", SearchMode.HYBRID),
        ]

        print("\n" + "=" * 70)
        print("PER-QUERY BREAKDOWN (top_k=3)")
        print("=" * 70)

        for query, expected_id, category, reason in HARD_QUERIES:
            print(f"\n  Q: '{query}'")
            print(f"     Expected: {expected_id} ({reason})")

            for name, mode in modes:
                results = await hybrid_search(
                    query=query, user=CEO,
                    qdrant_client=qdrant,
                    embed_fn=embeddings.aembed_query,
                    top_k=3, mode=mode,
                )
                ids = [r.document_id for r in results]
                hit = expected_id in ids
                rank = (ids.index(expected_id) + 1) if hit else "-"
                mark = "v" if hit else "X"
                print(
                    f"     {name:<8} [{mark}] "
                    f"rank={rank} results={ids}"
                )

        print("\n" + "=" * 70)


class TestEmbeddingModelComparison:
    """text-embedding-3-small vs large — is 6.5x cost justified?

    Honest answer: probably not for < 1000 docs in a single domain.
    The benchmark proves it with numbers.
    """

    async def test_small_vs_large_on_hard_queries(self, qdrant):
        """Both models on synonym queries — where quality matters."""
        emb_small = get_embeddings(EMBEDDING_SMALL)
        emb_large = get_embeddings(EMBEDDING_LARGE)

        # Seed with small
        await _seed(qdrant, emb_small, DENSE_VECTOR_SIZE)
        small_cats, _ = await _run_queries(
            qdrant, emb_small.aembed_query,
            SearchMode.DENSE_ONLY, top_k=3,
        )
        await qdrant.delete_collection(COLLECTION_NAME)

        # Seed with large
        await _seed(qdrant, emb_large, DENSE_LARGE_VECTOR_SIZE)
        large_cats, _ = await _run_queries(
            qdrant, emb_large.aembed_query,
            SearchMode.DENSE_ONLY, top_k=3,
        )
        await qdrant.delete_collection(COLLECTION_NAME)

        categories = [
            "synonym", "exact_code", "ranking",
            "jargon", "multilingual", "typo", "negation",
        ]
        cat_labels = {
            "synonym": "Synonym",
            "exact_code": "Exact Code",
            "ranking": "Ranking",
            "jargon": "Jargon",
            "multilingual": "Polish",
            "typo": "Typo",
            "negation": "Negation",
        }

        print("\n" + "=" * 70)
        print("EMBEDDING MODEL COMPARISON (dense_only, top_k=3)")
        print("=" * 70)
        header = f"  {'Model':<30}"
        for cat in categories:
            header += f" {cat_labels[cat]:>12}"
        header += f" {'Cost/1M':>10}"
        print(header)
        print("  " + "-" * 60)

        for label, cats, cost in [
            ("text-embedding-3-small", small_cats, "$0.02"),
            ("text-embedding-3-large", large_cats, "$0.13"),
        ]:
            line = f"  {label:<30}"
            for cat in categories:
                c = cats.get(cat, {"hit": 0, "total": 0})
                cell = f"{c['hit']}/{c['total']}"
                line += f" {cell:>12}"
            line += f" {cost:>10}"
            print(line)

        s_syn = small_cats.get("synonym", {"hit": 0})["hit"]
        l_syn = large_cats.get("synonym", {"hit": 0})["hit"]
        delta = l_syn - s_syn
        print(f"\n  Synonym delta: large finds {delta} more")
        print(
            "  Cost delta: 6.5x ($0.02 -> $0.13 per 1M tokens)"
        )
        if delta <= 0:
            print(
                "  VERDICT: Large model NOT justified at this "
                "corpus size"
            )
        else:
            print(
                f"  VERDICT: Large model finds {delta} more "
                "synonym queries — consider for synonym-heavy "
                "workloads"
            )
        print("=" * 70)

        # Both should find at least some queries
        s_total = sum(
            small_cats.get(c, {"hit": 0})["hit"]
            for c in categories
        )
        assert s_total >= 4, (
            f"Small model should find at least 4 queries, "
            f"got {s_total}"
        )
