#!/usr/bin/env python3
"""Benchmark: Azure OpenAI vs Ollama local inference.

Compares latency (TTFT, total generation), throughput (tokens/sec),
quality (extraction accuracy), and cost per query.

Usage:
    # Compare both providers (requires both Azure credentials and Ollama running)
    uv run python scripts/benchmark_local.py --compare

    # Benchmark Azure only
    uv run python scripts/benchmark_local.py --provider azure

    # Benchmark Ollama only
    uv run python scripts/benchmark_local.py --provider ollama

    # Dry run (mock providers, validates script logic)
    uv run python scripts/benchmark_local.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.core.config.settings import Settings
from apps.api.src.core.infrastructure.llm.provider import get_llm_provider

# -----------------------------------------------------------------------
# Benchmark data
# -----------------------------------------------------------------------

# Test prompts spanning different complexity levels
BENCHMARK_PROMPTS = [
    # Simple (classification/lookup)
    {
        "id": "simple_1",
        "prompt": "What is the capital of Poland?",
        "category": "simple",
        "expected_contains": ["Warsaw", "Warszawa"],
    },
    {
        "id": "simple_2",
        "prompt": "Is 7 a prime number? Answer yes or no.",
        "category": "simple",
        "expected_contains": ["yes", "Yes", "YES"],
    },
    {
        "id": "simple_3",
        "prompt": "Convert 100 EUR to PLN at a rate of 4.3. Return only the number.",
        "category": "simple",
        "expected_contains": ["430"],
    },
    {
        "id": "simple_4",
        "prompt": "What language is spoken in Switzerland? List all official languages.",
        "category": "simple",
        "expected_contains": ["German", "French", "Italian"],
    },
    {
        "id": "simple_5",
        "prompt": "What is the ISO country code for Poland?",
        "category": "simple",
        "expected_contains": ["PL"],
    },
    # Extraction (structured output)
    {
        "id": "extract_1",
        "prompt": (
            "Extract the rate from this text. Return JSON with fields: "
            "rate, currency, unit.\n"
            "Text: 'The transport rate is EUR 0.45 per kilogram for standard cargo.'"
        ),
        "category": "extraction",
        "expected_contains": ["0.45", "EUR", "kilogram"],
    },
    {
        "id": "extract_2",
        "prompt": (
            "Extract invoice details. Return JSON with: invoice_id, amount, currency.\n"
            "Text: 'Invoice INV-2024-001 for EUR 1,250.00 dated 2024-01-15.'"
        ),
        "category": "extraction",
        "expected_contains": ["INV-2024-001", "1250", "EUR"],
    },
    {
        "id": "extract_3",
        "prompt": (
            "Extract the company name and country. Return JSON.\n"
            "Text: 'LogiCore Sp. z o.o. is a Polish logistics company based in Wroclaw.'"
        ),
        "category": "extraction",
        "expected_contains": ["LogiCore", "Pol"],
    },
    {
        "id": "extract_4",
        "prompt": (
            "Extract all temperatures mentioned. Return a JSON array.\n"
            "Text: 'Pharma cargo requires 2-8C. Frozen goods need -18C or below.'"
        ),
        "category": "extraction",
        "expected_contains": ["2", "8", "-18"],
    },
    {
        "id": "extract_5",
        "prompt": (
            "Extract the contract parties. Return JSON with: party_a, party_b.\n"
            "Text: 'This agreement between LogiCore Sp. z o.o. and PharmaCorp SA...'"
        ),
        "category": "extraction",
        "expected_contains": ["LogiCore", "PharmaCorp"],
    },
    # Reasoning (multi-step)
    {
        "id": "reason_1",
        "prompt": (
            "A truck carries 5000 kg at EUR 0.45/kg. The contract has a 10% surcharge "
            "for hazardous materials. What is the total cost? Show your work."
        ),
        "category": "reasoning",
        "expected_contains": ["2475"],
    },
    {
        "id": "reason_2",
        "prompt": (
            "Invoice says EUR 2,500 for 5000 kg. Contract rate is EUR 0.45/kg. "
            "Is there a discrepancy? If so, how much?"
        ),
        "category": "reasoning",
        "expected_contains": ["250"],
    },
    {
        "id": "reason_3",
        "prompt": (
            "A warehouse processes 200 shipments/day. Each takes 15 minutes. "
            "How many workers are needed for a single 8-hour shift?"
        ),
        "category": "reasoning",
        "expected_contains": ["6", "7"],
    },
    {
        "id": "reason_4",
        "prompt": (
            "Cloud AI costs EUR 0.018/query. Local AI costs EUR 1,250/month fixed. "
            "At how many queries per month does local become cheaper?"
        ),
        "category": "reasoning",
        "expected_contains": ["69444", "69445", "69,444", "69,445", "roughly 70"],
    },
    {
        "id": "reason_5",
        "prompt": (
            "A fleet of 50 trucks drives 500 km/day each. Fuel costs EUR 1.50/liter "
            "and trucks use 30 liters per 100 km. What is the daily fuel cost?"
        ),
        "category": "reasoning",
        "expected_contains": ["11250", "11,250"],
    },
]


# -----------------------------------------------------------------------
# Result data structures
# -----------------------------------------------------------------------


@dataclass
class QueryResult:
    """Result of a single benchmark query."""

    prompt_id: str
    category: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    content: str
    expected_found: bool  # Did response contain expected keywords?
    error: str | None = None


@dataclass
class BenchmarkResult:
    """Aggregate results for a provider."""

    provider: str
    model: str
    total_queries: int
    successful_queries: int
    failed_queries: int
    accuracy: float  # Fraction of queries where expected keywords found
    latency_p50_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    tokens_per_sec: float  # Average output tokens / sec
    cost_per_query_eur: float
    results_by_category: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# Cost model
# -----------------------------------------------------------------------

# Azure OpenAI pricing (EUR, approximate)
AZURE_PRICING = {
    "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "gpt-5-mini": {"input_per_1m": 0.25, "output_per_1m": 2.00},
    "gpt-5-nano": {"input_per_1m": 0.05, "output_per_1m": 0.40},
    "gpt-5.2": {"input_per_1m": 1.75, "output_per_1m": 14.00},
}

# Local models: $0/query after hardware amortization
LOCAL_PRICING = {
    "qwen3:8b": {"input_per_1m": 0.00, "output_per_1m": 0.00},
    "qwen3:32b": {"input_per_1m": 0.00, "output_per_1m": 0.00},
    "command-r:35b": {"input_per_1m": 0.00, "output_per_1m": 0.00},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute query cost in EUR."""
    pricing = {**AZURE_PRICING, **LOCAL_PRICING}
    if model not in pricing:
        return 0.0
    p = pricing[model]
    return (
        input_tokens * p["input_per_1m"] / 1_000_000
        + output_tokens * p["output_per_1m"] / 1_000_000
    )


# -----------------------------------------------------------------------
# Benchmark runner
# -----------------------------------------------------------------------


async def run_benchmark(
    provider_name: str,
    settings: Settings,
    prompts: list[dict],
    dry_run: bool = False,
) -> BenchmarkResult:
    """Run benchmark against a single provider."""
    if dry_run:
        return _mock_benchmark(provider_name)

    provider = get_llm_provider(settings)
    model = provider.model_name

    results: list[QueryResult] = []

    for prompt_data in prompts:
        try:
            response = await provider.generate(prompt_data["prompt"])

            expected_found = any(
                kw in response.content
                for kw in prompt_data["expected_contains"]
            )

            results.append(
                QueryResult(
                    prompt_id=prompt_data["id"],
                    category=prompt_data["category"],
                    latency_ms=response.latency_ms,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    content=response.content[:200],  # Truncate for display
                    expected_found=expected_found,
                )
            )
        except Exception as e:
            results.append(
                QueryResult(
                    prompt_id=prompt_data["id"],
                    category=prompt_data["category"],
                    latency_ms=0,
                    input_tokens=0,
                    output_tokens=0,
                    content="",
                    expected_found=False,
                    error=str(e)[:200],
                )
            )

    return _aggregate_results(provider_name, model, results)


def _aggregate_results(
    provider_name: str,
    model: str,
    results: list[QueryResult],
) -> BenchmarkResult:
    """Aggregate individual query results into a benchmark summary."""
    successful = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]

    latencies = [r.latency_ms for r in successful] or [0]
    total_output_tokens = sum(r.output_tokens for r in successful)
    total_time_s = sum(r.latency_ms for r in successful) / 1000

    # Per-category breakdown
    categories: dict[str, dict] = {}
    for r in results:
        if r.category not in categories:
            categories[r.category] = {
                "total": 0,
                "correct": 0,
                "avg_latency_ms": 0,
                "latencies": [],
            }
        cat = categories[r.category]
        cat["total"] += 1
        if r.expected_found:
            cat["correct"] += 1
        if r.error is None:
            cat["latencies"].append(r.latency_ms)

    for cat_data in categories.values():
        lats = cat_data.pop("latencies")
        cat_data["avg_latency_ms"] = statistics.mean(lats) if lats else 0
        cat_data["accuracy"] = (
            cat_data["correct"] / cat_data["total"]
            if cat_data["total"] > 0
            else 0
        )

    total_cost = sum(
        compute_cost(model, r.input_tokens, r.output_tokens)
        for r in successful
    )
    avg_cost = total_cost / len(successful) if successful else 0

    return BenchmarkResult(
        provider=provider_name,
        model=model,
        total_queries=len(results),
        successful_queries=len(successful),
        failed_queries=len(failed),
        accuracy=(
            sum(1 for r in successful if r.expected_found) / len(results)
            if results
            else 0
        ),
        latency_p50_ms=statistics.median(latencies),
        latency_p95_ms=(
            sorted(latencies)[int(len(latencies) * 0.95)]
            if len(latencies) > 1
            else latencies[0]
        ),
        latency_mean_ms=statistics.mean(latencies),
        tokens_per_sec=total_output_tokens / total_time_s if total_time_s > 0 else 0,
        cost_per_query_eur=avg_cost,
        results_by_category=categories,
        errors=[r.error for r in failed if r.error],
    )


def _mock_benchmark(provider_name: str) -> BenchmarkResult:
    """Generate mock results for dry-run mode."""
    is_local = provider_name == "ollama"
    return BenchmarkResult(
        provider=provider_name,
        model="qwen3:8b" if is_local else "gpt-4o",
        total_queries=15,
        successful_queries=15,
        failed_queries=0,
        accuracy=0.87 if is_local else 0.93,
        latency_p50_ms=800 if is_local else 350,
        latency_p95_ms=2200 if is_local else 900,
        latency_mean_ms=950 if is_local else 420,
        tokens_per_sec=35 if is_local else 75,
        cost_per_query_eur=0.0 if is_local else 0.005,
        results_by_category={
            "simple": {
                "total": 5, "correct": 5,
                "accuracy": 1.0,
                "avg_latency_ms": 400 if is_local else 200,
            },
            "extraction": {
                "total": 5, "correct": 4 if is_local else 5,
                "accuracy": 0.8 if is_local else 1.0,
                "avg_latency_ms": 900 if is_local else 400,
            },
            "reasoning": {
                "total": 5, "correct": 3 if is_local else 4,
                "accuracy": 0.6 if is_local else 0.8,
                "avg_latency_ms": 1500 if is_local else 650,
            },
        },
    )


# -----------------------------------------------------------------------
# Output formatting
# -----------------------------------------------------------------------


def print_results(result: BenchmarkResult) -> None:
    """Print benchmark results in a readable table."""
    print(f"\n{'='*60}")
    print(f"  Provider: {result.provider} ({result.model})")
    print(f"{'='*60}")
    print(f"  Queries: {result.successful_queries}/{result.total_queries} successful")
    print(f"  Accuracy: {result.accuracy:.1%}")
    print(f"  Latency p50: {result.latency_p50_ms:.0f} ms")
    print(f"  Latency p95: {result.latency_p95_ms:.0f} ms")
    print(f"  Latency mean: {result.latency_mean_ms:.0f} ms")
    print(f"  Throughput: {result.tokens_per_sec:.1f} tokens/sec")
    print(f"  Cost/query: EUR {result.cost_per_query_eur:.6f}")

    if result.results_by_category:
        print(f"\n  {'Category':<15} {'Accuracy':>10} {'Avg Latency':>12}")
        print(f"  {'-'*15} {'-'*10} {'-'*12}")
        for cat, data in sorted(result.results_by_category.items()):
            print(
                f"  {cat:<15} {data['accuracy']:>9.0%} "
                f"{data['avg_latency_ms']:>10.0f} ms"
            )

    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            print(f"    - {err}")


def print_comparison(azure: BenchmarkResult, ollama: BenchmarkResult) -> None:
    """Print side-by-side comparison with architect framing."""
    print(f"\n{'='*70}")
    print("  COMPARISON: Azure OpenAI vs Ollama (Local)")
    print(f"{'='*70}")

    rows = [
        ("Model", azure.model, ollama.model),
        ("Accuracy", f"{azure.accuracy:.0%}", f"{ollama.accuracy:.0%}"),
        ("Latency p50", f"{azure.latency_p50_ms:.0f} ms", f"{ollama.latency_p50_ms:.0f} ms"),
        ("Latency p95", f"{azure.latency_p95_ms:.0f} ms", f"{ollama.latency_p95_ms:.0f} ms"),
        ("Throughput", f"{azure.tokens_per_sec:.0f} tok/s", f"{ollama.tokens_per_sec:.0f} tok/s"),
        (
            "Cost/query",
            f"EUR {azure.cost_per_query_eur:.6f}",
            f"EUR {ollama.cost_per_query_eur:.6f}",
        ),
    ]

    print(f"\n  {'Metric':<18} {'Azure':>18} {'Ollama':>18}")
    print(f"  {'-'*18} {'-'*18} {'-'*18}")
    for label, azure_val, ollama_val in rows:
        print(f"  {label:<18} {azure_val:>18} {ollama_val:>18}")

    # Architect verdict
    daily_queries = 2400
    daily_azure_cost = daily_queries * azure.cost_per_query_eur
    monthly_azure_cost = daily_azure_cost * 30
    monthly_local_cost = 1250  # Amortized hardware

    print("\n  ARCHITECT VERDICT:")
    print(f"  At {daily_queries} queries/day:")
    print(f"    Azure: EUR {monthly_azure_cost:.0f}/month")
    print(f"    Local: EUR {monthly_local_cost:.0f}/month (amortized hardware)")
    if monthly_local_cost < monthly_azure_cost:
        savings = monthly_azure_cost - monthly_local_cost
        print(f"    Local saves EUR {savings:.0f}/month")
    else:
        premium = monthly_local_cost - monthly_azure_cost
        print(f"    Cloud is EUR {premium:.0f}/month cheaper")
    print("    BUT: if regulatory constraint exists, local is the ONLY option.")

    accuracy_gap = azure.accuracy - ollama.accuracy
    if accuracy_gap > 0:
        print(f"\n  Quality gap: {accuracy_gap:.0%} lower accuracy on local.")
        impact = int(daily_queries * accuracy_gap)
        print(f"  Impact: ~{impact} queries/day may return lower quality results.")
        print("  Recommendation: route complex reasoning to cloud when regulations allow.")
    else:
        print("\n  Quality: local matches or exceeds cloud on this benchmark.")


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Azure OpenAI vs Ollama local inference"
    )
    parser.add_argument(
        "--provider",
        choices=["azure", "ollama", "compare"],
        default="compare",
        help="Which provider to benchmark (default: compare both)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock data instead of real providers",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save results to JSON file",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = Settings()

    results = {}

    if args.provider in ("azure", "compare"):
        print("Running Azure OpenAI benchmark...")
        azure_settings = Settings(
            **{
                **settings.model_dump(),
                "llm_provider": "azure",
            }
        )
        results["azure"] = await run_benchmark(
            "azure", azure_settings, BENCHMARK_PROMPTS, dry_run=args.dry_run
        )
        print_results(results["azure"])

    if args.provider in ("ollama", "compare"):
        print("Running Ollama benchmark...")
        ollama_settings = Settings(
            **{
                **settings.model_dump(),
                "llm_provider": "ollama",
            }
        )
        results["ollama"] = await run_benchmark(
            "ollama", ollama_settings, BENCHMARK_PROMPTS, dry_run=args.dry_run
        )
        print_results(results["ollama"])

    if "azure" in results and "ollama" in results:
        print_comparison(results["azure"], results["ollama"])

    if args.output:
        output_data = {
            name: asdict(result) for name, result in results.items()
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
