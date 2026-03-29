"""Retry policy with exponential backoff and jitter.

Domain-agnostic: works for any async callable. Configurable via
constructor parameters (max_retries, base_delay, max_delay, jitter).

Only retries on retriable exceptions (5xx, timeout, 429).
Does NOT retry on 4xx client errors by default.

Full jitter: delay = random(0, min(base_delay * 2^attempt, max_delay))
Prevents thundering herd on recovery.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class RetryPolicy:
    """Retry with exponential backoff and optional jitter.

    Args:
        max_retries: Maximum number of retries (0 = no retries, just 1 attempt).
        base_delay: Base delay in seconds for exponential backoff.
        max_delay: Maximum delay in seconds (caps exponential growth).
        jitter: If True, apply full jitter: random(0, calculated_delay).
        retriable_exceptions: Tuple of exception types to retry on.
                              Defaults to (TimeoutError,).
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        jitter: bool = True,
        retriable_exceptions: tuple[type[Exception], ...] = (TimeoutError,),
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.retriable_exceptions = retriable_exceptions

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number.

        Formula: min(base_delay * 2^attempt, max_delay)
        With jitter: random(0, calculated_delay)
        """
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            delay = random.random() * delay  # noqa: S311
        return delay

    async def execute(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute func with retry logic.

        Args:
            func: Async callable to execute.
            *args: Positional args for func.
            **kwargs: Keyword args for func.

        Returns:
            Result from func.

        Raises:
            The last exception if all retries are exhausted.
            Non-retriable exceptions immediately (no retry).
        """
        last_exception: Exception | None = None

        for attempt in range(1 + self.max_retries):
            try:
                return await func(*args, **kwargs)
            except self.retriable_exceptions as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self.calculate_delay(attempt)
                    logger.warning(
                        "Retry %d/%d for %s after %.2fs: %s",
                        attempt + 1,
                        self.max_retries,
                        getattr(func, "__name__", str(func)),
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception:
                # Non-retriable exception — raise immediately
                raise

        # Should not reach here, but satisfy type checker
        raise last_exception  # type: ignore[misc]
