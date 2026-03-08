#!/usr/bin/env python3
"""Compute human vs LLM judge Spearman correlation.

Usage:
    python scripts/calibrate_judge.py --golden-set data/golden_set.json
    python scripts/calibrate_judge.py --min-correlation 0.85

Exit codes:
    0 = PASS (correlation >= threshold)
    1 = HALT (correlation < threshold)
    2 = ERROR (invalid data, too few samples)

The golden set JSON format:
[
    {
        "query": "What is the penalty?",
        "context": "...",
        "expected_answer": "15% penalty per incident",
        "human_score": 4.5,
        "judge_score": null  // filled by this script if --run-judge is set
    },
    ...
]
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.telemetry.quality_pipeline import HumanCalibration


def load_golden_set(path: str) -> tuple[list[float], list[float]]:
    """Load human and judge scores from a golden set JSON file.

    Returns:
        Tuple of (human_scores, judge_scores).

    Raises:
        ValueError: If file is missing required fields.
    """
    with open(path) as f:
        data = json.load(f)

    human_scores = []
    judge_scores = []
    for entry in data:
        if "human_score" not in entry or "judge_score" not in entry:
            raise ValueError(
                f"Golden set entry missing required fields: {entry.get('query', 'unknown')}"
            )
        if entry["human_score"] is None or entry["judge_score"] is None:
            continue
        human_scores.append(float(entry["human_score"]))
        judge_scores.append(float(entry["judge_score"]))

    return human_scores, judge_scores


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute judge-human Spearman correlation"
    )
    parser.add_argument(
        "--golden-set",
        type=str,
        default="data/golden_set.json",
        help="Path to golden set JSON file",
    )
    parser.add_argument(
        "--min-correlation",
        type=float,
        default=0.85,
        help="Minimum Spearman correlation threshold (default: 0.85)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="Minimum number of samples required (default: 5)",
    )
    args = parser.parse_args()

    try:
        human_scores, judge_scores = load_golden_set(args.golden_set)
    except FileNotFoundError:
        print(f"ERROR: Golden set file not found: {args.golden_set}")
        return 2
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: Invalid golden set data: {e}")
        return 2

    calibration = HumanCalibration(
        min_correlation=args.min_correlation,
        min_samples=args.min_samples,
    )

    try:
        correlation = calibration.compute_correlation(human_scores, judge_scores)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2

    status = calibration.quality_gate_status(correlation)
    print(f"Spearman correlation: {correlation:.4f}")
    print(f"Threshold: {args.min_correlation:.4f}")
    print(f"Samples: {len(human_scores)}")
    print(f"Status: {status}")

    if status == "PASS":
        print("RESULT: Judge is calibrated. Automated quality gates may proceed.")
        return 0
    else:
        print(
            "RESULT: Judge is NOT calibrated. "
            "HALT all automated quality gates until recalibrated."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
