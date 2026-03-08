"""CLI evaluation runner for RAG quality assessment.

Runs the evaluation pipeline against the ground truth dataset
and reports context_precision, faithfulness, answer_relevancy.

Usage:
    uv run python scripts/run_evaluation.py
    uv run python scripts/run_evaluation.py --threshold 0.85
    uv run python scripts/run_evaluation.py --dataset tests/evaluation/eval_dataset.json

CI integration:
    Exit code 0 = quality gate passed
    Exit code 1 = quality gate failed
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.evaluation.llm_judge import run_eval_pipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run RAG quality evaluation pipeline"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="tests/evaluation/eval_dataset.json",
        help="Path to evaluation dataset JSON",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Quality gate threshold (default: 0.8)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of entries to evaluate (0 = all)",
    )
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"ERROR: Dataset not found: {dataset_path}")
        sys.exit(1)

    with open(dataset_path) as f:
        data = json.load(f)

    if args.limit > 0:
        data = data[: args.limit]

    print(f"Running evaluation on {len(data)} Q&A pairs...")
    print(f"Quality gate threshold: {args.threshold}")
    print("-" * 60)

    result = run_eval_pipeline(data)

    print("\nResults:")
    print(f"  Context Precision:  {result.context_precision:.4f}")
    print(f"  Faithfulness:       {result.faithfulness:.4f}")
    print(f"  Answer Relevancy:   {result.answer_relevancy:.4f}")
    print(f"  Dataset Size:       {result.dataset_size}")
    print(f"  Evaluated At:       {result.evaluated_at.isoformat()}")
    print("-" * 60)

    passed = result.passes_quality_gate(threshold=args.threshold)
    if passed:
        print(f"PASSED: All metrics above {args.threshold}")
        sys.exit(0)
    else:
        print(f"FAILED: One or more metrics below {args.threshold}")
        if result.context_precision <= args.threshold:
            print(f"  - context_precision {result.context_precision:.4f}"
                  f" <= {args.threshold}")
        if result.faithfulness <= args.threshold:
            print(f"  - faithfulness {result.faithfulness:.4f}"
                  f" <= {args.threshold}")
        if result.answer_relevancy <= args.threshold:
            print(f"  - answer_relevancy {result.answer_relevancy:.4f}"
                  f" <= {args.threshold}")
        sys.exit(1)


if __name__ == "__main__":
    main()
