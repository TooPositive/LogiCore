"""Tests for RetryPolicy — exponential backoff with jitter.

RED phase: all tests written before implementation.
"""

from unittest.mock import AsyncMock, patch

import pytest

from apps.api.src.core.infrastructure.llm.retry import RetryPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ServerError(Exception):
    """Simulates 5xx server error."""
    pass


class RateLimitError(Exception):
    """Simulates 429 Too Many Requests."""
    pass


class ClientError(Exception):
    """Simulates 4xx client error — NOT retriable."""
    pass


async def _always_succeeds(*args, **kwargs):
    return "ok"


async def _always_fails(*args, **kwargs):
    raise ServerError("500 Internal Server Error")


# ===========================================================================
# RetryPolicy — constructor & defaults
# ===========================================================================


class TestRetryPolicyInit:
    def test_default_max_retries(self):
        rp = RetryPolicy()
        assert rp.max_retries == 3

    def test_default_base_delay(self):
        rp = RetryPolicy()
        assert rp.base_delay == 1.0

    def test_default_max_delay(self):
        rp = RetryPolicy()
        assert rp.max_delay == 30.0

    def test_default_jitter(self):
        rp = RetryPolicy()
        assert rp.jitter is True

    def test_custom_config(self):
        rp = RetryPolicy(
            max_retries=5,
            base_delay=0.5,
            max_delay=60.0,
            jitter=False,
        )
        assert rp.max_retries == 5
        assert rp.base_delay == 0.5
        assert rp.max_delay == 60.0
        assert rp.jitter is False


# ===========================================================================
# RetryPolicy — backoff calculation
# ===========================================================================


class TestRetryPolicyBackoff:
    def test_exponential_backoff_no_jitter(self):
        """delay = min(base_delay * 2^attempt, max_delay)."""
        rp = RetryPolicy(base_delay=1.0, max_delay=30.0, jitter=False)
        assert rp.calculate_delay(0) == 1.0   # 1 * 2^0 = 1
        assert rp.calculate_delay(1) == 2.0   # 1 * 2^1 = 2
        assert rp.calculate_delay(2) == 4.0   # 1 * 2^2 = 4
        assert rp.calculate_delay(3) == 8.0   # 1 * 2^3 = 8
        assert rp.calculate_delay(4) == 16.0  # 1 * 2^4 = 16

    def test_max_delay_caps_backoff(self):
        rp = RetryPolicy(base_delay=1.0, max_delay=10.0, jitter=False)
        assert rp.calculate_delay(5) == 10.0  # 1 * 2^5 = 32, capped at 10
        assert rp.calculate_delay(10) == 10.0  # capped

    def test_jitter_reduces_delay(self):
        """With jitter, delay is random(0, calculated_delay)."""
        rp = RetryPolicy(base_delay=1.0, max_delay=30.0, jitter=True)
        # Run multiple times — jittered delay should be [0, calculated_delay]
        delays = [rp.calculate_delay(2) for _ in range(100)]
        max_expected = 4.0  # 1 * 2^2 = 4
        for d in delays:
            assert 0.0 <= d <= max_expected

    def test_jitter_distribution_not_constant(self):
        """Jittered delays should vary (not all the same)."""
        rp = RetryPolicy(base_delay=1.0, max_delay=30.0, jitter=True)
        delays = [rp.calculate_delay(3) for _ in range(50)]
        unique_delays = set(delays)
        # With 50 random draws, we should get many unique values
        assert len(unique_delays) > 5

    def test_custom_base_delay(self):
        rp = RetryPolicy(base_delay=0.5, max_delay=30.0, jitter=False)
        assert rp.calculate_delay(0) == 0.5
        assert rp.calculate_delay(1) == 1.0
        assert rp.calculate_delay(2) == 2.0


# ===========================================================================
# RetryPolicy — execute with retries
# ===========================================================================


class TestRetryPolicyExecute:
    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call should not be retried."""
        rp = RetryPolicy(max_retries=3)
        fn = AsyncMock(return_value="result")
        result = await rp.execute(fn)
        assert result == "result"
        fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_args_and_kwargs(self):
        rp = RetryPolicy(max_retries=3)

        async def echo(a, b, key=None):
            return (a, b, key)

        result = await rp.execute(echo, 1, 2, key="val")
        assert result == (1, 2, "val")

    @pytest.mark.asyncio
    async def test_retries_on_retriable_error(self):
        """Should retry on server errors (5xx)."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
            retriable_exceptions=(ServerError,),
        )
        fn = AsyncMock(side_effect=[ServerError("fail"), ServerError("fail"), "ok"])
        result = await rp.execute(fn)
        assert result == "ok"
        assert fn.call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        """TimeoutError should be retriable by default."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
        )
        fn = AsyncMock(side_effect=[TimeoutError("timeout"), "ok"])
        result = await rp.execute(fn)
        assert result == "ok"
        assert fn.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        """If all retries fail, raise the last exception."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            jitter=False,
            retriable_exceptions=(ServerError,),
        )
        fn = AsyncMock(side_effect=ServerError("persistent failure"))
        with pytest.raises(ServerError, match="persistent failure"):
            await rp.execute(fn)
        # Initial call + 3 retries = 4 total
        assert fn.call_count == 4

    @pytest.mark.asyncio
    async def test_does_not_retry_non_retriable(self):
        """Non-retriable errors (4xx) should raise immediately, no retry."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.01,
            retriable_exceptions=(ServerError,),
        )
        fn = AsyncMock(side_effect=ClientError("400 Bad Request"))
        with pytest.raises(ClientError):
            await rp.execute(fn)
        fn.assert_called_once()  # No retries

    @pytest.mark.asyncio
    async def test_zero_retries_just_calls_once(self):
        """max_retries=0 means one attempt, no retries."""
        rp = RetryPolicy(max_retries=0, retriable_exceptions=(ServerError,))
        fn = AsyncMock(side_effect=ServerError("fail"))
        with pytest.raises(ServerError):
            await rp.execute(fn)
        fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_actually_waits(self):
        """Verify that retries actually sleep (mocked)."""
        rp = RetryPolicy(
            max_retries=2,
            base_delay=1.0,
            jitter=False,
            retriable_exceptions=(ServerError,),
        )
        fn = AsyncMock(side_effect=[ServerError("fail"), "ok"])

        with patch("apps.api.src.core.infrastructure.llm.retry.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            result = await rp.execute(fn)
            assert result == "ok"
            # Should have slept once (between attempt 0 and attempt 1)
            mock_sleep.assert_called_once()
            # Delay for attempt 0: base_delay * 2^0 = 1.0
            mock_sleep.assert_called_with(1.0)

    @pytest.mark.asyncio
    async def test_retry_backoff_increases(self):
        """Each retry should wait longer (exponential backoff)."""
        rp = RetryPolicy(
            max_retries=3,
            base_delay=0.5,
            max_delay=30.0,
            jitter=False,
            retriable_exceptions=(ServerError,),
        )
        fn = AsyncMock(side_effect=ServerError("always fails"))

        with patch("apps.api.src.core.infrastructure.llm.retry.asyncio.sleep") as mock_sleep:
            mock_sleep.return_value = None
            with pytest.raises(ServerError):
                await rp.execute(fn)
            # 3 retries = 3 sleeps
            assert mock_sleep.call_count == 3
            delays = [call.args[0] for call in mock_sleep.call_args_list]
            # base * 2^0 = 0.5, base * 2^1 = 1.0, base * 2^2 = 2.0
            assert delays == [0.5, 1.0, 2.0]

    @pytest.mark.asyncio
    async def test_configurable_retriable_exceptions(self):
        """Can add custom exception types as retriable."""

        class CustomRetriableError(Exception):
            pass

        rp = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            retriable_exceptions=(CustomRetriableError,),
        )
        fn = AsyncMock(side_effect=[CustomRetriableError("custom"), "ok"])
        result = await rp.execute(fn)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_rate_limit_retriable_by_default(self):
        """429-type errors should be retriable when included."""
        rp = RetryPolicy(
            max_retries=2,
            base_delay=0.01,
            jitter=False,
            retriable_exceptions=(RateLimitError,),
        )
        fn = AsyncMock(side_effect=[RateLimitError("429"), "ok"])
        result = await rp.execute(fn)
        assert result == "ok"
