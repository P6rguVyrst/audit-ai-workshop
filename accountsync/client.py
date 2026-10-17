"""High-level client for the Accounts API.

:class:`AccountsClient` is the object application code is expected to hold: it
owns the effective configuration, keeps an access token fresh, and exposes the
handful of operations the sync job needs.
"""

import json
from pathlib import Path

from accountsync.auth import Token
from accountsync.config import load_config
from accountsync.errors import AuthError
from accountsync.pagination import DEFAULT_PAGE_SIZE, fetch_all
from accountsync.retry import fetch_with_retry
from accountsync.users import BASE_URL, fetch_user, list_users_page


class AccountsClient:
    """A configured client for one Accounts API tenant.

    ``token_source`` is a zero-argument callable returning an auth-server
    payload. It is called lazily, and again whenever the current token is
    within the refresh skew window.
    """

    def __init__(self, *, config=None, token=None, token_source=None, base_url=BASE_URL):
        self.config = load_config() if config is None else config
        self.base_url = base_url
        self._token = token
        self._token_source = token_source

    @property
    def retries(self):
        """How many attempts each upstream call gets."""
        return self.config["retries"]

    @property
    def token(self):
        """The current access token, refreshed if it is expired or missing."""
        if self._token is None or self._token.expired:
            self._token = self._refresh_token()
        return self._token

    def _refresh_token(self):
        if self._token_source is None:
            raise AuthError("no token_source configured; pass token= or token_source=")
        payload = fetch_with_retry(self._token_source, retries=self.retries)
        return Token.from_payload(payload)

    def headers(self):
        """Request headers, including the ``Authorization`` header."""
        return {
            "Accept": "application/json",
            "Authorization": self.token.authorization_header(),
        }

    def get_user(self, user_id):
        """Look up a single user by id."""
        return fetch_user(user_id, retries=self.retries)

    def list_users(self, page_size=DEFAULT_PAGE_SIZE):
        """Every user visible to this tenant, across all pages."""

        def page(page_number, size):
            data = list_users_page(page_number, size, base_url=self.base_url)
            return data or None  # an empty page means the collection ended

        return fetch_all(page, page_size=page_size)

    def sync_users(self, destination, page_size=DEFAULT_PAGE_SIZE):
        """Write every visible user to ``destination`` as JSON.

        Returns the number of records written.
        """
        users = self.list_users(page_size=page_size)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(users, indent=2, sort_keys=True))
        return len(users)
