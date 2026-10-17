"""Small builders shared by the tests."""

from datetime import UTC, datetime
from unittest.mock import Mock

import requests

from accountsync.auth import ISO_FORMAT


def stamp(delta):
    """An ``expires_at`` timestamp ``delta`` away from *UTC* now."""
    return (datetime.now(UTC) + delta).strftime(ISO_FORMAT)


def ok_response(payload):
    """A ``requests.Response``-alike that succeeds with ``payload``."""
    resp = Mock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def error_response(status_code):
    """A ``requests.Response``-alike that raises on ``raise_for_status``."""
    resp = Mock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Server Error")
    return resp
