"""Generic bounded retry loop with exponential backoff and jitter.

This is the mechanism behind "agents run in a loop when they fail to retrieve
data". Any transient operation (S3 fetch, gateway call, retrieval) is wrapped
so it retries on ``RetryableError`` up to ``max_attempts``, sleeping with
backoff between tries, then re-raises the last error for the caller to turn
into a decision flag.

``sleep`` is injectable so tests run instantly with no real delay.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Iterable, Optional, TypeVar

from .errors import RetryableError

T = TypeVar("T")


class RetryExhausted(RetryableError):
    """Raised when all attempts fail; carries the last underlying error."""

    def __init__(self, attempts: int, last: BaseException):
        super().__init__(f"retry exhausted after {attempts} attempts: {last!r}")
        self.attempts = attempts
        self.last = last


def retry_loop(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    retry_on: Iterable[type[BaseException]] = (RetryableError,),
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random = random.Random(),
) -> T:
    """Call *fn* repeatedly until it succeeds or attempts are exhausted.

    Args:
        fn: zero-arg callable to attempt.
        max_attempts: total attempts (>= 1).
        base_delay/max_delay: exponential backoff bounds (seconds).
        retry_on: exception types that trigger a retry.
        on_retry: optional hook ``(attempt_number, error)`` for logging/metrics.
        sleep: injectable sleeper (tests pass a no-op).

    Returns the successful result, or raises ``RetryExhausted`` whose ``last``
    attribute is the final underlying error.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    retry_types = tuple(retry_on)
    last_err: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except retry_types as err:  # transient -> maybe retry
            last_err = err
            if on_retry is not None:
                on_retry(attempt, err)
            if attempt == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += rng.uniform(0, base_delay)  # jitter to avoid thundering herd
            sleep(delay)
    assert last_err is not None
    raise RetryExhausted(max_attempts, last_err)
