"""LLM-as-Judge scoring for RAG quality evaluation.

Mock implementation for CI (no LLM calls). Uses heuristic similarity
scoring to approximate real LLM judge behavior.

For production evaluation with real LLM judges, use scripts/run_evaluation.py
which calls GPT-5-mini or GPT-5.2 as the judge.

Metrics:
- context_precision: are the retrieved chunks relevant to the question?
- faithfulness: does the answer stick to the provided context?
- answer_relevancy: does the answer address the question?
"""

import uuid
from datetime import UTC, datetime

from apps.api.src.core.domain.telemetry import EvalScore


def _word_overlap(text_a: str, text_b: str) -> float:
    """Simple word overlap ratio for mock scoring."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b))


def score_context_precision(
    question: str,
    context: str,
    answer: str,
) -> float:
    """Score how relevant the retrieved context is to the question.

    Mock: uses word overlap between question+answer and context.
    Real: LLM judges whether each context chunk is relevant.
    """
    q_overlap = _word_overlap(question, context)
    a_overlap = _word_overlap(answer, context)
    combined = (q_overlap + a_overlap) / 2
    # Scale: any meaningful overlap indicates relevant context
    return min(1.0, combined * 2.5 + 0.4) if combined > 0.05 else 0.15


def score_faithfulness(
    question: str,
    context: str,
    answer: str,
) -> float:
    """Score whether the answer sticks to the provided context.

    Mock: measures how much of the answer's content appears in the context.
    Hallucinated content (in answer but not in context) reduces the score.
    Real: LLM extracts claims from answer and checks each against context.
    """
    answer_words = set(answer.lower().split())
    context_words = set(context.lower().split())
    question_words = set(question.lower().split())

    if not answer_words:
        return 0.0

    # What fraction of answer words appear in context OR question
    # (question words are fair game since the answer may echo the question)
    grounded_source = context_words | question_words
    grounded = answer_words & grounded_source
    grounded_ratio = len(grounded) / len(answer_words)

    # High grounded ratio = faithful, low = hallucinated
    return min(1.0, grounded_ratio * 1.2 + 0.15)


def score_answer_relevancy(
    question: str,
    answer: str,
) -> float:
    """Score whether the answer addresses the question.

    Mock: word overlap between question and answer, boosted by answer length.
    Real: LLM generates questions from the answer and measures similarity.
    """
    overlap = _word_overlap(question, answer)
    # Longer answers that share question terms are more relevant
    answer_len = len(answer.split())
    length_bonus = min(0.2, answer_len / 100.0)  # up to 0.2 for 20+ words
    if overlap > 0.05:
        return min(1.0, overlap * 2.0 + 0.5 + length_bonus)
    return 0.15


def run_eval_pipeline(
    dataset: list[dict],
) -> EvalScore:
    """Run the full evaluation pipeline on a dataset.

    Args:
        dataset: List of dicts with question, expected_answer, context, category.

    Returns:
        EvalScore with aggregated metrics.
    """
    precisions: list[float] = []
    faithfulness_scores: list[float] = []
    relevancy_scores: list[float] = []

    for entry in dataset:
        question = entry["question"]
        context = entry["context"]
        expected_answer = entry["expected_answer"]

        p = score_context_precision(question, context, expected_answer)
        f = score_faithfulness(question, context, expected_answer)
        r = score_answer_relevancy(question, expected_answer)

        precisions.append(p)
        faithfulness_scores.append(f)
        relevancy_scores.append(r)

    n = len(dataset)
    return EvalScore(
        eval_id=str(uuid.uuid4()),
        context_precision=sum(precisions) / n if n > 0 else 0.0,
        faithfulness=sum(faithfulness_scores) / n if n > 0 else 0.0,
        answer_relevancy=sum(relevancy_scores) / n if n > 0 else 0.0,
        evaluated_at=datetime.now(UTC),
        dataset_size=n,
    )
