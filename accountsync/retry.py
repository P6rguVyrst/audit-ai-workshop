"""Retry helper for flaky upstream calls."""

import time

from accountsync.errors import TransientError

__all__ = ["TransientError", "fetch_with_retry"]


def fetch_with_retry(fetch, *, retries=3, backoff=0.5):
    """Call ``fetch`` up to ``retries`` times with exponential backoff.

    Returns the value produced by ``fetch``. The first attempt runs
    immediately; each retry is preceded by a delay of
    ``backoff * 2 ** (attempt - 1)`` seconds, so N attempts cost at most
    N-1 sleeps. When every attempt fails, the last ``TransientError`` is
    re-raised: this helper never returns ``None``, so a caller cannot
    mistake "the upstream was down" for "no result".
    """
    last_error = None
    for attempt in range(retries):
        if attempt:
            time.sleep(backoff * 2 ** (attempt - 1))
        try:
            return fetch()
        except TransientError as exc:
            last_error = exc
    raise last_error
