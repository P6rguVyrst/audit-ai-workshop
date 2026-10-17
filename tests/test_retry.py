"""Tests for accountsync.retry."""

import pytest

from accountsync.retry import TransientError, fetch_with_retry


def test_returns_value_on_first_success():
    result = fetch_with_retry(lambda: {"id": 42}, backoff=0)
    assert result == {"id": 42}


def test_retries_until_success():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TransientError("boom")
        return "ok"

    assert fetch_with_retry(flaky, retries=5, backoff=0) == "ok"
    assert len(calls) == 3


def test_stops_after_retry_limit():
    calls = []

    def always_fails():
        calls.append(1)
        raise TransientError("boom")

    with pytest.raises(TransientError):
        fetch_with_retry(always_fails, retries=3, backoff=0)
    assert len(calls) == 3


def test_exhausted_retries_raise_the_last_transient_error():
    def always_fails():
        raise TransientError("boom")

    with pytest.raises(TransientError):
        fetch_with_retry(always_fails, retries=2, backoff=0)


def test_unexpected_errors_are_not_retried():
    calls = []

    def bad():
        calls.append(1)
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        fetch_with_retry(bad, retries=3, backoff=0)
    assert len(calls) == 1
