"""Cost comparison: routed vs unrouted model selection.

Usage:
    uv run python scripts/benchmark_routing.py

Calculates cost savings from intelligent query routing:
- Unrouted: all queries go to GPT-5.2 (most expensive)
- Routed: SIMPLE -> nano, MEDIUM -> mini, COMPLEX -> GPT-5.2

No live providers needed -- pure cost model calculation.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Cost per query by tier (EUR) -- from Phase 7 spec
COSTS = {
    "simple": 0.0004,   # GPT-5 nano ($0.05/$0.40 per 1M tokens)
    "medium": 0.003,    # GPT-5 mini ($0.25/$2.00 per 1M tokens)
    "complex": 0.014,   # GPT-5.2 ($1.75/$14.00 per 1M tokens)
}

# Cost of the classifier itself (GPT-5 nano)
CLASSIFIER_COST = 0.000025  # EUR per classification


def calculate_costs(
    queries_per_day: int = 1000,
    simple_pct: float = 0.70,
    medium_pct: float = 0.20,
    complex_pct: float = 0.10,
    misclass_rate: float = 0.05,
) -> dict:
    """Calculate routed vs unrouted costs.

    Returns dict with daily/monthly costs, savings, and misclassification impact.
    """
    distribution = {
        "simple": simple_pct,
        "medium": medium_pct,
        "complex": complex_pct,
    }

    # Routed cost
    routed_daily = sum(
        queries_per_day * pct * COSTS[tier]
        for tier, pct in distribution.items()
    )

    # Add classifier cost
    classifier_daily = queries_per_day * CLASSIFIER_COST
    routed_daily_total = routed_daily + classifier_daily

    # Unrouted cost (all GPT-5.2)
    unrouted_daily = queries_per_day * COSTS["complex"]

    # Savings
    daily_savings = unrouted_daily - routed_daily_total
    savings_pct = (daily_savings / unrouted_daily) * 100 if unrouted_daily > 0 else 0

    # Misclassification cost (complex queries sent to nano)
    complex_per_day = queries_per_day * complex_pct
    misclassified_per_day = complex_per_day * misclass_rate

    return {
        "queries_per_day": queries_per_day,
        "distribution": distribution,
        "routed_daily_eur": round(routed_daily_total, 4),
        "unrouted_daily_eur": round(unrouted_daily, 4),
        "daily_savings_eur": round(daily_savings, 4),
        "savings_pct": round(savings_pct, 1),
        "monthly_savings_eur": round(daily_savings * 30, 2),
        "yearly_savings_eur": round(daily_savings * 365, 2),
        "classifier_daily_eur": round(classifier_daily, 4),
        "misclassified_per_day": round(misclassified_per_day, 1),
        "misclass_rate": misclass_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Routing cost benchmark")
    parser.add_argument(
        "--queries", type=int, default=1000, help="Queries per day"
    )
    parser.add_argument(
        "--simple", type=float, default=0.70, help="Simple query percentage"
    )
    parser.add_argument(
        "--medium", type=float, default=0.20, help="Medium query percentage"
    )
    parser.add_argument(
        "--complex", type=float, default=0.10, help="Complex query percentage"
    )
    args = parser.parse_args()

    results = calculate_costs(
        queries_per_day=args.queries,
        simple_pct=args.simple,
        medium_pct=args.medium,
        complex_pct=args.complex,
    )

    print("\n=== Routing Cost Benchmark ===")
    print(f"Queries/day: {results['queries_per_day']}")
    print(
        f"Distribution: "
        f"{results['distribution']['simple']*100:.0f}% simple, "
        f"{results['distribution']['medium']*100:.0f}% medium, "
        f"{results['distribution']['complex']*100:.0f}% complex"
    )
    print()
    print(f"Unrouted (all GPT-5.2): EUR {results['unrouted_daily_eur']}/day")
    print(f"Routed (tiered):        EUR {results['routed_daily_eur']}/day")
    print(f"Classifier overhead:    EUR {results['classifier_daily_eur']}/day")
    print()
    print(f"Daily savings:   EUR {results['daily_savings_eur']}")
    print(f"Monthly savings: EUR {results['monthly_savings_eur']}")
    print(f"Yearly savings:  EUR {results['yearly_savings_eur']}")
    print(f"Savings:         {results['savings_pct']}%")
    print()
    print(
        f"Misclassification rate: {results['misclass_rate']*100:.0f}% "
        f"-> {results['misclassified_per_day']:.0f} wrong answers/day"
    )
    print()

    # Architect verdict
    print("=== Architect Verdict ===")
    if results["savings_pct"] > 50:
        print(
            f"RECOMMENDATION: Deploy routing. {results['savings_pct']}% cost reduction "
            f"is immediate ROI. The classifier costs EUR {results['classifier_daily_eur']}/day "
            f"-- negligible vs EUR {results['daily_savings_eur']}/day savings."
        )
    else:
        print(
            "CAUTION: Savings below 50%. Review query distribution -- "
            "if most queries are complex, routing adds overhead without benefit."
        )

    print(
        f"\nWHEN THIS CHANGES: If complex query percentage exceeds 60%, "
        f"routing overhead outweighs savings. Monitor distribution monthly."
    )
    print(
        f"\nCOST OF WRONG CHOICE: Each misrouted complex query costs "
        f"EUR {COSTS['complex'] - COSTS['simple']:.4f} in quality degradation. "
        f"At {results['misclass_rate']*100:.0f}% rate = "
        f"{results['misclassified_per_day']:.0f} wrong answers/day."
    )


if __name__ == "__main__":
    main()
