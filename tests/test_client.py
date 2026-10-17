"""Tests for accountsync.client."""

import json
from unittest.mock import Mock, patch

import pytest
import requests

from accountsync.client import AccountsClient
from accountsync.errors import AuthError, TransientError
from tests.helpers import ok_response


@pytest.fixture(autouse=True)
def no_sleep():
    """Skip the real backoff delays."""
    with patch("accountsync.users.time.sleep"), patch("accountsync.retry.time.sleep"):
        yield


@patch("accountsync.users.requests.get")
def test_get_user_returns_the_payload(mock_get, fresh_token):
    mock_get.return_value = ok_response({"id": 42, "email": "ada@example.com"})

    client = AccountsClient(token=fresh_token)

    assert client.get_user(42) == {"id": 42, "email": "ada@example.com"}


@patch("accountsync.users.requests.get")
def test_get_user_uses_the_configured_retry_count(mock_get, fresh_token):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")
    client = AccountsClient(config={"retries": 5}, token=fresh_token)

    with pytest.raises(requests.RequestException):
        client.get_user(42)

    assert mock_get.call_count == 5


@patch("accountsync.users.requests.get")
def test_list_users_walks_every_page(mock_get, fresh_token):
    mock_get.side_effect = [
        ok_response({"data": [{"id": i} for i in range(10)]}),
        ok_response({"data": [{"id": i} for i in range(10, 17)]}),
    ]
    client = AccountsClient(token=fresh_token)

    users = client.list_users(page_size=10)

    assert [u["id"] for u in users] == list(range(17))
    assert mock_get.call_count == 2


@patch("accountsync.users.requests.get")
def test_sync_users_writes_json(mock_get, tmp_path, fresh_token):
    mock_get.return_value = ok_response({"data": [{"id": 1}, {"id": 2}]})
    destination = tmp_path / "out" / "users.json"

    written = AccountsClient(token=fresh_token).sync_users(destination, page_size=10)

    assert written == 2
    assert json.loads(destination.read_text()) == [{"id": 1}, {"id": 2}]


def test_headers_carry_the_bearer_token(fresh_token):
    headers = AccountsClient(token=fresh_token).headers()

    assert headers["Authorization"] == "Bearer tok-live"
    assert headers["Accept"] == "application/json"


def test_a_fresh_token_is_reused(fresh_token):
    source = Mock()
    client = AccountsClient(token=fresh_token, token_source=source)

    assert client.token is fresh_token
    source.assert_not_called()


def test_an_expired_token_is_refreshed(stale_token, fresh_token):
    source = Mock(
        return_value={
            "access_token": fresh_token.access_token,
            "expires_at": fresh_token.expires_at,
        }
    )
    client = AccountsClient(token=stale_token, token_source=source)

    assert client.token == fresh_token
    assert client.token == fresh_token, "the refreshed token should be cached"
    source.assert_called_once()


def test_refresh_retries_transient_errors(stale_token, fresh_token):
    source = Mock(
        side_effect=[
            TransientError("auth server unavailable"),
            {"access_token": "tok-new", "expires_at": fresh_token.expires_at},
        ]
    )
    client = AccountsClient(token=stale_token, token_source=source)

    assert client.token.access_token == "tok-new"
    assert source.call_count == 2


def test_refresh_without_a_token_source_is_an_auth_error(stale_token):
    client = AccountsClient(token=stale_token)

    with pytest.raises(AuthError):
        _ = client.token


def test_a_malformed_auth_payload_is_an_auth_error(stale_token):
    client = AccountsClient(token=stale_token, token_source=lambda: {"token": "oops"})

    with pytest.raises(AuthError):
        _ = client.token
