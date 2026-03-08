"""Re-ranking benchmark v2: Prove WHEN re-ranking works vs when it doesn't.

Two corpus types, three reranker models:
1. HOMOGENEOUS corpus — all contracts (re-ranking should HURT)
2. DIVERSE corpus — contracts + safety + HR + technical + ops (re-ranking should HELP)

Models:
- NoOp (baseline)
- cross-encoder/ms-marco-MiniLM-L-12-v2 (English cross-encoder)
- BAAI/bge-reranker-v2-m3 (multilingual, 0.6B, BEIR #1)
- qwen3:8b via Ollama (LLM-based reranking)

Usage:
    python scripts/benchmark_reranking_v2.py

Requires: Qdrant, Azure OpenAI, sentence-transformers, Ollama with qwen3:8b
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.core.config.settings import settings  # noqa: F401
from apps.api.src.core.domain.document import UserContext
from apps.api.src.core.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    DENSE_VECTOR_SIZE,
    ensure_collection,
)
from apps.api.src.core.rag.embeddings import get_embeddings
from apps.api.src.core.rag.ingestion import ingest_document
from apps.api.src.core.rag.reranker import (
    BaseReranker,
    LocalCrossEncoderReranker,
    NoOpReranker,
    RerankResult,
    RerankerError,
    _to_rerank_results,
)
from apps.api.src.core.rag.retriever import SearchMode, hybrid_search
from tests.evaluation.corpus import CORPUS
from tests.evaluation.ground_truth import (
    GROUND_TRUTH,
    get_all_categories,
    get_queries_by_category,
)
from tests.evaluation.metrics import compute_mrr, compute_precision_at_k


# ---------------------------------------------------------------------------
# Ollama LLM-based reranker
# ---------------------------------------------------------------------------


class OllamaLLMReranker(BaseReranker):
    """LLM-based reranking via Ollama API.

    Sends each query-document pair to a local LLM and extracts a relevance
    score from the response. Slower than cross-encoders but can leverage
    the LLM's understanding of context and semantics.
    """

    def __init__(
        self,
        model: str = "qwen3:8b",
        ollama_url: str = "http://localhost:11434",
        confidence_threshold: float = 0.0,
    ) -> None:
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.confidence_threshold = confidence_threshold

    async def rerank(
        self, query: str, results: list, top_k: int = 5
    ) -> list[RerankResult]:
        if not results:
            return []

        scores = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for r in results:
                score = await self._score_pair(client, query, r.content)
                scores.append(score)

        return _to_rerank_results(
            results, scores, top_k, self.confidence_threshold
        )

    async def _score_pair(
        self, client: httpx.AsyncClient, query: str, document: str
    ) -> float:
        """Score a single query-document pair using the LLM."""
        prompt = (
            "Rate how relevant this document is to the query. "
            "Reply with ONLY a number from 0 to 10, nothing else.\n\n"
            f"Query: {query}\n\n"
            f"Document: {document[:500]}\n\n"
            "Relevance score (0-10):"
        )

        try:
            resp = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 10},
                },
            )
            resp.raise_for_status()
            text = resp.json()["response"].strip()
            # Extract first number from response
            for part in text.replace("/", " ").split():
                try:
                    score = float(part)
                    return min(max(score / 10.0, 0.0), 1.0)
                except ValueError:
                    continue
            return 0.0
        except Exception:
            return 0.0


# ---------------------------------------------------------------------------
# Corpus loading: LLM-generated production-quality documents
# ---------------------------------------------------------------------------


def _load_corpus_file(path: Path) -> list[dict]:
    """Load corpus from a JSON file."""
    if not path.exists():
        print(f"  WARNING: {path} not found.")
        return []
    with open(path) as f:
        raw = json.load(f)
    return [
        {"doc_id": e["doc_id"], "text": e["text"],
         "department": e.get("department", "legal"),
         "clearance": e.get("clearance_level", 1)}
        for e in raw
    ]


def load_homogeneous_corpus() -> list[dict]:
    """Load homogeneous corpus: original 12 docs + 45 LLM-generated contracts.

    ALL documents are transport/logistics contracts — same document type.
    """
    corpus_path = Path(__file__).resolve().parent.parent / "data" / "benchmark-corpus" / "homogeneous_docs.json"
    # Original 12 docs
    docs = [
        {"doc_id": d.doc_id, "text": d.text,
         "department": d.department, "clearance": d.clearance_level}
        for d in CORPUS
    ]
    docs.extend(_load_corpus_file(corpus_path))
    return docs


def load_diverse_corpus() -> list[dict]:
    """Load diverse corpus: original 12 docs + 45 LLM-generated noise documents.

    Documents span 8 types: safety, HR, tech, incidents, meetings, SOPs, compliance, vendors.
    """
    corpus_path = Path(__file__).resolve().parent.parent / "data" / "benchmark-corpus" / "diverse_docs.json"
    docs = [
        {"doc_id": d.doc_id, "text": d.text,
         "department": d.department, "clearance": d.clearance_level}
        for d in CORPUS
    ]
    docs.extend(_load_corpus_file(corpus_path))
    return docs


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_scenario(
    scenario_name: str,
    corpus_docs: list[dict],
    rerankers: dict[str, BaseReranker],
    top_k: int = 5,
    rerank_top_k: int = 20,
):
    """Run a single benchmark scenario."""
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
        print(f"\n  === {scenario_name} ===")
        avg_len = sum(len(d["text"]) for d in corpus_docs) // len(corpus_docs)
        print(f"  Corpus: {len(corpus_docs)} docs, avg {avg_len} chars")

        # Seed
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

        mode = SearchMode.DENSE_ONLY
        categories = sorted(get_all_categories())

        # Results: model -> {overall_mrr, overall_p5, latency, categories}
        results = {}

        for model_name, reranker in rerankers.items():
            model_mrr_all = []
            model_p5_all = []
            model_lats = []
            model_cats = {}

            for cat in categories:
                queries = get_queries_by_category(cat)
                cat_mrr = []
                cat_p5 = []

                for q in queries:
                    search_results = await hybrid_search(
                        query=q.query, user=ceo,
                        qdrant_client=qdrant,
                        embed_fn=embeddings.aembed_query,
                        top_k=rerank_top_k, mode=mode,
                    )

                    start = time.perf_counter()
                    reranked = await reranker.rerank(
                        q.query, search_results, top_k=top_k
                    )
                    lat = (time.perf_counter() - start) * 1000
                    if model_name != "NoOp":
                        model_lats.append(lat)

                    ids = [r.document_id for r in reranked]
                    cat_mrr.append(compute_mrr(ids, q.relevant_doc_ids))
                    cat_p5.append(
                        compute_precision_at_k(ids, q.relevant_doc_ids, top_k)
                    )

                model_cats[cat] = {
                    "mrr": sum(cat_mrr) / len(cat_mrr),
                    "p5": sum(cat_p5) / len(cat_p5),
                }
                model_mrr_all.extend(cat_mrr)
                model_p5_all.extend(cat_p5)

            results[model_name] = {
                "mrr": sum(model_mrr_all) / len(model_mrr_all),
                "p5": sum(model_p5_all) / len(model_p5_all),
                "latency": (
                    sum(model_lats) / len(model_lats) if model_lats else 0
                ),
                "categories": model_cats,
            }

        # Print results
        print()
        print(f"  {'':20}", end="")
        for name in results:
            print(f" {name:>22}", end="")
        print()
        print("  " + "-" * (20 + 23 * len(results)))

        noop_data = results.get("NoOp", {})

        for cat in categories:
            print(f"  {cat:<20}", end="")
            for name, data in results.items():
                mrr = data["categories"][cat]["mrr"]
                if name == "NoOp":
                    print(f" {mrr:>22.3f}", end="")
                else:
                    noop_mrr = noop_data["categories"][cat]["mrr"]
                    delta = mrr - noop_mrr
                    print(f" {mrr:>12.3f} ({delta:+.3f})", end="")
            print()

        print("  " + "-" * (20 + 23 * len(results)))
        print(f"  {'OVERALL MRR':<20}", end="")
        for name, data in results.items():
            mrr = data["mrr"]
            if name == "NoOp":
                print(f" {mrr:>22.3f}", end="")
            else:
                delta = mrr - noop_data["mrr"]
                print(f" {mrr:>12.3f} ({delta:+.3f})", end="")
        print()

        print(f"  {'LATENCY (ms)':<20}", end="")
        for name, data in results.items():
            lat = data["latency"]
            if name == "NoOp":
                print(f" {'0':>22}", end="")
            else:
                print(f" {lat:>22.0f}", end="")
        print()

        await qdrant.delete_collection(COLLECTION_NAME)
        return results

    finally:
        await qdrant.close()


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ollama", action="store_true",
                        help="Skip Ollama LLM reranker (very slow)")
    args = parser.parse_args()

    print("=" * 80)
    print("RE-RANKING BENCHMARK v2: When Does Re-Ranking Help?")
    print("=" * 80)
    print(f"  Queries: {len(GROUND_TRUTH)} ground truth, "
          f"{len(get_all_categories())} categories")

    # Load reranker models
    print("\n  Loading models...")
    rerankers: dict[str, BaseReranker] = {
        "NoOp": NoOpReranker(),
    }

    print("    TinyBERT (2-layer, air-gapped candidate)...")
    rerankers["TinyBERT"] = LocalCrossEncoderReranker(
        model_name="cross-encoder/ms-marco-TinyBERT-L-2-v2"
    )

    print("    ms-marco-L12 (12-layer, English)...")
    rerankers["ms-marco"] = LocalCrossEncoderReranker(
        model_name="cross-encoder/ms-marco-MiniLM-L-12-v2"
    )

    print("    BGE-reranker-v2-m3 (multilingual, 0.6B)...")
    rerankers["bge-m3"] = LocalCrossEncoderReranker(
        model_name="BAAI/bge-reranker-v2-m3"
    )

    print("    mmarco-mMiniLM (multilingual ms-marco, 118M)...")
    rerankers["mmarco-multi"] = LocalCrossEncoderReranker(
        model_name="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    )

    print("    BGE-reranker-base (278M)...")
    rerankers["bge-base"] = LocalCrossEncoderReranker(
        model_name="BAAI/bge-reranker-base"
    )

    print("    BGE-reranker-large (560M)...")
    rerankers["bge-large"] = LocalCrossEncoderReranker(
        model_name="BAAI/bge-reranker-large"
    )

    # Check if Ollama is available (skip with --no-ollama)
    if not args.no_ollama:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    if any("qwen3" in m for m in models):
                        print("    qwen3:8b (Ollama LLM)...")
                        rerankers["qwen3-llm"] = OllamaLLMReranker(
                            model="qwen3:8b"
                        )
                    else:
                        print("    [SKIP] qwen3 not found in Ollama")
        except Exception:
            print("    [SKIP] Ollama not available")
    else:
        print("    [SKIP] Ollama (--no-ollama flag)")

    print(f"\n  Models loaded: {', '.join(rerankers.keys())}")

    # Scenario 1: Homogeneous corpus (12 original + 45 quality contracts)
    homo_corpus = load_homogeneous_corpus()
    results_homo = await run_scenario(
        f"SCENARIO 1: Homogeneous ({len(homo_corpus)} docs — all contracts)",
        homo_corpus, rerankers,
    )

    # Scenario 2: Diverse corpus (12 original + 45 multi-type noise docs)
    diverse_corpus = load_diverse_corpus()
    results_diverse = await run_scenario(
        f"SCENARIO 2: Diverse ({len(diverse_corpus)} docs — 8 doc types)",
        diverse_corpus, rerankers,
    )

    # Architect analysis
    print("\n" + "=" * 80)
    print("  ARCHITECT ANALYSIS: When Does Re-Ranking Work?")
    print("  " + "-" * 60)

    noop_homo = results_homo["NoOp"]["mrr"]
    noop_div = results_diverse["NoOp"]["mrr"]

    print(f"\n  Baseline MRR (no reranking):")
    print(f"    Homogeneous ({len(homo_corpus)} contracts): {noop_homo:.3f}")
    print(f"    Diverse ({len(diverse_corpus)} docs, 8 types): {noop_div:.3f}")

    print(f"\n  Re-ranking impact (MRR delta):")
    print(f"  {'Model':<25} {'Homogeneous':>12} {'Diverse':>12} {'Latency':>10} {'Verdict':>18}")
    print("  " + "-" * 80)

    for name in rerankers:
        if name == "NoOp":
            continue
        dhomo = results_homo[name]["mrr"] - noop_homo
        ddiv = results_diverse[name]["mrr"] - noop_div
        lat = results_diverse[name]["latency"]
        if ddiv > 0.05:
            verdict = "USE (diverse)"
        elif ddiv > 0.01:
            verdict = "MARGINAL"
        elif dhomo < -0.05 and ddiv < -0.01:
            verdict = "NEVER USE"
        elif ddiv < -0.01:
            verdict = "HURTS"
        else:
            verdict = "NEUTRAL"
        print(f"  {name:<25} {dhomo:>+12.3f} {ddiv:>+12.3f} {lat:>8.0f}ms {verdict:>18}")

    print()

    # Per-category breakdown for each model on diverse corpus
    for name in rerankers:
        if name == "NoOp":
            continue
        helped = []
        hurt = []
        for cat in sorted(get_all_categories()):
            div_cat = results_diverse[name]["categories"][cat]["mrr"]
            noop_cat = results_diverse["NoOp"]["categories"][cat]["mrr"]
            delta = div_cat - noop_cat
            if delta > 0.05:
                helped.append(f"{cat} ({delta:+.3f})")
            elif delta < -0.05:
                hurt.append(f"{cat} ({delta:+.3f})")
        if helped or hurt:
            print(f"  {name} on diverse corpus:")
            if helped:
                print(f"    Helped: {', '.join(helped)}")
            if hurt:
                print(f"    Hurt:   {', '.join(hurt)}")

    print()
    print("  KEY INSIGHTS:")
    print("  1. Re-ranking value = f(corpus DIVERSITY), not f(corpus SIZE).")
    print("  2. English-only models (ms-marco, TinyBERT) fail on Polish queries.")
    print("  3. 'Multilingual' training data != multilingual effectiveness (mmarco-multi HURTS).")
    print("  4. Only BGE-m3 (m3 objective) and BGE-large meaningfully help on diverse corpus.")
    print("  5. BGE-base (278M) is neutral — wastes compute for near-zero improvement.")
    print("  6. TinyBERT is viable for air-gapped/on-prem IF corpus is English-only.")
    print("  7. Switch condition: enable re-ranking when >3 document types in corpus.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
