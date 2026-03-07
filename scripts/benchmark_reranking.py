"""Re-ranking benchmark: Compare retrieval with and without cross-encoder re-ranking.

Ingests the 12-doc corpus into Qdrant, runs 52 ground truth queries, then
re-ranks top results with LocalCrossEncoderReranker. Measures precision@5,
recall@5, MRR improvement.

Usage:
    python scripts/benchmark_reranking.py

Requires: Qdrant on localhost:6333, Azure OpenAI credentials in .env,
          sentence-transformers installed.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.config.settings import settings  # noqa: F401 — loads .env
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


async def main():
    from qdrant_client import AsyncQdrantClient

    print("=" * 78)
    print("RE-RANKING BENCHMARK: NoOp vs Local Cross-Encoder")
    print("  Model: cross-encoder/ms-marco-MiniLM-L-12-v2")
    print("  Queries: 52 ground truth, 10 categories")
    print("=" * 78)

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
    top_k = 5
    rerank_top_k = 10  # Retrieve more, then re-rank to top_k

    # Initialize rerankers
    noop = NoOpReranker()
    print("  Loading cross-encoder model (first load downloads ~130MB)...")
    cross_encoder = LocalCrossEncoderReranker(
        model_name="cross-encoder/ms-marco-MiniLM-L-12-v2"
    )

    try:
        # Seed
        print("  Seeding collection...")
        if await qdrant.collection_exists(COLLECTION_NAME):
            await qdrant.delete_collection(COLLECTION_NAME)
        await ensure_collection(qdrant, dense_size=DENSE_VECTOR_SIZE)

        for doc in CORPUS:
            await ingest_document(
                text=doc.text,
                document_id=doc.doc_id,
                department_id=doc.department,
                clearance_level=doc.clearance_level,
                source_file=f"{doc.doc_id}.txt",
                qdrant_client=qdrant,
                embed_fn=embeddings.aembed_documents,
                chunk_size=400,
                chunk_overlap=50,
            )

        print(f"  Seeded {len(CORPUS)} documents")
        print()

        # Search mode: dense_only (best from Phase 2 benchmarks)
        mode = SearchMode.DENSE_ONLY

        # Track per-category results
        categories = sorted(get_all_categories())
        all_noop_mrr = []
        all_rerank_mrr = []
        all_noop_p5 = []
        all_rerank_p5 = []
        all_rerank_latencies = []
        category_results = {}

        for cat in categories:
            queries = get_queries_by_category(cat)
            cat_noop_mrr = []
            cat_rerank_mrr = []
            cat_noop_p5 = []
            cat_rerank_p5 = []

            for q in queries:
                # Step 1: Retrieve top rerank_top_k results (over-fetch)
                results = await hybrid_search(
                    query=q.query,
                    user=ceo,
                    qdrant_client=qdrant,
                    embed_fn=embeddings.aembed_query,
                    top_k=rerank_top_k,
                    mode=mode,
                )

                # NoOp: just take top_k from raw results
                noop_results = await noop.rerank(q.query, results, top_k=top_k)
                noop_ids = [r.document_id for r in noop_results]

                noop_mrr = compute_mrr(noop_ids, q.relevant_doc_ids)
                noop_p5 = compute_precision_at_k(
                    noop_ids, q.relevant_doc_ids, top_k
                )
                cat_noop_mrr.append(noop_mrr)
                cat_noop_p5.append(noop_p5)

                # Cross-encoder re-rank
                start = time.perf_counter()
                reranked = await cross_encoder.rerank(
                    q.query, results, top_k=top_k
                )
                rerank_lat = (time.perf_counter() - start) * 1000
                all_rerank_latencies.append(rerank_lat)

                rerank_ids = [r.document_id for r in reranked]
                rerank_mrr = compute_mrr(rerank_ids, q.relevant_doc_ids)
                rerank_p5 = compute_precision_at_k(
                    rerank_ids, q.relevant_doc_ids, top_k
                )
                cat_rerank_mrr.append(rerank_mrr)
                cat_rerank_p5.append(rerank_p5)

            avg_noop_mrr = sum(cat_noop_mrr) / len(cat_noop_mrr)
            avg_rerank_mrr = sum(cat_rerank_mrr) / len(cat_rerank_mrr)
            avg_noop_p5 = sum(cat_noop_p5) / len(cat_noop_p5)
            avg_rerank_p5 = sum(cat_rerank_p5) / len(cat_rerank_p5)

            category_results[cat] = {
                "noop_mrr": avg_noop_mrr,
                "rerank_mrr": avg_rerank_mrr,
                "mrr_delta": avg_rerank_mrr - avg_noop_mrr,
                "noop_p5": avg_noop_p5,
                "rerank_p5": avg_rerank_p5,
                "p5_delta": avg_rerank_p5 - avg_noop_p5,
            }

            all_noop_mrr.extend(cat_noop_mrr)
            all_rerank_mrr.extend(cat_rerank_mrr)
            all_noop_p5.extend(cat_noop_p5)
            all_rerank_p5.extend(cat_rerank_p5)

        # Print per-category table
        print(
            f"  {'Category':<20} {'NoOp MRR':>10} {'Rerank MRR':>12} "
            f"{'Δ MRR':>8} {'NoOp P@5':>10} {'Rerank P@5':>12} {'Δ P@5':>8}"
        )
        print("  " + "-" * 85)

        for cat in categories:
            cr = category_results[cat]
            print(
                f"  {cat:<20}"
                f" {cr['noop_mrr']:>10.3f}"
                f" {cr['rerank_mrr']:>12.3f}"
                f" {cr['mrr_delta']:>+8.3f}"
                f" {cr['noop_p5']:>10.3f}"
                f" {cr['rerank_p5']:>12.3f}"
                f" {cr['p5_delta']:>+8.3f}"
            )

        # Aggregates
        overall_noop_mrr = sum(all_noop_mrr) / len(all_noop_mrr)
        overall_rerank_mrr = sum(all_rerank_mrr) / len(all_rerank_mrr)
        overall_noop_p5 = sum(all_noop_p5) / len(all_noop_p5)
        overall_rerank_p5 = sum(all_rerank_p5) / len(all_rerank_p5)
        avg_lat = sum(all_rerank_latencies) / len(all_rerank_latencies)

        print("  " + "-" * 85)
        mrr_d = overall_rerank_mrr - overall_noop_mrr
        p5_d = overall_rerank_p5 - overall_noop_p5
        print(
            f"  {'OVERALL':<20}"
            f" {overall_noop_mrr:>10.3f}"
            f" {overall_rerank_mrr:>12.3f}"
            f" {mrr_d:>+8.3f}"
            f" {overall_noop_p5:>10.3f}"
            f" {overall_rerank_p5:>12.3f}"
            f" {p5_d:>+8.3f}"
        )

        print()
        print(f"  Re-ranking latency: avg {avg_lat:.0f}ms per query")

        # Categories where reranking helped / hurt
        helped = [
            c for c, cr in category_results.items() if cr["mrr_delta"] > 0.01
        ]
        hurt = [
            c for c, cr in category_results.items() if cr["mrr_delta"] < -0.01
        ]
        neutral = [
            c for c, cr in category_results.items()
            if -0.01 <= cr["mrr_delta"] <= 0.01
        ]

        print()
        print("  ARCHITECT ANALYSIS:")
        print("  " + "-" * 60)

        if mrr_d > 0:
            pct = (mrr_d / overall_noop_mrr) * 100 if overall_noop_mrr > 0 else 0
            print(
                f"  Re-ranking IMPROVES overall MRR by {mrr_d:+.3f} ({pct:+.1f}%)"
            )
        elif mrr_d < 0:
            pct = (mrr_d / overall_noop_mrr) * 100 if overall_noop_mrr > 0 else 0
            print(
                f"  Re-ranking HURTS overall MRR by {mrr_d:+.3f} ({pct:+.1f}%)"
            )
        else:
            print("  Re-ranking has NO EFFECT on overall MRR.")

        if helped:
            print(f"  Helped: {', '.join(helped)}")
        if hurt:
            print(f"  Hurt: {', '.join(hurt)}")
        if neutral:
            print(f"  Neutral: {', '.join(neutral)}")

        print()
        if mrr_d > 0:
            print(
                f"  RECOMMENDATION: Enable re-ranking. "
                f"Cost: {avg_lat:.0f}ms latency per query. "
                f"Benefit: {pct:+.1f}% MRR improvement."
            )
            print(
                "  Switch condition: Disable if latency budget is <50ms "
                "and MRR is already >0.95."
            )
        elif mrr_d < -0.01:
            print(
                "  RECOMMENDATION: Do NOT enable re-ranking at this corpus scale."
            )
            print(
                "  The cross-encoder re-scores based on query-document relevance, "
                "but with short documents (~200 chars), all chunks score similarly."
            )
            print(
                "  Re-evaluate when: documents are >1000 chars, multiple chunks "
                "per doc, and initial retrieval returns false positives in top-5."
            )
        else:
            print(
                "  RECOMMENDATION: Re-ranking adds latency without improving MRR."
            )
            print(
                "  Keep the architecture (BaseReranker, CircuitBreaker) but don't "
                "enable by default."
            )
            print(
                "  Re-evaluate when: corpus >500 docs, document length >1000 chars, "
                "or precision@1 drops below 0.80."
            )

        await qdrant.delete_collection(COLLECTION_NAME)

    finally:
        await qdrant.close()

    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
