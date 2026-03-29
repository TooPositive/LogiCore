"""Compare embedding models on the LogiCore corpus.

Measures: precision@k, recall@k, MRR, latency, cost per model.
Uses the 52-query ground truth dataset.

Usage:
    python scripts/benchmark_embeddings.py \
        --models text-embedding-3-small,text-embedding-3-large
    python scripts/benchmark_embeddings.py --mock

Requires: Azure OpenAI credentials in .env (unless --mock)

Output: Table with precision@k, recall@k, MRR, latency, cost per model.
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

from apps.api.src.core.rag.embeddings import (
    EMBEDDING_MODELS,
    EmbeddingBenchmarkResult,
    MockEmbedder,
    get_embedder,
)
from tests.evaluation.corpus import CORPUS
from tests.evaluation.ground_truth import (
    GROUND_TRUTH,
    get_all_categories,
)
from tests.evaluation.metrics import (
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def run_embedding_benchmark(
    embedder,
    model_name: str,
    top_k: int = 5,
) -> EmbeddingBenchmarkResult:
    """Benchmark a single embedding model against the ground truth.

    Embeds all corpus documents, then for each ground truth query,
    embeds the query and ranks documents by cosine similarity.
    """
    doc_texts = [doc.text for doc in CORPUS]
    doc_ids = [doc.doc_id for doc in CORPUS]

    print(f"    Embedding {len(doc_texts)} documents...")
    doc_embeddings = await embedder.embed_documents(doc_texts)

    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    latencies: list[float] = []

    for q in GROUND_TRUTH:
        start = time.perf_counter()
        query_embedding = await embedder.embed_query(q.query)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)

        similarities = [
            (doc_ids[i], cosine_similarity(query_embedding, doc_emb))
            for i, doc_emb in enumerate(doc_embeddings)
        ]
        similarities.sort(key=lambda x: x[1], reverse=True)
        retrieved_ids = [did for did, _ in similarities[:top_k]]

        precisions.append(
            compute_precision_at_k(retrieved_ids, q.relevant_doc_ids, top_k)
        )
        recalls.append(
            compute_recall_at_k(retrieved_ids, q.relevant_doc_ids, top_k)
        )
        mrrs.append(compute_mrr(retrieved_ids, q.relevant_doc_ids))

    model_info = EMBEDDING_MODELS.get(model_name)
    cost = model_info.cost_per_1m_tokens if model_info else 0.0

    return EmbeddingBenchmarkResult(
        model_name=model_name,
        provider=type(embedder).__name__,
        dimensions=embedder.dimensions,
        precision_at_k={top_k: sum(precisions) / len(precisions)},
        recall_at_k={top_k: sum(recalls) / len(recalls)},
        mrr=sum(mrrs) / len(mrrs),
        avg_latency_ms=sum(latencies) / len(latencies),
        cost_per_1m_tokens=cost,
        total_queries=len(GROUND_TRUTH),
    )


async def main_async(args):
    print("=" * 78)
    print("EMBEDDING MODEL BENCHMARK")
    print("=" * 78)
    n_cats = len(get_all_categories())
    print(f"  Corpus: {len(CORPUS)} documents")
    print(f"  Queries: {len(GROUND_TRUTH)} ground truth ({n_cats} categories)")
    print(f"  Top-k: {args.top_k}")
    print()

    results: list[EmbeddingBenchmarkResult] = []

    if args.mock:
        models_to_test = ["mock-128d", "mock-1536d"]
        for model_name in models_to_test:
            dims = 128 if "128" in model_name else 1536
            embedder = MockEmbedder(dimensions=dims)
            print(f"  Benchmarking {model_name} ({dims}d, mock)...")
            result = await run_embedding_benchmark(
                embedder, model_name, args.top_k
            )
            result.notes = "Mock (hash-based, no semantic understanding)"
            results.append(result)
    else:
        model_names = [m.strip() for m in args.models.split(",")]
        for model_name in model_names:
            model_info = EMBEDDING_MODELS.get(model_name)
            if not model_info:
                print(f"  [SKIP] Unknown model: {model_name}")
                continue

            dims = model_info.dimensions
            cost = model_info.cost_per_1m_tokens
            print(f"  Benchmarking {model_name} ({dims}d, ${cost}/1M)...")
            try:
                embedder = get_embedder(
                    model_info.provider, model=model_name
                )
                result = await run_embedding_benchmark(
                    embedder, model_name, args.top_k
                )
                results.append(result)
            except Exception as e:
                print(f"    [ERROR] {e}")

    if not results:
        print("  No results to display.")
        return

    # Print results table
    print()
    header = (
        f"  {'Model':<28} {'Dims':>6} {'P@k':>8} "
        f"{'R@k':>8} {'MRR':>8} {'Latency':>10} {'Cost/1M':>10}"
    )
    print(header)
    print("  " + "-" * 80)
    for r in results:
        p_at_k = list(r.precision_at_k.values())[0]
        r_at_k = list(r.recall_at_k.values())[0]
        print(
            f"  {r.model_name:<28}"
            f" {r.dimensions:>6}"
            f" {p_at_k:>8.3f}"
            f" {r_at_k:>8.3f}"
            f" {r.mrr:>8.3f}"
            f" {r.avg_latency_ms:>8.1f}ms"
            f" ${r.cost_per_1m_tokens:>8.2f}"
        )

    # Architect verdict
    print()
    print("  ARCHITECT ANALYSIS:")
    print("  " + "-" * 60)

    if len(results) >= 2:
        best = max(results, key=lambda r: r.mrr)
        cheapest = min(results, key=lambda r: r.cost_per_1m_tokens)
        print(f"  Best MRR: {best.model_name} ({best.mrr:.3f})")
        cost_str = f"${cheapest.cost_per_1m_tokens}/1M tok"
        print(f"  Cheapest: {cheapest.model_name} ({cost_str})")

        if best.model_name != cheapest.model_name:
            if cheapest.cost_per_1m_tokens > 0:
                cost_ratio = (
                    best.cost_per_1m_tokens / cheapest.cost_per_1m_tokens
                )
            else:
                cost_ratio = float("inf")
            mrr_delta = best.mrr - cheapest.mrr
            print()
            print(
                f"  DECISION: Is {cost_ratio:.1f}x cost justified "
                f"for +{mrr_delta:.3f} MRR?"
            )
            if mrr_delta < 0.05:
                print(
                    f"  RECOMMENDATION: Use {cheapest.model_name}. "
                    f"MRR delta ({mrr_delta:.3f}) does not justify cost."
                )
                print(
                    "  REVISIT WHEN: corpus exceeds 1000 "
                    "semantically similar docs."
                )
            else:
                print(
                    f"  RECOMMENDATION: Use {best.model_name}. "
                    f"MRR improvement ({mrr_delta:.3f}) is significant."
                )
        else:
            print(
                f"  RECOMMENDATION: {best.model_name} "
                "is both best AND cheapest."
            )
    else:
        r = results[0]
        print(f"  Single model: {r.model_name} (MRR={r.mrr:.3f})")
        print("  Run with --models to compare multiple models.")

    print("=" * 78)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        output = [
            {
                "model_name": r.model_name,
                "provider": r.provider,
                "dimensions": r.dimensions,
                "precision_at_k": r.precision_at_k,
                "recall_at_k": r.recall_at_k,
                "mrr": r.mrr,
                "avg_latency_ms": r.avg_latency_ms,
                "cost_per_1m_tokens": r.cost_per_1m_tokens,
                "total_queries": r.total_queries,
                "notes": r.notes,
            }
            for r in results
        ]
        with open(args.output_json, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Results saved to {args.output_json}")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark embedding models"
    )
    parser.add_argument(
        "--models",
        type=str,
        default="text-embedding-3-small,text-embedding-3-large",
        help="Comma-separated model names",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use MockEmbedder (no credentials needed)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-k for precision/recall metrics",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Save results to JSON file",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
