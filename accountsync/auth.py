"""Access tokens issued by the Accounts API auth server.

The auth server returns ``{"access_token": ..., "expires_at": ...}`` where
``expires_at`` is an ISO-8601 UTC timestamp. :class:`Token` wraps that pair;
:func:`is_expired` is what the client consults before every request.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from accountsync.errors import AuthError

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

#: Refresh this many seconds early rather than racing the expiry.
DEFAULT_SKEW_SECONDS = 30


def parse_expiry(expires_at):
    """Parse an ISO-8601 UTC timestamp such as ``2026-08-30T12:00:00Z``.

    The result is timezone-aware (UTC): a naive datetime would be
    interpreted in the machine's local timezone, making expiry answers
    depend on where the process happens to run.
    """
    return datetime.strptime(expires_at, ISO_FORMAT).replace(tzinfo=UTC)


def is_expired(expires_at, skew_seconds=DEFAULT_SKEW_SECONDS):
    """Return True if the token is expired, or expires within the skew window.

    ``expires_at`` is the ``expires_at`` field returned by the auth server.
    A small skew is applied so we refresh slightly early rather than firing a
    request with a token that dies in flight.
    """
    expiry = parse_expiry(expires_at)
    return datetime.now(UTC) >= expiry - timedelta(seconds=skew_seconds)


def seconds_remaining(expires_at):
    """Seconds until the token expires (0 if it already has)."""
    delta = parse_expiry(expires_at) - datetime.now(UTC)
    return max(0.0, delta.total_seconds())


@dataclass(frozen=True)
class Token:
    """An access token and the moment it stops working."""

    access_token: str
    expires_at: str

    @classmethod
    def from_payload(cls, payload):
        """Build a token from an auth-server response body."""
        try:
            return cls(access_token=payload["access_token"], expires_at=payload["expires_at"])
        except (KeyError, TypeError) as exc:
            raise AuthError(f"auth server returned an unusable payload: {payload!r}") from exc

    @property
    def expired(self):
        """True when this token should be refreshed before the next request."""
        return is_expired(self.expires_at)

    @property
    def seconds_left(self):
        """Seconds until this token expires."""
        return seconds_remaining(self.expires_at)

    def authorization_header(self):
        """The ``Authorization`` header value for this token."""
        return f"Bearer {self.access_token}"
