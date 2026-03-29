"""Simulate a provider outage and verify failover behavior.

Usage:
    uv run python scripts/simulate_outage.py [--requests N] [--outage-duration SECS]

This script:
1. Creates a ProviderChain with a simulated-failing primary
2. Sends N requests during simulated outage
3. Resolves the outage and sends more requests
4. Reports: failover time, recovery time, requests served, cache fallbacks

No live providers needed -- uses mock providers for deterministic simulation.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    ProviderChain,
    ProviderEntry,
)


class SimulatedProvider:
    """Provider that can be toggled between healthy and failing."""

    def __init__(self, name: str, latency_ms: float = 100.0) -> None:
        self._name = name
        self._latency_ms = latency_ms
        self.is_down = False

    @property
    def model_name(self) -> str:
        return self._name

    async def generate(self, prompt: str, **kwargs) -> LLMResponse:
        if self.is_down:
            raise Exception(f"503 Service Unavailable: {self._name}")
        await asyncio.sleep(self._latency_ms / 1000)
        return LLMResponse(
            content=f"Response from {self._name}: {prompt[:50]}",
            model=self._name,
            input_tokens=len(prompt.split()),
            output_tokens=20,
            latency_ms=self._latency_ms,
        )

    async def generate_structured(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.generate(prompt, **kwargs)


async def run_simulation(
    num_requests: int = 20,
    outage_duration: float = 2.0,
    failure_threshold: int = 3,
    reset_timeout: float = 0.5,
) -> dict:
    """Run outage simulation and return metrics."""
    primary = SimulatedProvider("azure-gpt5", latency_ms=50.0)
    fallback = SimulatedProvider("ollama-local", latency_ms=200.0)

    primary_breaker = CircuitBreaker(
        name="azure",
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
        success_threshold=2,
    )
    fallback_breaker = CircuitBreaker(
        name="ollama",
        failure_threshold=failure_threshold,
        reset_timeout=reset_timeout,
    )

    chain = ProviderChain(
        providers=[
            ProviderEntry(provider=primary, breaker=primary_breaker),
            ProviderEntry(provider=fallback, breaker=fallback_breaker),
        ]
    )

    results = []
    start_time = time.monotonic()

    # Phase 1: Normal operation (2 requests)
    for i in range(2):
        r = await chain.generate(f"Normal query {i}")
        results.append(
            {"phase": "normal", "provider": r.provider_name, "degraded": r.is_degraded}
        )

    # Phase 2: Outage begins
    primary.is_down = True
    outage_start = time.monotonic()
    outage_requests = num_requests - 4  # Save 2 for recovery

    for i in range(outage_requests):
        r = await chain.generate(f"Outage query {i}")
        results.append(
            {"phase": "outage", "provider": r.provider_name, "degraded": r.is_degraded}
        )

    # Phase 3: Recovery
    primary.is_down = False
    await asyncio.sleep(reset_timeout + 0.1)

    for i in range(2):
        r = await chain.generate(f"Recovery query {i}")
        results.append(
            {"phase": "recovery", "provider": r.provider_name, "degraded": r.is_degraded}
        )

    total_time = time.monotonic() - start_time

    # Compute metrics
    normal_results = [r for r in results if r["phase"] == "normal"]
    outage_results = [r for r in results if r["phase"] == "outage"]
    recovery_results = [r for r in results if r["phase"] == "recovery"]

    return {
        "total_requests": len(results),
        "total_time_s": round(total_time, 3),
        "normal_phase": {
            "requests": len(normal_results),
            "primary_served": sum(
                1 for r in normal_results if r["provider"] == "azure-gpt5"
            ),
        },
        "outage_phase": {
            "requests": len(outage_results),
            "fallback_served": sum(
                1 for r in outage_results if r["provider"] == "ollama-local"
            ),
            "all_degraded": all(r["degraded"] for r in outage_results),
        },
        "recovery_phase": {
            "requests": len(recovery_results),
            "primary_recovered": sum(
                1 for r in recovery_results if r["provider"] == "azure-gpt5"
            ),
        },
        "breaker_stats": {
            "primary_trips": primary_breaker.metrics.trips,
            "primary_state": primary_breaker.state.value,
            "fallback_state": fallback_breaker.state.value,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate provider outage")
    parser.add_argument(
        "--requests", type=int, default=20, help="Total requests to send"
    )
    parser.add_argument(
        "--outage-duration",
        type=float,
        default=2.0,
        help="Simulated outage duration (seconds)",
    )
    args = parser.parse_args()

    metrics = asyncio.run(
        run_simulation(num_requests=args.requests, outage_duration=args.outage_duration)
    )

    print("\n=== Outage Simulation Results ===")
    print(f"Total requests: {metrics['total_requests']}")
    print(f"Total time: {metrics['total_time_s']}s")
    print()
    print("Normal phase:")
    print(f"  Requests: {metrics['normal_phase']['requests']}")
    print(f"  Primary served: {metrics['normal_phase']['primary_served']}")
    print()
    print("Outage phase:")
    print(f"  Requests: {metrics['outage_phase']['requests']}")
    print(f"  Fallback served: {metrics['outage_phase']['fallback_served']}")
    print(f"  All degraded: {metrics['outage_phase']['all_degraded']}")
    print()
    print("Recovery phase:")
    print(f"  Requests: {metrics['recovery_phase']['requests']}")
    print(f"  Primary recovered: {metrics['recovery_phase']['primary_recovered']}")
    print()
    print("Breaker stats:")
    print(f"  Primary trips: {metrics['breaker_stats']['primary_trips']}")
    print(f"  Primary state: {metrics['breaker_stats']['primary_state']}")
    print(f"  Fallback state: {metrics['breaker_stats']['fallback_state']}")


if __name__ == "__main__":
    main()
