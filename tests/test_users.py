"""Tests for accountsync.users.

Mocks the upstream service so the suite makes no network calls, and patches
``time.sleep`` so the backoff does not slow the tests down.
"""

from unittest.mock import Mock, patch

import pytest
import requests

from accountsync.users import fetch_user


@pytest.fixture(autouse=True)
def no_sleep():
    """Skip the real backoff delays."""
    with patch("accountsync.users.time.sleep") as sleep:
        yield sleep


def ok_response(payload):
    resp = Mock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def error_response(status_code):
    resp = Mock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Server Error")
    return resp


@patch("accountsync.users.requests.get")
def test_returns_parsed_json_on_success(mock_get):
    mock_get.return_value = ok_response({"id": 42, "email": "ada@example.com"})

    assert fetch_user(42) == {"id": 42, "email": "ada@example.com"}


@patch("accountsync.users.requests.get")
def test_calls_the_expected_url_with_a_timeout(mock_get):
    mock_get.return_value = ok_response({"id": 42})

    fetch_user(42)

    mock_get.assert_called_once_with("https://api.example.com/users/42", timeout=5)


@patch("accountsync.users.requests.get")
def test_does_not_retry_on_success(mock_get):
    mock_get.return_value = ok_response({"id": 42})

    fetch_user(42)

    assert mock_get.call_count == 1


@patch("accountsync.users.requests.get")
def test_retries_after_a_connection_error(mock_get):
    mock_get.side_effect = [
        requests.ConnectionError("connection reset by peer"),
        ok_response({"id": 42}),
    ]

    assert fetch_user(42) == {"id": 42}
    assert mock_get.call_count == 2


@patch("accountsync.users.requests.get")
def test_retries_after_a_timeout(mock_get):
    mock_get.side_effect = [
        requests.Timeout("read timed out"),
        requests.Timeout("read timed out"),
        ok_response({"id": 42}),
    ]

    assert fetch_user(42) == {"id": 42}
    assert mock_get.call_count == 3


@patch("accountsync.users.requests.get")
def test_retries_on_http_500(mock_get):
    mock_get.side_effect = [error_response(500), ok_response({"id": 42})]

    assert fetch_user(42) == {"id": 42}
    assert mock_get.call_count == 2


@patch("accountsync.users.requests.get")
def test_gives_up_after_the_retry_limit(mock_get):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42, retries=3)

    assert mock_get.call_count == 3


@patch("accountsync.users.requests.get")
def test_respects_a_custom_retry_count(mock_get):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42, retries=5)

    assert mock_get.call_count == 5


@patch("accountsync.users.requests.get")
def test_backs_off_between_attempts(mock_get, no_sleep):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42, retries=3, backoff=0.5)

    assert [call.args[0] for call in no_sleep.call_args_list] == [0.5, 1.0]


@patch("accountsync.users.requests.get")
def test_retries_must_be_at_least_one(mock_get):
    with pytest.raises(ValueError, match="retries must be >= 1"):
        fetch_user(42, retries=0)

    mock_get.assert_not_called()


@patch("accountsync.users.requests.get")
def test_upstream_outage_raises_instead_of_returning_none(mock_get):
    """A dead upstream is reported, not swallowed into a None return."""
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42)
