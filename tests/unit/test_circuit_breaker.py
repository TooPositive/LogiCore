"""Tests for generic CircuitBreaker — state transitions, metrics, error classification.

Generic = works for ANY async callable (LLM providers, rerankers, HTTP clients).
This is the extracted pattern from CircuitBreakerReranker, generalized.

RED phase: all tests written before implementation.
"""

import asyncio
import time

import pytest

from apps.api.src.core.infrastructure.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _success_fn(*args, **kwargs):
    """Always succeeds, returns 'ok'."""
    return "ok"


async def _failure_fn(*args, **kwargs):
    """Always raises a 5xx-equivalent error."""
    raise Exception("server error 500")


async def _timeout_fn(*args, **kwargs):
    """Always raises TimeoutError."""
    raise TimeoutError("request timed out")


class RateLimitError(Exception):
    """Simulates HTTP 429."""
    pass


async def _rate_limit_fn(*args, **kwargs):
    """Always raises rate limit error."""
    raise RateLimitError("429 Too Many Requests")


class ClientError(Exception):
    """Simulates HTTP 4xx (not 429)."""
    pass


async def _client_error_fn(*args, **kwargs):
    """Raises 4xx client error — should NOT count as failure."""
    raise ClientError("400 Bad Request")


# ===========================================================================
# CircuitState enum tests
# ===========================================================================


class TestCircuitState:
    def test_has_three_states(self):
        assert CircuitState.CLOSED == "CLOSED"
        assert CircuitState.OPEN == "OPEN"
        assert CircuitState.HALF_OPEN == "HALF_OPEN"

    def test_all_states_present(self):
        states = list(CircuitState)
        assert len(states) == 3


# ===========================================================================
# CircuitOpenError tests
# ===========================================================================


class TestCircuitOpenError:
    def test_has_provider_name(self):
        err = CircuitOpenError(provider_name="azure-gpt5")
        assert err.provider_name == "azure-gpt5"

    def test_has_time_until_reset(self):
        err = CircuitOpenError(provider_name="azure", time_until_reset=45.0)
        assert err.time_until_reset == 45.0

    def test_str_contains_provider_name(self):
        err = CircuitOpenError(provider_name="azure-gpt5")
        assert "azure-gpt5" in str(err)

    def test_is_exception_subclass(self):
        err = CircuitOpenError(provider_name="test")
        assert isinstance(err, Exception)


# ===========================================================================
# CircuitBreaker — constructor & defaults
# ===========================================================================


class TestCircuitBreakerInit:
    def test_default_state_is_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_default_failure_threshold(self):
        cb = CircuitBreaker(name="test")
        assert cb.failure_threshold == 5

    def test_default_reset_timeout(self):
        cb = CircuitBreaker(name="test")
        assert cb.reset_timeout == 60.0

    def test_default_success_threshold(self):
        cb = CircuitBreaker(name="test")
        assert cb.success_threshold == 3

    def test_custom_thresholds(self):
        cb = CircuitBreaker(
            name="custom",
            failure_threshold=10,
            reset_timeout=120.0,
            success_threshold=5,
        )
        assert cb.failure_threshold == 10
        assert cb.reset_timeout == 120.0
        assert cb.success_threshold == 5

    def test_name_is_stored(self):
        cb = CircuitBreaker(name="azure-gpt5")
        assert cb.name == "azure-gpt5"

    def test_initial_metrics_are_zero(self):
        cb = CircuitBreaker(name="test")
        assert cb.metrics.total_calls == 0
        assert cb.metrics.total_failures == 0
        assert cb.metrics.total_successes == 0
        assert cb.metrics.trips == 0


# ===========================================================================
# CircuitBreaker — CLOSED state
# ===========================================================================


class TestCircuitBreakerClosed:
    @pytest.mark.asyncio
    async def test_call_passes_through_on_success(self):
        cb = CircuitBreaker(name="test")
        result = await cb.call(_success_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_call_passes_args_and_kwargs(self):
        async def echo_fn(a, b, key=None):
            return (a, b, key)

        cb = CircuitBreaker(name="test")
        result = await cb.call(echo_fn, 1, 2, key="val")
        assert result == (1, 2, "val")

    @pytest.mark.asyncio
    async def test_success_increments_metrics(self):
        cb = CircuitBreaker(name="test")
        await cb.call(_success_fn)
        assert cb.metrics.total_calls == 1
        assert cb.metrics.total_successes == 1
        assert cb.metrics.total_failures == 0

    @pytest.mark.asyncio
    async def test_failure_increments_failure_count(self):
        cb = CircuitBreaker(name="test", failure_threshold=10)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        assert cb.metrics.total_failures == 1

    @pytest.mark.asyncio
    async def test_failure_reraises_original_exception(self):
        cb = CircuitBreaker(name="test", failure_threshold=10)
        with pytest.raises(Exception, match="server error 500"):
            await cb.call(_failure_fn)

    @pytest.mark.asyncio
    async def test_timeout_counts_as_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=10)
        with pytest.raises(TimeoutError):
            await cb.call(_timeout_fn)
        assert cb.metrics.total_failures == 1

    @pytest.mark.asyncio
    async def test_rate_limit_counts_as_failure(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=10,
            excluded_exceptions=(ClientError,),
        )
        with pytest.raises(RateLimitError):
            await cb.call(_rate_limit_fn)
        assert cb.metrics.total_failures == 1

    @pytest.mark.asyncio
    async def test_client_error_does_not_count_as_failure(self):
        """4xx errors are caller bugs, not provider failures."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=3,
            excluded_exceptions=(ClientError,),
        )
        with pytest.raises(ClientError):
            await cb.call(_client_error_fn)
        # Should NOT count as failure
        assert cb.metrics.total_failures == 0
        # Should still count as a call
        assert cb.metrics.total_calls == 1

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """A success should reset consecutive failure count."""
        call_count = 0

        async def flaky_fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise Exception("fail")
            return "ok"

        cb = CircuitBreaker(name="test", failure_threshold=5)
        # 2 failures
        with pytest.raises(Exception):
            await cb.call(flaky_fn)
        with pytest.raises(Exception):
            await cb.call(flaky_fn)
        # 1 success - should reset failure count
        result = await cb.call(flaky_fn)
        assert result == "ok"


# ===========================================================================
# CircuitBreaker — CLOSED -> OPEN transition
# ===========================================================================


class TestCircuitBreakerTripping:
    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_does_not_open_below_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(4):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_trips_increments_metric(self):
        cb = CircuitBreaker(name="test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.metrics.trips == 1

    @pytest.mark.asyncio
    async def test_open_state_rejects_calls(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)
        # Trip the breaker
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        # Next call should raise CircuitOpenError, not call the function
        with pytest.raises(CircuitOpenError):
            await cb.call(_success_fn)

    @pytest.mark.asyncio
    async def test_open_error_contains_provider_name(self):
        cb = CircuitBreaker(name="azure-gpt5", failure_threshold=2, reset_timeout=60.0)
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(_success_fn)
        assert exc_info.value.provider_name == "azure-gpt5"

    @pytest.mark.asyncio
    async def test_open_error_contains_time_until_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(_success_fn)
        assert exc_info.value.time_until_reset > 0
        assert exc_info.value.time_until_reset <= 60.0

    @pytest.mark.asyncio
    async def test_mixed_failures_dont_open_prematurely(self):
        """Intermixed successes reset the counter."""
        cb = CircuitBreaker(name="test", failure_threshold=3)

        # fail, fail, success, fail, fail -> counter resets at success
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        await cb.call(_success_fn)  # reset
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)

        # Only 2 consecutive failures since last success, threshold is 3
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_client_errors_dont_trip_breaker(self):
        """4xx errors should not count toward tripping."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            excluded_exceptions=(ClientError,),
        )
        for _ in range(5):
            with pytest.raises(ClientError):
                await cb.call(_client_error_fn)
        assert cb.state == CircuitState.CLOSED


# ===========================================================================
# CircuitBreaker — OPEN -> HALF_OPEN transition
# ===========================================================================


class TestCircuitBreakerHalfOpen:
    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(
            name="test", failure_threshold=2, reset_timeout=0.1
        )
        # Trip
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.state == CircuitState.OPEN

        # Wait for reset timeout
        await asyncio.sleep(0.15)

        # Next call should go through (HALF_OPEN)
        result = await cb.call(_success_fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_stays_open_before_timeout(self):
        cb = CircuitBreaker(
            name="test", failure_threshold=2, reset_timeout=10.0
        )
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        # Don't wait - should still be OPEN
        with pytest.raises(CircuitOpenError):
            await cb.call(_success_fn)


# ===========================================================================
# CircuitBreaker — HALF_OPEN -> CLOSED (recovery)
# ===========================================================================


class TestCircuitBreakerRecovery:
    @pytest.mark.asyncio
    async def test_closes_after_success_threshold(self):
        """Need success_threshold consecutive successes to fully close."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=3,
        )
        # Trip
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)

        await asyncio.sleep(0.1)

        # 3 consecutive successes should close the circuit
        for _ in range(3):
            await cb.call(_success_fn)

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_still_half_open_before_success_threshold(self):
        """If success_threshold=3, after 2 successes we're still HALF_OPEN."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=3,
        )
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)

        await asyncio.sleep(0.1)

        # Only 2 successes, threshold is 3
        await cb.call(_success_fn)
        await cb.call(_success_fn)
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_failure_in_half_open_reopens_circuit(self):
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=3,
        )
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)

        await asyncio.sleep(0.1)

        # One success, then failure -> back to OPEN
        await cb.call(_success_fn)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_failure_in_half_open_resets_success_count(self):
        """After reopening from HALF_OPEN, the success count resets."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=3,
        )
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)

        await asyncio.sleep(0.1)

        # 2 successes, then fail
        await cb.call(_success_fn)
        await cb.call(_success_fn)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)

        # Wait again for next HALF_OPEN
        await asyncio.sleep(0.1)

        # Need full 3 successes again (counter was reset)
        await cb.call(_success_fn)
        await cb.call(_success_fn)
        assert cb.state == CircuitState.HALF_OPEN

        await cb.call(_success_fn)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_multiple_trips_increment_metric(self):
        """Each time circuit opens, trips metric should increment."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=1,
        )
        # Trip 1
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.metrics.trips == 1

        await asyncio.sleep(0.1)

        # Recover
        await cb.call(_success_fn)
        assert cb.state == CircuitState.CLOSED

        # Trip 2
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        assert cb.metrics.trips == 2


# ===========================================================================
# CircuitBreaker — metrics tracking
# ===========================================================================


class TestCircuitBreakerMetrics:
    @pytest.mark.asyncio
    async def test_total_calls_tracks_all(self):
        cb = CircuitBreaker(name="test", failure_threshold=10)
        await cb.call(_success_fn)
        await cb.call(_success_fn)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        assert cb.metrics.total_calls == 3

    @pytest.mark.asyncio
    async def test_open_calls_count_in_total(self):
        """Rejected calls (circuit open) should still count in total_calls."""
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=60.0)
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)
        with pytest.raises(CircuitOpenError):
            await cb.call(_success_fn)
        # 2 failures + 1 rejected = 3 total
        assert cb.metrics.total_calls == 3

    @pytest.mark.asyncio
    async def test_metrics_snapshot_returns_dict(self):
        cb = CircuitBreaker(name="test")
        await cb.call(_success_fn)
        snapshot = cb.metrics_snapshot()
        assert isinstance(snapshot, dict)
        assert "state" in snapshot
        assert "total_calls" in snapshot
        assert "total_failures" in snapshot
        assert "total_successes" in snapshot
        assert "trips" in snapshot
        assert snapshot["state"] == "CLOSED"
        assert snapshot["total_calls"] == 1


# ===========================================================================
# CircuitBreaker — edge cases
# ===========================================================================


class TestCircuitBreakerEdgeCases:
    @pytest.mark.asyncio
    async def test_zero_failure_threshold_trips_immediately(self):
        """Edge case: failure_threshold=1 means one failure trips."""
        cb = CircuitBreaker(name="test", failure_threshold=1, reset_timeout=60.0)
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_threshold_one_closes_immediately(self):
        """Edge case: success_threshold=1 means one success closes."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout=0.05,
            success_threshold=1,
        )
        with pytest.raises(Exception):
            await cb.call(_failure_fn)
        await asyncio.sleep(0.1)
        await cb.call(_success_fn)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_concurrent_calls_in_half_open(self):
        """Multiple concurrent calls when half-open: only probes go through,
        but the circuit should not break (no crash)."""
        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            reset_timeout=0.05,
            success_threshold=2,
        )
        for _ in range(2):
            with pytest.raises(Exception):
                await cb.call(_failure_fn)

        await asyncio.sleep(0.1)

        # Fire multiple concurrent calls
        async def call_success():
            return await cb.call(_success_fn)

        results = await asyncio.gather(
            *[call_success() for _ in range(5)],
            return_exceptions=True,
        )
        # Some might succeed, some might get CircuitOpenError during the
        # transition - but none should crash
        for r in results:
            assert r == "ok" or isinstance(r, CircuitOpenError)

    @pytest.mark.asyncio
    async def test_excluded_exceptions_configurable(self):
        """Can configure which exceptions are excluded from failure count."""

        class CustomNonFailure(Exception):
            pass

        async def custom_error_fn():
            raise CustomNonFailure("not a provider issue")

        cb = CircuitBreaker(
            name="test",
            failure_threshold=2,
            excluded_exceptions=(CustomNonFailure,),
        )
        for _ in range(5):
            with pytest.raises(CustomNonFailure):
                await cb.call(custom_error_fn)
        assert cb.state == CircuitState.CLOSED
        assert cb.metrics.total_failures == 0
