"""Tests for accountsync.pagination."""

from accountsync.pagination import fetch_all


def make_api(records, page_size):
    """A well-behaved endpoint: every page is full except the last."""

    def fetch_page(page_number, size):
        assert size == page_size
        start = page_number * size
        page = records[start : start + size]
        return page or None  # end-of-data is signalled explicitly

    return fetch_page


def test_single_partial_page():
    records = list(range(7))
    assert fetch_all(make_api(records, 10), page_size=10) == records


def test_multiple_full_pages_then_partial():
    records = list(range(25))
    assert fetch_all(make_api(records, 10), page_size=10) == records


def test_exactly_one_full_page():
    records = list(range(10))
    assert fetch_all(make_api(records, 10), page_size=10) == records


def test_empty_result_set():
    assert fetch_all(make_api([], 10), page_size=10) == []


def test_requests_pages_in_order():
    seen = []

    def fetch_page(page_number, size):
        seen.append(page_number)
        start = page_number * size
        page = list(range(30))[start : start + size]
        return page or None  # end-of-data is signalled explicitly

    fetch_all(fetch_page, page_size=10)
    assert seen == [0, 1, 2, 3]
