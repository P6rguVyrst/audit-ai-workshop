"""User lookup against the upstream account service."""

import time

import requests

BASE_URL = "https://api.example.com"


def fetch_user(user_id, retries=3, backoff=0.5):
    """Fetch a user record, retrying on transient network errors.

    Sleeps only between attempts. When every attempt fails, the last
    ``RequestException`` is re-raised rather than returning ``None``.
    """
    last_error = None
    for attempt in range(retries):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        try:
            resp = requests.get(f"{BASE_URL}/users/{user_id}", timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            last_error = exc
    raise last_error


def list_users_page(page_number, page_size, *, base_url=BASE_URL, timeout=5):
    """Fetch one page of the ``GET /users`` collection.

    Shaped for :func:`accountsync.pagination.fetch_all`: takes the page number
    and page size, returns the list of records on that page.
    """
    resp = requests.get(
        f"{base_url}/users",
        params={"page": page_number, "per_page": page_size},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["data"]
