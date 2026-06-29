import pytest

from reimb.errors import DocumentRetrievalError, ReimbError
from reimb.retry import RetryExhausted, retry_loop


def _no_sleep(_):
    return None


def test_succeeds_first_try():
    assert retry_loop(lambda: 42, sleep=_no_sleep) == 42


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise DocumentRetrievalError("transient")
        return "ok"

    assert retry_loop(flaky, max_attempts=3, sleep=_no_sleep) == "ok"
    assert calls["n"] == 3


def test_exhausts_and_wraps_last_error():
    def always_fail():
        raise DocumentRetrievalError("still down")

    with pytest.raises(RetryExhausted) as ei:
        retry_loop(always_fail, max_attempts=2, sleep=_no_sleep)
    assert ei.value.attempts == 2
    assert isinstance(ei.value.last, DocumentRetrievalError)


def test_non_retryable_propagates_immediately():
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry_loop(boom, max_attempts=5, retry_on=(ReimbError,), sleep=_no_sleep)
    assert calls["n"] == 1  # not retried


def test_on_retry_hook_invoked():
    seen = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise DocumentRetrievalError("x")
        return 1

    retry_loop(flaky, max_attempts=3, sleep=_no_sleep,
               on_retry=lambda a, e: seen.append(a))
    assert seen == [1]
