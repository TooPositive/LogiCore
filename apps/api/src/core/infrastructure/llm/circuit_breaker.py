"""Generic circuit breaker for async callables.

Works for ANY async function: LLM providers, rerankers, HTTP clients,
embedding services. Not tied to any specific domain.

States:
- CLOSED:    Normal operation. Count consecutive failures.
- OPEN:      Reject all calls. Wait for reset_timeout.
- HALF_OPEN: Allow probe requests. Need success_threshold consecutive
             successes to return to CLOSED. Any failure -> OPEN.

Only counts provider-level failures (5xx, timeout, rate limit).
Client errors (4xx) are caller bugs -- excluded via excluded_exceptions.

Metrics tracked: total_calls, total_failures, total_successes, trips.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""

    def __init__(
        self,
        provider_name: str,
        time_until_reset: float = 0.0,
    ) -> None:
        self.provider_name = provider_name
        self.time_until_reset = time_until_reset
        super().__init__(
            f"Circuit breaker is OPEN for '{provider_name}'. "
            f"Retry in {time_until_reset:.1f}s."
        )


@dataclass
class CircuitBreakerMetrics:
    """Metrics tracked by the circuit breaker."""

    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    trips: int = 0


class CircuitBreaker:
    """Generic circuit breaker for any async callable.

    Args:
        name: Identifier for this breaker (e.g., provider name).
        failure_threshold: Consecutive failures before opening circuit.
        reset_timeout: Seconds to wait in OPEN before trying HALF_OPEN.
        success_threshold: Consecutive successes in HALF_OPEN to close.
        excluded_exceptions: Exception types that do NOT count as failures
                             (e.g., client 4xx errors).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 60.0,
        success_threshold: int = 3,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold
        self.excluded_exceptions = excluded_exceptions

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._metrics = CircuitBreakerMetrics()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def metrics(self) -> CircuitBreakerMetrics:
        """Current metrics."""
        return self._metrics

    def metrics_snapshot(self) -> dict[str, Any]:
        """Return a dict snapshot of current state and metrics."""
        return {
            "state": self._state.value,
            "total_calls": self._metrics.total_calls,
            "total_failures": self._metrics.total_failures,
            "total_successes": self._metrics.total_successes,
            "trips": self._metrics.trips,
            "name": self.name,
        }

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute func through the circuit breaker.

        Args:
            func: Async callable to execute.
            *args: Positional args for func.
            **kwargs: Keyword args for func.

        Returns:
            Result from func.

        Raises:
            CircuitOpenError: If circuit is OPEN and reset_timeout hasn't elapsed.
            Exception: Re-raises the original exception from func on failure.
        """
        self._metrics.total_calls += 1

        # OPEN state: check if reset_timeout has elapsed
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.reset_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
            else:
                raise CircuitOpenError(
                    provider_name=self.name,
                    time_until_reset=self.reset_timeout - elapsed,
                )

        # Execute the function
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            if self._is_excluded(exc):
                # Re-raise but don't count as failure
                raise
            self._on_failure()
            raise

    def _is_excluded(self, exc: Exception) -> bool:
        """Check if this exception type is excluded from failure counting."""
        return isinstance(exc, self.excluded_exceptions)

    def _on_success(self) -> None:
        """Handle a successful call."""
        self._metrics.total_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            # CLOSED state: reset failure count
            self._failure_count = 0

    def _on_failure(self) -> None:
        """Handle a failed call."""
        self._metrics.total_failures += 1

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN -> back to OPEN
            self._state = CircuitState.OPEN
            self._last_failure_time = time.monotonic()
            self._success_count = 0
            self._metrics.trips += 1
        else:
            # CLOSED state
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
                self._failure_count = 0
                self._metrics.trips += 1
