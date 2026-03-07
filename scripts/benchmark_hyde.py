"""HyDE benchmark: Compare retrieval with and without HyDE on vague queries.

Ingests the 12-doc corpus into Qdrant, then runs vague + exact_code queries
with and without HyDE query transformation. Measures recall improvement.

Usage:
    python scripts/benchmark_hyde.py

Requires: Qdrant on localhost:6333, Azure OpenAI credentials in .env
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.config.settings import settings
from apps.api.src.domain.document import UserContext
from apps.api.src.infrastructure.qdrant.collections import (
    COLLECTION_NAME,
    DENSE_VECTOR_SIZE,
    ensure_collection,
)
from apps.api.src.rag.embeddings import get_embeddings
from apps.api.src.rag.ingestion import ingest_document
from apps.api.src.rag.retriever import SearchMode, hybrid_search
from tests.evaluation.corpus import CORPUS
from tests.evaluation.ground_truth import get_queries_by_category
from tests.evaluation.metrics import (
    compute_mrr,
    compute_precision_at_k,
    compute_recall_at_k,
)


async def hyde_transform(query: str) -> str:
    """Generate a hypothetical answer using Azure OpenAI gpt-5-mini."""
    import httpx

    endpoint = settings.azure_openai_endpoint.rstrip("/")
    deployment = settings.azure_openai_deployment  # gpt-5-mini
    api_version = settings.azure_openai_api_version
    url = (
        f"{endpoint}/openai/deployments/{deployment}"
        f"/chat/completions?api-version={api_version}"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={
                "api-key": settings.azure_openai_api_key,
                "Content-Type": "application/json",
            },
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Write a short passage (2-3 sentences) that would "
                            "answer the following question about a logistics "
                            "company's documents. Be specific and include "
                            "relevant details."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "max_completion_tokens": 150,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def main():
    from qdrant_client import AsyncQdrantClient

    print("=" * 78)
    print("HyDE BENCHMARK: Vague Queries With/Without HyDE")
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

        # Test categories
        categories = ["vague", "exact_code", "natural_language", "negation"]

        for cat in categories:
            queries = get_queries_by_category(cat)
            print(f"  Category: {cat} ({len(queries)} queries)")
            print(f"  {'Query':<40} {'Mode':<10} {'R@5':>6} {'MRR':>6} {'Lat':>8}")
            print("  " + "-" * 75)

            cat_no_hyde_recall = []
            cat_hyde_recall = []
            cat_no_hyde_mrr = []
            cat_hyde_mrr = []

            for q in queries:
                # Without HyDE
                start = time.perf_counter()
                results_no_hyde = await hybrid_search(
                    query=q.query,
                    user=ceo,
                    qdrant_client=qdrant,
                    embed_fn=embeddings.aembed_query,
                    top_k=top_k,
                    mode=SearchMode.HYBRID,
                )
                lat_no = (time.perf_counter() - start) * 1000
                ids_no = [r.document_id for r in results_no_hyde]
                r_no = compute_recall_at_k(ids_no, q.relevant_doc_ids, top_k)
                m_no = compute_mrr(ids_no, q.relevant_doc_ids)
                cat_no_hyde_recall.append(r_no)
                cat_no_hyde_mrr.append(m_no)

                # With HyDE
                start = time.perf_counter()
                hypothetical = await hyde_transform(q.query)
                results_hyde = await hybrid_search(
                    query=q.query,  # BM25 still uses original
                    user=ceo,
                    qdrant_client=qdrant,
                    embed_fn=lambda text: embeddings.aembed_query(hypothetical),
                    top_k=top_k,
                    mode=SearchMode.HYBRID,
                )
                lat_hy = (time.perf_counter() - start) * 1000
                ids_hy = [r.document_id for r in results_hyde]
                r_hy = compute_recall_at_k(ids_hy, q.relevant_doc_ids, top_k)
                m_hy = compute_mrr(ids_hy, q.relevant_doc_ids)
                cat_hyde_recall.append(r_hy)
                cat_hyde_mrr.append(m_hy)

                q_short = q.query[:38]
                print(
                    f"  {q_short:<40} {'no-HyDE':<10}"
                    f" {r_no:>5.2f} {m_no:>5.2f} {lat_no:>6.0f}ms"
                )
                print(
                    f"  {'':<40} {'HyDE':<10}"
                    f" {r_hy:>5.2f} {m_hy:>5.2f} {lat_hy:>6.0f}ms"
                )

            avg_r_no = sum(cat_no_hyde_recall) / len(cat_no_hyde_recall)
            avg_r_hy = sum(cat_hyde_recall) / len(cat_hyde_recall)
            avg_m_no = sum(cat_no_hyde_mrr) / len(cat_no_hyde_mrr)
            avg_m_hy = sum(cat_hyde_mrr) / len(cat_hyde_mrr)
            delta_r = avg_r_hy - avg_r_no
            delta_m = avg_m_hy - avg_m_no

            print()
            print(f"  {cat} SUMMARY:")
            print(f"    No-HyDE avg: R@5={avg_r_no:.3f}, MRR={avg_m_no:.3f}")
            print(f"    HyDE avg:    R@5={avg_r_hy:.3f}, MRR={avg_m_hy:.3f}")
            pct_r = (delta_r / avg_r_no * 100) if avg_r_no > 0 else 0
            pct_m = (delta_m / avg_m_no * 100) if avg_m_no > 0 else 0
            print(
                f"    Delta:       R@5={delta_r:+.3f} ({pct_r:+.1f}%), "
                f"MRR={delta_m:+.3f} ({pct_m:+.1f}%)"
            )
            print()

        await qdrant.delete_collection(COLLECTION_NAME)

    finally:
        await qdrant.close()

    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
