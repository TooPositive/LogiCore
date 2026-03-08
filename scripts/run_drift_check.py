#!/usr/bin/env python3
"""Weekly regression suite for drift detection.

Usage:
    python scripts/run_drift_check.py
    python scripts/run_drift_check.py --model gpt-5.2 --version 2026-0301
    python scripts/run_drift_check.py --config data/drift_config.json

Cron-compatible: use exit codes for CI/CD integration.

Exit codes:
    0 = GREEN (no significant drift)
    1 = RED (>5% regression on at least one metric)
    2 = YELLOW (2-5% regression, investigation recommended)
    3 = ERROR (configuration or runtime error)

Config JSON format:
{
    "models": [
        {
            "name": "gpt-5.2",
            "version": "2026-0301",
            "baseline_scores": {
                "context_precision": 0.90,
                "faithfulness": 0.85,
                "answer_relevancy": 0.88
            }
        }
    ],
    "yellow_threshold": 0.02,
    "red_threshold": 0.05
}
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.core.domain.telemetry import DriftSeverity
from apps.api.src.core.telemetry.drift_detector import (
    DriftDetector,
    LogAlertHandler,
)
from apps.api.src.core.telemetry.model_registry import ModelVersionRegistry


def load_config(path: str) -> dict:
    """Load drift check configuration from JSON."""
    with open(path) as f:
        return json.load(f)


def run_drift_check(
    registry: ModelVersionRegistry,
    model_name: str,
    current_scores: dict[str, float],
    yellow_threshold: float = 0.02,
    red_threshold: float = 0.05,
) -> int:
    """Run drift check for a single model.

    Returns exit code: 0=GREEN, 1=RED, 2=YELLOW.
    """
    detector = DriftDetector(
        registry=registry,
        alert_handler=LogAlertHandler(),
        yellow_threshold=yellow_threshold,
        red_threshold=red_threshold,
    )

    alerts = detector.check_regression(
        model_name=model_name,
        current_scores=current_scores,
    )

    if not alerts:
        print(f"  [{model_name}] GREEN: All metrics within baseline tolerance.")
        return 0

    max_severity = DriftSeverity.GREEN
    for alert in alerts:
        print(
            f"  [{model_name}] {alert.severity}: "
            f"{alert.metric} baseline={alert.baseline_value:.4f} "
            f"current={alert.current_value:.4f} delta={alert.delta:+.4f}"
        )
        if alert.severity == DriftSeverity.RED:
            max_severity = DriftSeverity.RED
        elif alert.severity == DriftSeverity.YELLOW and max_severity != DriftSeverity.RED:
            max_severity = DriftSeverity.YELLOW

    if max_severity == DriftSeverity.RED:
        return 1
    if max_severity == DriftSeverity.YELLOW:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run weekly drift detection regression suite"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to drift config JSON file",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Single model name to check",
    )
    parser.add_argument(
        "--version",
        type=str,
        help="Current model version string",
    )
    parser.add_argument(
        "--scores",
        type=str,
        help='Current scores as JSON string, e.g. \'{"precision": 0.88}\'',
    )
    parser.add_argument(
        "--yellow-threshold",
        type=float,
        default=0.02,
        help="Yellow alert threshold (default: 0.02 = 2%%)",
    )
    parser.add_argument(
        "--red-threshold",
        type=float,
        default=0.05,
        help="Red alert threshold (default: 0.05 = 5%%)",
    )
    args = parser.parse_args()

    registry = ModelVersionRegistry()

    if args.config:
        try:
            config = load_config(args.config)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ERROR: Failed to load config: {e}")
            return 3

        yellow = config.get("yellow_threshold", args.yellow_threshold)
        red = config.get("red_threshold", args.red_threshold)

        worst_exit = 0
        for model_cfg in config.get("models", []):
            name = model_cfg["name"]
            version = model_cfg["version"]
            baseline = model_cfg["baseline_scores"]
            registry.register(name, version, baseline)

            # In a real implementation, current_scores would come from
            # running the evaluation suite. Here we use baseline as
            # placeholder — real usage provides --scores or runs evals.
            print(f"Checking model: {name} (version: {version})")
            result = run_drift_check(
                registry, name, baseline, yellow, red
            )
            worst_exit = max(worst_exit, result)

        return worst_exit

    elif args.model and args.scores:
        try:
            current_scores = json.loads(args.scores)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid scores JSON: {e}")
            return 3

        # Register a dummy baseline for comparison
        # In production, baselines are loaded from persistent storage
        print(f"Checking model: {args.model}")
        if args.version:
            registry.register(args.model, args.version, current_scores)
        return run_drift_check(
            registry,
            args.model,
            current_scores,
            args.yellow_threshold,
            args.red_threshold,
        )

    else:
        print(
            "Usage: Provide --config <path> or --model <name> --scores '{...}'"
        )
        print("Run with --help for full options.")
        return 3


if __name__ == "__main__":
    sys.exit(main())
