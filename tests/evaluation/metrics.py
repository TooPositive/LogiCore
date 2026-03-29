"""Retrieval quality metrics: precision@k, recall@k, MRR.

Shared module used by both the automated quality gate tests
and the benchmark scripts. No external dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from tests.evaluation.ground_truth import GroundTruthQuery


def compute_precision_at_k(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
    k: int,
) -> float:
    """Precision@k = (relevant docs in top-k) / k.

    Measures how many of the top-k results are actually relevant.
    """
    if k <= 0 or not relevant_doc_ids:
        return 0.0

    top_k = retrieved_doc_ids[:k]
    relevant_set = set(relevant_doc_ids)
    hits = sum(1 for doc_id in top_k if doc_id in relevant_set)
    return hits / k


def compute_recall_at_k(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
    k: int,
) -> float:
    """Recall@k = (relevant docs in top-k) / total relevant docs.

    Measures what fraction of all relevant docs appear in top-k results.
    """
    if not relevant_doc_ids or k <= 0:
        return 0.0

    top_k = retrieved_doc_ids[:k]
    relevant_set = set(relevant_doc_ids)
    hits = sum(1 for doc_id in top_k if doc_id in relevant_set)
    return hits / len(relevant_doc_ids)


def compute_mrr(
    retrieved_doc_ids: list[str],
    relevant_doc_ids: list[str],
) -> float:
    """Mean Reciprocal Rank = 1 / rank of first relevant result.

    If no relevant result is found, returns 0.0.
    """
    if not retrieved_doc_ids or not relevant_doc_ids:
        return 0.0

    relevant_set = set(relevant_doc_ids)
    for i, doc_id in enumerate(retrieved_doc_ids):
        if doc_id in relevant_set:
            return 1.0 / (i + 1)
    return 0.0


# ---------------------------------------------------------------------------
# Aggregate results
# ---------------------------------------------------------------------------


@dataclass
class RetrievalEvalResult:
    """Aggregated retrieval quality metrics."""

    mean_precision_at_k: float
    mean_recall_at_k: float
    mean_mrr: float
    total_queries: int
    k: int
    per_category: dict[str, RetrievalEvalResult] = field(default_factory=dict)


def run_evaluation(
    queries: list[GroundTruthQuery],
    search_fn: Callable[[str], list[str]],
    k: int = 5,
) -> RetrievalEvalResult:
    """Run retrieval quality checks across a set of ground truth queries.

    Args:
        queries: List of ground truth queries with expected relevant doc IDs.
        search_fn: Function that takes a query string and returns a list of
                   retrieved document IDs (ordered by relevance).
        k: Top-k to measure precision and recall at.

    Returns:
        RetrievalEvalResult with aggregate and per-category metrics.
    """
    if not queries:
        return RetrievalEvalResult(
            mean_precision_at_k=0.0,
            mean_recall_at_k=0.0,
            mean_mrr=0.0,
            total_queries=0,
            k=k,
        )

    # Collect per-query metrics
    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []

    # Group by category
    category_data: dict[str, list[tuple[float, float, float]]] = {}

    for q in queries:
        retrieved = search_fn(q.query)

        p = compute_precision_at_k(retrieved, q.relevant_doc_ids, k)
        r = compute_recall_at_k(retrieved, q.relevant_doc_ids, k)
        m = compute_mrr(retrieved, q.relevant_doc_ids)

        precisions.append(p)
        recalls.append(r)
        mrrs.append(m)

        if q.category not in category_data:
            category_data[q.category] = []
        category_data[q.category].append((p, r, m))

    # Build per-category results
    per_category: dict[str, RetrievalEvalResult] = {}
    for cat, metrics_list in category_data.items():
        cat_p = [m[0] for m in metrics_list]
        cat_r = [m[1] for m in metrics_list]
        cat_m = [m[2] for m in metrics_list]
        per_category[cat] = RetrievalEvalResult(
            mean_precision_at_k=sum(cat_p) / len(cat_p),
            mean_recall_at_k=sum(cat_r) / len(cat_r),
            mean_mrr=sum(cat_m) / len(cat_m),
            total_queries=len(metrics_list),
            k=k,
        )

    return RetrievalEvalResult(
        mean_precision_at_k=sum(precisions) / len(precisions),
        mean_recall_at_k=sum(recalls) / len(recalls),
        mean_mrr=sum(mrrs) / len(mrrs),
        total_queries=len(queries),
        k=k,
        per_category=per_category,
    )
