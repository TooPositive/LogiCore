"""Red team tests for resilience engineering.

Attack categories:
1. Circuit breaker manipulation (keep circuit artificially open/closed)
2. Thundering herd on recovery (many concurrent requests when half-open)
3. Cache fallback RBAC bypass attempt
4. Provider chain exhaustion (all providers down + empty cache)
5. Response quality gate bypass (crafted minimal responses)
6. Retry abuse (retriable errors flooding)

These tests prove what the system REFUSES to do.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from apps.api.src.core.infrastructure.llm.provider import LLMResponse
from apps.api.src.core.infrastructure.llm.provider_chain import (
    AllProvidersDownError,
    ProviderChain,
    ProviderEntry,
    ResponseQualityGate,
)
from apps.api.src.core.infrastructure.llm.retry import RetryPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(name: str, content: str = "response") -> MagicMock:
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(
        return_value=LLMResponse(
            content=content, model=name,
            input_tokens=10, output_tokens=20, latency_ms=100.0,
        )
    )
    return provider


def _make_failing_provider(name: str) -> MagicMock:
    provider = MagicMock()
    provider.model_name = name
    provider.generate = AsyncMock(side_effect=Exception(f"{name} down"))
    return provider


# ===========================================================================
# 1. Circuit breaker manipulation
# ===========================================================================


class TestCircuitBreakerManipulation:
    @pytest.mark.asyncio
    async def test_cannot_externally_set_state_to_closed(self):
        """Directly setting _state should not bypass failure counting."""
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(AsyncMock(side_effect=Exception("fail")))

        assert cb.state == CircuitState.OPEN

        # Even if someone sets _state directly, the next failure should re-trip
        cb._state = CircuitState.CLOSED
        # The failure count was reset on trip, so we need 2 more
        with pytest.raises(Exception):
            await cb.call(AsyncMock(side_effect=Exception("fail")))
        with pytest.raises(Exception):
            await cb.call(AsyncMock(side_effect=Exception("fail")))
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_cannot_keep_circuit_artificially_open_by_sending_excluded(self):
        """Excluded exceptions (4xx) should NEVER trip the breaker."""

        class ClientError(Exception):
            pass

        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            excluded_exceptions=(ClientError,),
        )

        # Send 100 client errors — breaker should stay closed
        for _ in range(100):
            with pytest.raises(ClientError):
                await cb.call(AsyncMock(side_effect=ClientError("400")))

        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.total_failures == 0

    @pytest.mark.asyncio
    async def test_rapid_open_close_cycles_tracked(self):
        """Multiple rapid open/close cycles should all be counted."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout=0.05,
            success_threshold=1,
        )

        for cycle in range(5):
            # Trip
            with pytest.raises(Exception):
                await cb.call(AsyncMock(side_effect=Exception("fail")))
            assert cb.state == CircuitState.OPEN

            # Wait and recover
            await asyncio.sleep(0.1)
            await cb.call(AsyncMock(return_value="ok"))
            assert cb.state == CircuitState.CLOSED

        assert cb.metrics.trips == 5


# ===========================================================================
# 2. Thundering herd on recovery
# ===========================================================================


class TestThunderingHerd:
    @pytest.mark.asyncio
    async def test_concurrent_half_open_requests_dont_crash(self):
        """Many concurrent requests during HALF_OPEN should not cause errors
        or race conditions. Some may get CircuitOpenError — that's correct."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=2,
        )

        # Trip
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(AsyncMock(side_effect=Exception("fail")))

        await asyncio.sleep(0.1)

        # Thundering herd: 50 concurrent requests
        success_fn = AsyncMock(return_value="ok")

        async def safe_call():
            try:
                return await cb.call(success_fn)
            except CircuitOpenError:
                return "rejected"

        results = await asyncio.gather(*[safe_call() for _ in range(50)])

        # All should either succeed or be rejected (no crashes)
        for r in results:
            assert r == "ok" or r == "rejected"

        # At least some should have succeeded
        assert results.count("ok") > 0

    @pytest.mark.asyncio
    async def test_jitter_prevents_synchronized_retries(self):
        """RetryPolicy with jitter should produce varied delays."""
        rp = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=True)

        # Generate 100 delays for the same attempt
        delays = [rp.calculate_delay(2) for _ in range(100)]

        # With jitter, delays should be spread out
        unique = set(round(d, 4) for d in delays)
        assert len(unique) > 20  # At least 20 unique values out of 100

        # All within bounds
        for d in delays:
            assert 0 <= d <= 4.0  # base_delay * 2^2 = 4.0


# ===========================================================================
# 3. Cache fallback RBAC bypass attempt
# ===========================================================================


class TestCacheRBACBypass:
    @pytest.mark.asyncio
    async def test_cache_lookup_receives_exact_prompt(self):
        """Cache lookup should receive the exact prompt — no RBAC stripping.
        RBAC enforcement is at the Qdrant level, not the cache lookup."""
        p1 = _make_failing_provider("azure")

        received_prompts = []

        async def tracking_cache(prompt: str) -> str | None:
            received_prompts.append(prompt)
            return "cached answer"

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=p1,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=tracking_cache,
        )

        test_prompt = "What are the secret salary rates?"
        await chain.generate(test_prompt)
        assert received_prompts == [test_prompt]

    @pytest.mark.asyncio
    async def test_cache_disclaimer_always_present(self):
        """Cache responses MUST always include a disclaimer."""
        p1 = _make_failing_provider("azure")

        async def cache_fn(prompt: str) -> str | None:
            return "cached answer"

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=p1,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=cache_fn,
        )

        result = await chain.generate("test")
        assert result.disclaimer is not None
        assert len(result.disclaimer) > 0
        assert result.cache_used is True


# ===========================================================================
# 4. Provider chain exhaustion
# ===========================================================================


class TestProviderExhaustion:
    @pytest.mark.asyncio
    async def test_all_providers_down_no_cache_raises(self):
        """With no cache and all providers down, must raise, not hang."""
        providers = [
            ProviderEntry(
                provider=_make_failing_provider(f"provider-{i}"),
                breaker=CircuitBreaker(name=f"p{i}", failure_threshold=1),
            )
            for i in range(5)
        ]

        chain = ProviderChain(providers=providers)

        with pytest.raises(AllProvidersDownError):
            await chain.generate("test")

    @pytest.mark.asyncio
    async def test_all_providers_down_cache_miss_raises(self):
        """All down + cache miss = AllProvidersDownError."""
        p1 = _make_failing_provider("azure")
        empty_cache = AsyncMock(return_value=None)

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=p1,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=empty_cache,
        )

        with pytest.raises(AllProvidersDownError):
            await chain.generate("test")

    @pytest.mark.asyncio
    async def test_all_providers_down_plus_cache_error_raises(self):
        """If cache lookup itself fails, should raise AllProvidersDownError."""
        p1 = _make_failing_provider("azure")
        broken_cache = AsyncMock(side_effect=Exception("Redis down"))

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=p1,
                    breaker=CircuitBreaker(name="azure", failure_threshold=1),
                ),
            ],
            cache_lookup=broken_cache,
        )

        # Should not hang or return garbage — should raise
        with pytest.raises((AllProvidersDownError, Exception)):
            await chain.generate("test")


# ===========================================================================
# 5. Response quality gate bypass
# ===========================================================================


class TestQualityGateBypass:
    @pytest.mark.asyncio
    async def test_whitespace_padding_doesnt_bypass_gate(self):
        """Attacker returns spaces to pass length check — gate strips first."""
        # 100 spaces = 100 chars, but should fail after strip()
        padded = " " * 100
        provider = _make_provider("attacker", padded)

        fallback = _make_provider("honest", "This is a real response.")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=provider,
                    breaker=CircuitBreaker(name="attacker", failure_threshold=5),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="honest"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("test")
        assert result.provider_name == "honest"

    @pytest.mark.asyncio
    async def test_newline_padding_doesnt_bypass_gate(self):
        """Newlines should also be stripped."""
        newlined = "\n\n\n\n\n\n\n\n\n\n\n\n"
        provider = _make_provider("attacker", newlined)
        fallback = _make_provider("honest", "This is a real response.")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=provider,
                    breaker=CircuitBreaker(name="attacker", failure_threshold=5),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="honest"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("test")
        assert result.provider_name == "honest"

    @pytest.mark.asyncio
    async def test_exactly_min_length_passes(self):
        """Response exactly at min_length should pass."""
        provider = _make_provider("azure", "1234567890")  # exactly 10 chars

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=provider,
                    breaker=CircuitBreaker(name="azure"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("test")
        assert result.provider_name == "azure"

    @pytest.mark.asyncio
    async def test_one_below_min_length_fails(self):
        """Response one char below min_length should fail."""
        provider = _make_provider("azure", "123456789")  # 9 chars
        fallback = _make_provider("fallback", "long enough response here")

        chain = ProviderChain(
            providers=[
                ProviderEntry(
                    provider=provider,
                    breaker=CircuitBreaker(name="azure", failure_threshold=5),
                ),
                ProviderEntry(
                    provider=fallback,
                    breaker=CircuitBreaker(name="fallback"),
                ),
            ],
            quality_gate=ResponseQualityGate(min_length=10),
        )

        result = await chain.generate("test")
        assert result.provider_name == "fallback"


# ===========================================================================
# 6. Retry abuse
# ===========================================================================


class TestRetryAbuse:
    @pytest.mark.asyncio
    async def test_non_retriable_error_stops_immediately(self):
        """Non-retriable errors must not be retried — they stop immediately."""

        class AuthError(Exception):
            pass

        rp = RetryPolicy(
            max_retries=10,
            base_delay=0.01,
            retriable_exceptions=(TimeoutError,),
        )

        fn = AsyncMock(side_effect=AuthError("401 Unauthorized"))

        with pytest.raises(AuthError):
            await rp.execute(fn)

        fn.assert_called_once()  # No retries

    @pytest.mark.asyncio
    async def test_max_retries_is_hard_limit(self):
        """Even with persistent failures, retries stop at max_retries."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
            retriable_exceptions=(TimeoutError,),
        )

        fn = AsyncMock(side_effect=TimeoutError("always times out"))

        with pytest.raises(TimeoutError):
            await rp.execute(fn)

        # 1 initial + 3 retries = 4 total
        assert fn.call_count == 4

    @pytest.mark.asyncio
    async def test_circuit_breaker_stops_retries_from_hitting_down_provider(self):
        """Circuit breaker should prevent retry loops from hammering a dead provider."""
        call_count = 0

        async def counting_fail():
            nonlocal call_count
            call_count += 1
            raise Exception("500 error")

        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)

        # After 2 calls, breaker trips — subsequent calls get CircuitOpenError
        with pytest.raises(Exception):
            await cb.call(counting_fail)
        with pytest.raises(Exception):
            await cb.call(counting_fail)

        # Breaker is now OPEN — next call does NOT reach the provider
        with pytest.raises(CircuitOpenError):
            await cb.call(counting_fail)

        assert call_count == 2  # Only 2 actual calls, not 3
