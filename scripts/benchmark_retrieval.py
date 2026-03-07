"""End-to-end retrieval quality benchmark.

Measures the full pipeline: chunking + embedding + search.
Compares pipeline configurations: no chunking, fixed-size, semantic.

Usage:
    python scripts/benchmark_retrieval.py --mock
    python scripts/benchmark_retrieval.py --live
    python scripts/benchmark_retrieval.py --live --mode hybrid

Requires:
    --mock: No external services
    --live: Qdrant on localhost:6333, Azure OpenAI credentials in .env

Output: Table with precision@k, recall@k, MRR per pipeline config.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.rag.chunking import FixedSizeChunker, SemanticChunker
from apps.api.src.rag.embeddings import MockEmbedder
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


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MockRetrievalPipeline:
    """In-memory retrieval pipeline for benchmarking without Qdrant.

    Embeds documents (or chunks) in memory, retrieves by cosine
    similarity. No external services required.
    """

    def __init__(
        self,
        embedder: MockEmbedder,
        chunker=None,
    ):
        self.embedder = embedder
        self.chunker = chunker
        self.doc_embeddings: list[tuple[str, list[float]]] = []

    async def index(self):
        """Embed all documents (or chunks) into memory."""
        self.doc_embeddings = []

        for doc in CORPUS:
            if self.chunker:
                chunks = self.chunker.chunk(doc.text)
                for chunk_result in chunks:
                    vec = await self.embedder.embed_query(
                        chunk_result.content
                    )
                    self.doc_embeddings.append((doc.doc_id, vec))
            else:
                vec = await self.embedder.embed_query(doc.text)
                self.doc_embeddings.append((doc.doc_id, vec))

    async def search(self, query: str, top_k: int = 5) -> list[str]:
        """Search by cosine similarity. Deduplicates by doc_id."""
        query_vec = await self.embedder.embed_query(query)

        scored = [
            (doc_id, cosine_similarity(query_vec, doc_vec))
            for doc_id, doc_vec in self.doc_embeddings
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        seen: set[str] = set()
        result: list[str] = []
        for doc_id, _ in scored:
            if doc_id not in seen:
                seen.add(doc_id)
                result.append(doc_id)
                if len(result) >= top_k:
                    break

        return result


async def run_mock_benchmark(args):
    """Run benchmark with mock embedder and in-memory retrieval."""
    print("=" * 78)
    print("END-TO-END RETRIEVAL BENCHMARK (Mock Mode)")
    print("=" * 78)
    n_cats = len(get_all_categories())
    print(f"  Corpus: {len(CORPUS)} documents")
    print(f"  Queries: {len(GROUND_TRUTH)} ground truth ({n_cats} cats)")
    print(f"  Top-k: {args.top_k}")
    print()

    embedder = MockEmbedder(dimensions=256)

    def sync_embed(texts: list[str]) -> list[list[float]]:
        return [embedder._hash_to_vector(t) for t in texts]

    configs = [
        ("Whole-doc (no chunking)", None),
        (
            "Fixed-size 512",
            FixedSizeChunker(chunk_size=512, overlap=50),
        ),
        (
            "Fixed-size 256",
            FixedSizeChunker(chunk_size=256, overlap=25),
        ),
        (
            "Semantic (t=0.5)",
            SemanticChunker(
                similarity_threshold=0.5,
                min_chunk_size=50,
                max_chunk_size=2000,
                embed_fn=sync_embed,
            ),
        ),
    ]

    results: list[dict] = []

    for name, chunker in configs:
        print(f"  Testing: {name}...")
        pipeline = MockRetrievalPipeline(embedder, chunker)
        await pipeline.index()

        start = time.perf_counter()

        precisions = []
        recalls = []
        mrr_scores = []

        for q in GROUND_TRUTH:
            retrieved = await pipeline.search(q.query, args.top_k)
            precisions.append(
                compute_precision_at_k(
                    retrieved, q.relevant_doc_ids, args.top_k
                )
            )
            recalls.append(
                compute_recall_at_k(
                    retrieved, q.relevant_doc_ids, args.top_k
                )
            )
            mrr_scores.append(
                compute_mrr(retrieved, q.relevant_doc_ids)
            )

        elapsed_ms = (time.perf_counter() - start) * 1000

        avg_p = sum(precisions) / len(precisions)
        avg_r = sum(recalls) / len(recalls)
        avg_mrr = sum(mrr_scores) / len(mrr_scores)

        # Per-category breakdown
        cat_metrics = {}
        for cat in get_all_categories():
            cat_queries = get_queries_by_category(cat)
            cat_p = []
            cat_r = []
            cat_m = []
            for q in cat_queries:
                retrieved = await pipeline.search(q.query, args.top_k)
                cat_p.append(
                    compute_precision_at_k(
                        retrieved, q.relevant_doc_ids, args.top_k
                    )
                )
                cat_r.append(
                    compute_recall_at_k(
                        retrieved, q.relevant_doc_ids, args.top_k
                    )
                )
                cat_m.append(
                    compute_mrr(retrieved, q.relevant_doc_ids)
                )
            cat_metrics[cat] = {
                "precision": sum(cat_p) / len(cat_p),
                "recall": sum(cat_r) / len(cat_r),
                "mrr": sum(cat_m) / len(cat_m),
            }

        results.append({
            "config": name,
            "precision_at_k": avg_p,
            "recall_at_k": avg_r,
            "mrr": avg_mrr,
            "total_ms": elapsed_ms,
            "chunks_indexed": len(pipeline.doc_embeddings),
            "per_category": cat_metrics,
        })

    # Print results table
    print()
    header = (
        f"  {'Config':<25} {'Chunks':>8} {'P@k':>8} "
        f"{'R@k':>8} {'MRR':>8} {'Time':>10}"
    )
    print(header)
    print("  " + "-" * 70)
    for r in results:
        print(
            f"  {r['config']:<25}"
            f" {r['chunks_indexed']:>8}"
            f" {r['precision_at_k']:>8.3f}"
            f" {r['recall_at_k']:>8.3f}"
            f" {r['mrr']:>8.3f}"
            f" {r['total_ms']:>8.0f}ms"
        )

    # Per-category for best config
    best = max(results, key=lambda r: r["mrr"])
    print()
    print(f"  Per-category for best config: {best['config']}")
    print(f"  {'Category':<20} {'P@k':>8} {'R@k':>8} {'MRR':>8}")
    print("  " + "-" * 50)
    for cat in sorted(best["per_category"].keys()):
        m = best["per_category"][cat]
        print(
            f"  {cat:<20}"
            f" {m['precision']:>8.3f}"
            f" {m['recall']:>8.3f}"
            f" {m['mrr']:>8.3f}"
        )

    # Architect verdict
    print()
    print("  ARCHITECT ANALYSIS:")
    print("  " + "-" * 60)
    print(f"  Best MRR: {best['config']} ({best['mrr']:.3f})")

    worst = min(results, key=lambda r: r["mrr"])
    mrr_delta = best["mrr"] - worst["mrr"]
    print(f"  Worst MRR: {worst['config']} ({worst['mrr']:.3f})")
    print(f"  MRR spread: {mrr_delta:.3f}")

    if mrr_delta < 0.05:
        print()
        print("  NOTE: With mock embeddings (hash-based), there is no")
        print("  semantic understanding. MRR differences reflect")
        print("  structural chunking effects, NOT semantic quality.")
        print("  Run with --live for meaningful semantic benchmarks.")
    else:
        print()
        pct = mrr_delta * 100
        print(
            f"  DECISION: {best['config']} produces "
            f"{mrr_delta:.3f} higher MRR than {worst['config']}."
        )
        print(
            f"  That means {pct:.1f}% more queries have "
            "the right document at rank 1."
        )

    print("=" * 78)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n  Results saved to {args.output_json}")


async def run_live_benchmark(args):
    """Run benchmark with real Qdrant and embeddings."""
    try:
        from qdrant_client import AsyncQdrantClient
    except ImportError:
        print("  [ERROR] qdrant-client not installed")
        return

    from apps.api.src.domain.document import UserContext
    from apps.api.src.infrastructure.qdrant.collections import (
        COLLECTION_NAME,
        DENSE_VECTOR_SIZE,
        ensure_collection,
    )
    from apps.api.src.rag.ingestion import ingest_document
    from apps.api.src.rag.retriever import SearchMode, hybrid_search

    print("=" * 78)
    print("END-TO-END RETRIEVAL BENCHMARK (Live Mode)")
    print("=" * 78)
    print(f"  Corpus: {len(CORPUS)} documents")
    print(f"  Queries: {len(GROUND_TRUTH)} ground truth")
    print(f"  Top-k: {args.top_k}")
    print(f"  Search mode: {args.mode}")
    print()

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

    try:
        from apps.api.src.rag.embeddings import get_embeddings

        embeddings = get_embeddings()

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

        mode = SearchMode(args.mode)

        precisions = []
        recalls = []
        mrr_scores = []
        latencies = []

        for q in GROUND_TRUTH:
            start = time.perf_counter()
            results = await hybrid_search(
                query=q.query,
                user=ceo,
                qdrant_client=qdrant,
                embed_fn=embeddings.aembed_query,
                top_k=args.top_k,
                mode=mode,
            )
            lat = (time.perf_counter() - start) * 1000
            latencies.append(lat)

            retrieved_ids = [r.document_id for r in results]
            precisions.append(
                compute_precision_at_k(
                    retrieved_ids, q.relevant_doc_ids, args.top_k
                )
            )
            recalls.append(
                compute_recall_at_k(
                    retrieved_ids, q.relevant_doc_ids, args.top_k
                )
            )
            mrr_scores.append(
                compute_mrr(retrieved_ids, q.relevant_doc_ids)
            )

        avg_p = sum(precisions) / len(precisions)
        avg_r = sum(recalls) / len(recalls)
        avg_mrr = sum(mrr_scores) / len(mrr_scores)
        avg_lat = sum(latencies) / len(latencies)

        print()
        print(f"  {'Metric':<20} {'Value':>10}")
        print("  " + "-" * 35)
        k_str = str(args.top_k)
        print(f"  {'Precision@' + k_str:<20} {avg_p:>10.3f}")
        print(f"  {'Recall@' + k_str:<20} {avg_r:>10.3f}")
        print(f"  {'MRR':<20} {avg_mrr:>10.3f}")
        print(f"  {'Avg Latency':<20} {avg_lat:>8.1f}ms")

        # Per-category
        print()
        header = f"  {'Category':<20} {'P@k':>8} {'R@k':>8} {'MRR':>8}"
        print(header)
        print("  " + "-" * 50)
        for cat in sorted(get_all_categories()):
            cat_queries = get_queries_by_category(cat)
            cat_p = []
            cat_r = []
            cat_m = []
            for q_item in cat_queries:
                r = await hybrid_search(
                    query=q_item.query,
                    user=ceo,
                    qdrant_client=qdrant,
                    embed_fn=embeddings.aembed_query,
                    top_k=args.top_k,
                    mode=mode,
                )
                ids = [x.document_id for x in r]
                cat_p.append(
                    compute_precision_at_k(
                        ids, q_item.relevant_doc_ids, args.top_k
                    )
                )
                cat_r.append(
                    compute_recall_at_k(
                        ids, q_item.relevant_doc_ids, args.top_k
                    )
                )
                cat_m.append(
                    compute_mrr(ids, q_item.relevant_doc_ids)
                )
            print(
                f"  {cat:<20}"
                f" {sum(cat_p) / len(cat_p):>8.3f}"
                f" {sum(cat_r) / len(cat_r):>8.3f}"
                f" {sum(cat_m) / len(cat_m):>8.3f}"
            )

        await qdrant.delete_collection(COLLECTION_NAME)

    finally:
        await qdrant.close()

    print()
    print("  ARCHITECT ANALYSIS:")
    print("  " + "-" * 60)
    print(f"  Overall MRR: {avg_mrr:.3f} (mode={args.mode})")
    if avg_mrr >= 0.8:
        print("  Quality gate: PASS (MRR >= 0.80)")
    else:
        print(f"  Quality gate: FAIL (MRR {avg_mrr:.3f} < 0.80)")
        print("  RECOMMENDATION: Add re-ranking or HyDE.")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end retrieval benchmark"
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use mock embedder (no Qdrant)",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Use real embeddings + Qdrant",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Top-k for metrics",
    )
    parser.add_argument(
        "--mode", type=str, default="hybrid",
        help="Search mode: dense_only, sparse_only, hybrid",
    )
    parser.add_argument(
        "--output-json", type=Path, default=None,
        help="Save results to JSON",
    )

    args = parser.parse_args()

    if not args.mock and not args.live:
        args.mock = True

    if args.mock:
        asyncio.run(run_mock_benchmark(args))
    else:
        asyncio.run(run_live_benchmark(args))


if __name__ == "__main__":
    main()
