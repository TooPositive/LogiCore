"""Re-ranking benchmark: Compare retrieval with and without cross-encoder re-ranking.

Tests multiple cross-encoder models at multiple corpus scales to find:
1. Which model works for multilingual queries (Polish, typos)?
2. At what corpus scale does re-ranking become beneficial?

Usage:
    python scripts/benchmark_reranking.py                    # 12-doc corpus
    python scripts/benchmark_reranking.py --scale 100        # 100-doc expanded corpus
    python scripts/benchmark_reranking.py --scale 100 --models all  # all models at 100 docs

Requires: Qdrant on localhost:6333, Azure OpenAI credentials in .env,
          sentence-transformers installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.config.settings import settings  # noqa: F401
from apps.api.src.domain.document import UserContext
from apps.api.src.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    DENSE_VECTOR_SIZE,
    ensure_collection,
)
from apps.api.src.rag.embeddings import get_embeddings
from apps.api.src.rag.ingestion import ingest_document
from apps.api.src.rag.reranker import LocalCrossEncoderReranker, NoOpReranker
from apps.api.src.rag.retriever import SearchMode, hybrid_search
from tests.evaluation.corpus import CORPUS
from tests.evaluation.ground_truth import (
    GROUND_TRUTH,
    get_all_categories,
    get_queries_by_category,
)
from tests.evaluation.metrics import (
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
)


# ---------------------------------------------------------------------------
# Corpus expansion: generate semantically similar documents at scale
# ---------------------------------------------------------------------------

COMPANY_NAMES = [
    "MediLog", "PharmaRoute", "BioFreight", "ColdChain Express",
    "EuroMed Transport", "HealthLine Logistics", "VaxShip",
    "NordPharma", "WisłaFresh", "OdraCargo", "MazurLog",
    "HansaTransport", "TatraFreight", "WarszawaLogistik",
    "KrakówCargo", "GdańskTransit", "ŚląskHaul", "PoznańExpress",
    "WrocławShip", "ŁódźFreight", "SzczecCargo", "BydgoLogistik",
]

CONTRACT_TEMPLATES = [
    {
        "type": "pharma",
        "department": "legal",
        "clearance": 2,
        "template": (
            "SERVICE AGREEMENT {ctr}\n"
            "Between: {company} ({country}) and LogiCore Sp. z o.o.\n"
            "Effective: {start} — {end}\n\n"
            "1. Scope of Services\n"
            "LogiCore shall provide temperature-controlled pharmaceutical "
            "logistics for {company}, covering {routes} routes across {regions}. "
            "All shipments require GDP-compliant cold chain from collection "
            "to final delivery at {destinations}.\n\n"
            "2. Service Level Agreement\n"
            "SLA: on-time delivery >= {sla}%. On-time defined as within "
            "{window}-hour delivery window. Monthly performance reports "
            "due by 5th business day.\n\n"
            "3. Penalty Clauses\n"
            "Late shipment penalty: EUR {late_pen} per incident. "
            "Temperature excursion (outside {temp_range}): EUR {temp_pen} "
            "per incident. Documentation failure: EUR {doc_pen} per missing "
            "record. Annual penalty cap: EUR {pen_cap}.\n\n"
            "4. Financial Terms\n"
            "Annual contract value: EUR {annual_value}. Payment: NET {net} "
            "days. Price review annually in Q4.\n\n"
            "5. Compliance\n"
            "Vehicles must maintain GDP certification. Drivers complete annual "
            "cold-chain training. Temperature loggers calibrated quarterly. "
            "{extra_compliance}\n\n"
            "6. Termination\n"
            "{notice} months written notice. Immediate termination for "
            "{breach_count}+ SLA failures in any rolling 3-month period."
        ),
    },
    {
        "type": "hazmat",
        "department": "legal",
        "clearance": 2,
        "template": (
            "HAZARDOUS MATERIALS AGREEMENT {ctr}\n"
            "Between: {company} ({country}) and LogiCore Sp. z o.o.\n"
            "Effective: {start} — {end}\n\n"
            "1. Scope\n"
            "ADR-certified hazardous materials transport for {company}. "
            "Cargo classes: {cargo_classes}. Routes: {routes} routes "
            "across {regions}.\n\n"
            "2. Safety Requirements\n"
            "UN-approved packaging verified by shipper. Every driver must "
            "hold valid ADR certificate. Vehicles equipped with ADR placarding, "
            "fire extinguishers, spill containment, {extra_safety}.\n\n"
            "3. Penalties\n"
            "Penalty: EUR {violation_pen} per compliance violation including "
            "expired ADR certificate, missing placarding, unsealed containment. "
            "Regulatory fine passthrough: LogiCore bears {fine_pct}% of fines "
            "from DGSA inspection.\n\n"
            "4. Financial Terms\n"
            "Annual value: EUR {annual_value}. Payment: NET {net} days. "
            "Fuel surcharge adjusted monthly per ADAC diesel index.\n\n"
            "5. Emergency\n"
            "24/7 emergency hotline. Spill response within {response_min} "
            "minutes for routes within {response_km}km of depot. "
            "Quarterly joint emergency drill with {company}.\n\n"
            "6. Termination\n"
            "{notice} days written notice. Immediate termination for "
            "environmental contamination."
        ),
    },
    {
        "type": "fresh",
        "department": "legal",
        "clearance": 2,
        "template": (
            "LOGISTICS SERVICE AGREEMENT {ctr}\n"
            "Between: {company} ({country}) and LogiCore Sp. z o.o.\n"
            "Effective: {start} — {end}\n\n"
            "1. Scope\n"
            "Refrigerated transport of {product_type} for {company}. "
            "{routes} fixed routes serving {locations} retail locations "
            "across {regions}.\n\n"
            "2. Temperature Requirements\n"
            "Fresh products: {fresh_temp} degrees. Frozen products: "
            "{frozen_temp} degrees. Continuous monitoring via IoT sensors. "
            "Excursion threshold: {excursion_min} minutes.\n\n"
            "3. Penalties\n"
            "Late delivery: EUR {late_pen} per store. Temperature excursion: "
            "EUR {temp_pen} per incident. Product spoilage due to LogiCore "
            "fault: full replacement cost + EUR {spoilage_pen} handling fee.\n\n"
            "4. Financial Terms\n"
            "Annual value: EUR {annual_value}. Payment: NET {net} days. "
            "Seasonal volume adjustments in Q4 (holiday peak).\n\n"
            "5. Quality Standards\n"
            "HACCP certification required. {extra_quality}\n\n"
            "6. Termination\n"
            "{notice} months notice. Immediate for {breach_count}+ "
            "spoilage incidents in any calendar month."
        ),
    },
    {
        "type": "general",
        "department": "legal",
        "clearance": 2,
        "template": (
            "TRANSPORT SERVICE CONTRACT {ctr}\n"
            "Between: {company} ({country}) and LogiCore Sp. z o.o.\n"
            "Effective: {start} — {end}\n\n"
            "1. Scope\n"
            "General freight transport for {company}. {product_type} "
            "distribution across {routes} routes in {regions}. "
            "No temperature requirements. Standard cargo insurance.\n\n"
            "2. Service Levels\n"
            "On-time delivery target: {sla}%. Delivery window: {window} "
            "hours. Tracking updates every {tracking_interval} minutes.\n\n"
            "3. Penalties\n"
            "Late delivery: EUR {late_pen} per shipment. Damage to goods: "
            "replacement cost up to EUR {damage_cap} per incident. "
            "Missing documentation: EUR {doc_pen} per occurrence.\n\n"
            "4. Financial Terms\n"
            "Annual value: EUR {annual_value}. Payment: NET {net} days. "
            "Volume discount: {discount}% above {volume_threshold} "
            "shipments/month.\n\n"
            "5. Insurance\n"
            "Cargo insurance: EUR {insurance_cap} per shipment. "
            "Liability cap: {liability_x}x annual contract value.\n\n"
            "6. Termination\n"
            "{notice} months written notice. {extra_term}"
        ),
    },
]

HR_TEMPLATES = [
    {
        "type": "policy",
        "department": "hr",
        "clearance": 2,
        "template": (
            "{title}\n"
            "LogiCore Sp. z o.o. — HR Department\n"
            "Version {version} — Effective {start}\n\n"
            "1. {section1_title}\n"
            "{section1_body}\n\n"
            "2. {section2_title}\n"
            "{section2_body}\n\n"
            "3. {section3_title}\n"
            "{section3_body}\n\n"
            "4. {section4_title}\n"
            "{section4_body}\n\n"
            "5. Documentation\n"
            "All records maintained in HR system for {retention} years "
            "per RODO data retention requirements."
        ),
    },
]


def _generate_contract(template_idx: int, variant: int, seed: int) -> dict:
    """Generate a contract document from template with random parameters."""
    rng = random.Random(seed)
    tmpl = CONTRACT_TEMPLATES[template_idx % len(CONTRACT_TEMPLATES)]
    company = COMPANY_NAMES[variant % len(COMPANY_NAMES)]
    year = rng.choice([2023, 2024, 2025])
    ctr_num = f"CTR-{year}-{variant + 100:03d}"

    params = {
        "ctr": ctr_num,
        "company": company,
        "country": rng.choice(["Poland", "Czech Republic", "Slovakia"]),
        "start": f"{year}-{rng.randint(1,6):02d}-01",
        "end": f"{year+2}-{rng.randint(1,6):02d}-28",
        "routes": rng.randint(4, 20),
        "regions": rng.choice([
            "Mazowsze and Łódzkie",
            "Śląsk and Małopolska",
            "Wielkopolska and Kujawy",
            "Pomorze and Warmia-Mazury",
            "all of Poland and Central Europe",
        ]),
        "destinations": rng.choice([
            "pharmacies and hospitals",
            "distribution centers",
            "retail locations",
            "manufacturing facilities",
        ]),
        "sla": rng.choice([95.0, 96.5, 97.0, 98.0, 98.5, 99.0]),
        "window": rng.choice([2, 3, 4, 6]),
        "late_pen": rng.choice([100, 200, 300, 500, 750, 1000]),
        "temp_pen": rng.choice([500, 1000, 1500, 2000, 3000]),
        "doc_pen": rng.choice([50, 100, 150, 200]),
        "pen_cap": rng.choice([100_000, 250_000, 500_000, 750_000]),
        "annual_value": rng.choice([
            320_000, 450_000, 650_000, 890_000,
            1_200_000, 1_500_000, 2_100_000, 3_400_000,
        ]),
        "net": rng.choice([15, 30, 45, 60]),
        "notice": rng.randint(3, 12),
        "breach_count": rng.choice([2, 3, 4, 5]),
        "temp_range": rng.choice(["2-8°C", "15-25°C", "-20 to -15°C"]),
        "extra_compliance": rng.choice([
            "Annual GDP audit by independent assessor.",
            "Quarterly internal compliance review.",
            "Monthly temperature log submission to client.",
        ]),
        "cargo_classes": rng.choice([
            "UN Class 3 (flammable liquids)",
            "UN Class 6.1 (toxic substances) and Class 8 (corrosives)",
            "UN Class 2 (gases) and Class 3 (flammable liquids)",
        ]),
        "extra_safety": rng.choice([
            "emergency shower equipment",
            "gas detection monitors",
            "explosion-proof lighting",
        ]),
        "violation_pen": rng.choice([2000, 3000, 5000, 7500, 10_000]),
        "fine_pct": rng.choice([50, 75, 100]),
        "response_min": rng.choice([15, 30, 45]),
        "response_km": rng.choice([25, 50, 75]),
        "product_type": rng.choice([
            "fresh produce", "frozen seafood", "dairy products",
            "bakery goods", "auto parts", "electronics",
            "industrial machinery", "construction materials",
        ]),
        "locations": rng.randint(20, 500),
        "fresh_temp": rng.choice(["2-6", "2-8", "4-8"]),
        "frozen_temp": rng.choice([-18, -20, -25]),
        "excursion_min": rng.choice([10, 15, 20, 30]),
        "spoilage_pen": rng.choice([500, 1000, 2000]),
        "extra_quality": rng.choice([
            "Annual HACCP audit by accredited body.",
            "Monthly microbiological testing of transport containers.",
            "Quarterly allergen cross-contamination review.",
        ]),
        "tracking_interval": rng.choice([15, 30, 60]),
        "damage_cap": rng.choice([5000, 10_000, 25_000, 50_000]),
        "discount": rng.choice([3, 5, 7, 10]),
        "volume_threshold": rng.choice([50, 100, 200, 500]),
        "insurance_cap": rng.choice([50_000, 100_000, 250_000]),
        "liability_x": rng.choice([1, 2, 3]),
        "extra_term": rng.choice([
            "Force majeure clause includes pandemics and natural disasters.",
            "Mutual termination for convenience with 6 months notice.",
            "Auto-renewal for 1-year periods unless terminated.",
        ]),
    }

    text = tmpl["template"].format(**params)
    doc_id = f"DOC-{tmpl['type'].upper()}-{variant+100:03d}"

    return {
        "doc_id": doc_id,
        "text": text,
        "department": tmpl["department"],
        "clearance": tmpl["clearance"],
    }


def generate_expanded_corpus(target_size: int) -> list[dict]:
    """Generate an expanded corpus of target_size documents."""
    docs = []

    # Include original 12 docs
    for doc in CORPUS:
        docs.append({
            "doc_id": doc.doc_id,
            "text": doc.text,
            "department": doc.department,
            "clearance": doc.clearance_level,
        })

    # Generate additional contracts
    variant = 0
    while len(docs) < target_size:
        template_idx = variant % len(CONTRACT_TEMPLATES)
        seed = variant * 42 + 7
        doc = _generate_contract(template_idx, variant, seed)
        docs.append(doc)
        variant += 1

    return docs[:target_size]


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_benchmark(
    corpus_docs: list[dict],
    model_names: list[str],
    top_k: int = 5,
    rerank_top_k: int = 10,
):
    """Run re-ranking benchmark with given corpus and models."""
    from qdrant_client import AsyncQdrantClient

    ceo = UserContext(
        user_id="eva.richter",
        clearance_level=4,
        departments=[
            "hr", "management", "legal",
            "logistics", "warehouse", "executive",
        ],
    )

    qdrant = AsyncQdrantClient(
        host="localhost", port=6333, check_compatibility=False
    )
    embeddings = get_embeddings()

    try:
        # Seed corpus
        print(f"  Seeding {len(corpus_docs)} documents...")
        if await qdrant.collection_exists(COLLECTION_NAME):
            await qdrant.delete_collection(COLLECTION_NAME)
        await ensure_collection(qdrant, dense_size=DENSE_VECTOR_SIZE)

        for doc in corpus_docs:
            await ingest_document(
                text=doc["text"],
                document_id=doc["doc_id"],
                department_id=doc["department"],
                clearance_level=doc["clearance"],
                source_file=f"{doc['doc_id']}.txt",
                qdrant_client=qdrant,
                embed_fn=embeddings.aembed_documents,
                chunk_size=400,
                chunk_overlap=50,
            )

        print(f"  Seeded {len(corpus_docs)} documents")
        print()

        mode = SearchMode.DENSE_ONLY
        noop = NoOpReranker()

        # Load all models
        rerankers = {}
        for model_name in model_names:
            short_name = model_name.split("/")[-1]
            print(f"  Loading model: {short_name}...")
            rerankers[short_name] = LocalCrossEncoderReranker(
                model_name=model_name
            )

        categories = sorted(get_all_categories())

        # Results storage: model -> category -> metrics
        all_results = {}

        # NoOp baseline
        print()
        print("  Running NoOp baseline...")
        noop_cat_results = {}
        noop_all_mrr = []
        noop_all_p5 = []

        for cat in categories:
            queries = get_queries_by_category(cat)
            cat_mrr = []
            cat_p5 = []
            for q in queries:
                results = await hybrid_search(
                    query=q.query, user=ceo,
                    qdrant_client=qdrant,
                    embed_fn=embeddings.aembed_query,
                    top_k=rerank_top_k, mode=mode,
                )
                noop_results = await noop.rerank(q.query, results, top_k=top_k)
                ids = [r.document_id for r in noop_results]
                cat_mrr.append(compute_mrr(ids, q.relevant_doc_ids))
                cat_p5.append(
                    compute_precision_at_k(ids, q.relevant_doc_ids, top_k)
                )

            noop_cat_results[cat] = {
                "mrr": sum(cat_mrr) / len(cat_mrr),
                "p5": sum(cat_p5) / len(cat_p5),
            }
            noop_all_mrr.extend(cat_mrr)
            noop_all_p5.extend(cat_p5)

        noop_overall = {
            "mrr": sum(noop_all_mrr) / len(noop_all_mrr),
            "p5": sum(noop_all_p5) / len(noop_all_p5),
        }
        all_results["NoOp"] = {
            "categories": noop_cat_results,
            "overall": noop_overall,
            "latency_ms": 0,
        }

        # Each reranker model
        for short_name, reranker in rerankers.items():
            print(f"  Running {short_name}...")
            model_cat_results = {}
            model_all_mrr = []
            model_all_p5 = []
            model_latencies = []

            for cat in categories:
                queries = get_queries_by_category(cat)
                cat_mrr = []
                cat_p5 = []
                for q in queries:
                    results = await hybrid_search(
                        query=q.query, user=ceo,
                        qdrant_client=qdrant,
                        embed_fn=embeddings.aembed_query,
                        top_k=rerank_top_k, mode=mode,
                    )

                    start = time.perf_counter()
                    reranked = await reranker.rerank(
                        q.query, results, top_k=top_k
                    )
                    lat = (time.perf_counter() - start) * 1000
                    model_latencies.append(lat)

                    ids = [r.document_id for r in reranked]
                    cat_mrr.append(compute_mrr(ids, q.relevant_doc_ids))
                    cat_p5.append(
                        compute_precision_at_k(ids, q.relevant_doc_ids, top_k)
                    )

                model_cat_results[cat] = {
                    "mrr": sum(cat_mrr) / len(cat_mrr),
                    "p5": sum(cat_p5) / len(cat_p5),
                }
                model_all_mrr.extend(cat_mrr)
                model_all_p5.extend(cat_p5)

            model_overall = {
                "mrr": sum(model_all_mrr) / len(model_all_mrr),
                "p5": sum(model_all_p5) / len(model_all_p5),
            }
            avg_lat = sum(model_latencies) / len(model_latencies)
            all_results[short_name] = {
                "categories": model_cat_results,
                "overall": model_overall,
                "latency_ms": avg_lat,
            }

        # Print comparison table
        print()
        print(f"  {'':30}", end="")
        for name in all_results:
            print(f" {name:>20}", end="")
        print()
        print("  " + "-" * (30 + 21 * len(all_results)))

        for cat in categories:
            print(f"  {cat:<30}", end="")
            for name, data in all_results.items():
                mrr = data["categories"][cat]["mrr"]
                noop_mrr = all_results["NoOp"]["categories"][cat]["mrr"]
                delta = mrr - noop_mrr
                if name == "NoOp":
                    print(f" {mrr:>20.3f}", end="")
                else:
                    print(f" {mrr:>10.3f} ({delta:+.3f})", end="")
            print()

        print("  " + "-" * (30 + 21 * len(all_results)))
        print(f"  {'OVERALL MRR':<30}", end="")
        for name, data in all_results.items():
            mrr = data["overall"]["mrr"]
            noop_mrr = all_results["NoOp"]["overall"]["mrr"]
            delta = mrr - noop_mrr
            if name == "NoOp":
                print(f" {mrr:>20.3f}", end="")
            else:
                print(f" {mrr:>10.3f} ({delta:+.3f})", end="")
        print()

        print(f"  {'OVERALL P@5':<30}", end="")
        for name, data in all_results.items():
            p5 = data["overall"]["p5"]
            noop_p5 = all_results["NoOp"]["overall"]["p5"]
            delta = p5 - noop_p5
            if name == "NoOp":
                print(f" {p5:>20.3f}", end="")
            else:
                print(f" {p5:>10.3f} ({delta:+.3f})", end="")
        print()

        print(f"  {'LATENCY (ms)':<30}", end="")
        for name, data in all_results.items():
            lat = data["latency_ms"]
            if name == "NoOp":
                print(f" {'0':>20}", end="")
            else:
                print(f" {lat:>20.0f}", end="")
        print()

        # Architect analysis
        print()
        print("  ARCHITECT ANALYSIS:")
        print("  " + "-" * 60)
        print(f"  Corpus size: {len(corpus_docs)} documents")
        print(
            f"  Avg doc length: "
            f"{sum(len(d['text']) for d in corpus_docs) // len(corpus_docs)} chars"
        )
        print()

        noop_mrr = all_results["NoOp"]["overall"]["mrr"]
        for name, data in all_results.items():
            if name == "NoOp":
                continue
            mrr = data["overall"]["mrr"]
            delta = mrr - noop_mrr
            pct = (delta / noop_mrr * 100) if noop_mrr > 0 else 0
            lat = data["latency_ms"]

            if delta > 0.01:
                print(
                    f"  {name}: IMPROVES MRR by {delta:+.3f} ({pct:+.1f}%) "
                    f"at {lat:.0f}ms/query"
                )
                # Show which categories improved
                helped = []
                hurt = []
                for cat in categories:
                    cat_d = (
                        data["categories"][cat]["mrr"]
                        - all_results["NoOp"]["categories"][cat]["mrr"]
                    )
                    if cat_d > 0.01:
                        helped.append(f"{cat} ({cat_d:+.3f})")
                    elif cat_d < -0.01:
                        hurt.append(f"{cat} ({cat_d:+.3f})")
                if helped:
                    print(f"    Helped: {', '.join(helped)}")
                if hurt:
                    print(f"    Hurt: {', '.join(hurt)}")
            elif delta < -0.01:
                print(
                    f"  {name}: HURTS MRR by {delta:+.3f} ({pct:+.1f}%) "
                    f"at {lat:.0f}ms/query"
                )
                # Show worst categories
                worst = []
                for cat in categories:
                    cat_d = (
                        data["categories"][cat]["mrr"]
                        - all_results["NoOp"]["categories"][cat]["mrr"]
                    )
                    if cat_d < -0.1:
                        worst.append(f"{cat} ({cat_d:+.3f})")
                if worst:
                    print(f"    Worst: {', '.join(worst)}")
            else:
                print(f"  {name}: NO EFFECT ({delta:+.3f})")

        await qdrant.delete_collection(COLLECTION_NAME)

    finally:
        await qdrant.close()


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Re-ranking benchmark with multiple models and corpus scales"
    )
    parser.add_argument(
        "--scale", type=int, default=12,
        help="Corpus size (12=original, 50/100/200=expanded)",
    )
    parser.add_argument(
        "--models", type=str, default="english",
        help=(
            "Which models: 'english' (MS MARCO only), "
            "'multilingual' (multilingual only), "
            "'all' (both)"
        ),
    )
    args = parser.parse_args()

    ENGLISH_MODEL = "cross-encoder/ms-marco-MiniLM-L-12-v2"
    MULTILINGUAL_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    if args.models == "english":
        model_names = [ENGLISH_MODEL]
    elif args.models == "multilingual":
        model_names = [MULTILINGUAL_MODEL]
    elif args.models == "all":
        model_names = [ENGLISH_MODEL, MULTILINGUAL_MODEL]
    else:
        model_names = [args.models]

    model_short = [m.split("/")[-1] for m in model_names]

    print("=" * 78)
    print("RE-RANKING BENCHMARK")
    print(f"  Corpus scale: {args.scale} documents")
    print(f"  Models: {', '.join(model_short)}")
    print(f"  Queries: {len(GROUND_TRUTH)} ground truth, "
          f"{len(get_all_categories())} categories")
    print("=" * 78)

    if args.scale <= 12:
        corpus = [
            {
                "doc_id": d.doc_id,
                "text": d.text,
                "department": d.department,
                "clearance": d.clearance_level,
            }
            for d in CORPUS
        ]
    else:
        corpus = generate_expanded_corpus(args.scale)

    avg_len = sum(len(d["text"]) for d in corpus) // len(corpus)
    print(f"  Avg doc length: {avg_len} chars")
    print()

    await run_benchmark(corpus, model_names)

    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
