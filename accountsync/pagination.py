"""Helpers for walking paginated list endpoints."""

DEFAULT_PAGE_SIZE = 100

#: Safety cap on pages walked in one :func:`fetch_all` call, so a
#: pathological endpoint that never signals end-of-data cannot loop the
#: client forever. Callers pass their own bound when they want one.
DEFAULT_MAX_PAGES = 1000


def fetch_all(fetch_page, page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES):
    """Collect every record from a paginated endpoint.

    ``fetch_page(page_number, page_size)`` returns the list of records on
    that page, and signals the end of the result set by returning ``None``.
    End-of-data is *explicit*: a short page is reported as-is, because
    endpoints that filter after paginating legitimately return short or
    empty pages mid-stream. At most ``max_pages`` pages are requested.
    When the cap is reached, whatever has been collected so far is returned
    as-is; a caller that needs a completeness guarantee must pass a bound
    it trusts.
    """
    records = []
    for page_number in range(max_pages):
        page = fetch_page(page_number, page_size)
        if page is None:
            break
        records.extend(page)
    return records
