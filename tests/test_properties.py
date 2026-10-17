"""Property-based tests to be completed.

Search for "TODO" and follow the instructions.

**These tests fail on the current tree, by design.** They are the
counterexamples the rest of the suite cannot reach. Two of them are the direct
inverse of tests that currently pass:

* ``test_retry_is_total`` contradicts ``test_retry.py::test_survives_total_failure``
* ``test_never_sleeps_after_the_last_attempt`` contradicts
  ``test_users.py::test_backs_off_exponentially``

Neither pair can hold at once. Choosing between them is part of the exercise.

Notes on the constraints this file was written under:

* ``database=None`` means no example database is written, so a counterexample is
  not replayed on the next run.
* No ``time-machine`` dependency: the timezone properties quantise the generated
  expiry to 5-minute steps, so no example can land within clock-drift distance
  of a skew boundary and the real clock is safe to read.
* ``tests/helpers.py:stamp()`` builds its "UTC" timestamps from the local clock,
  so nothing here may use it — a helper that shares the code's assumption cannot
  witness a violation of it. These tests construct their own timestamps.
"""

import contextlib
import copy
import itertools
import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import requests

pytest.importorskip("hypothesis", reason="hypothesis is not installed; see the module docstring")

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
    run_state_machine_as_test,
)

from accountsync import retry, users
from accountsync.auth import ISO_FORMAT, is_expired, parse_expiry
from accountsync.client import AccountsClient
from accountsync.config import DEFAULTS, load_config, merge_config
from accountsync.errors import TransientError
from accountsync.pagination import fetch_all
from accountsync.retry import fetch_with_retry
from accountsync.users import fetch_user
from tests.helpers import ok_response

#: Shared settings for every property in this module.
#:
#: ``function_scoped_fixture`` is suppressed because ``conftest.py``'s autouse
#: ``clean_env`` fixture is function-scoped and would otherwise trip the health
#: check on every property here.
PROPERTY = settings(
    max_examples=int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "50")),
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture(autouse=True)
def _pristine_defaults():
    """Restore ``DEFAULTS`` after every test in this module.
    """
    snapshot = copy.deepcopy(DEFAULTS)
    yield
    DEFAULTS.clear()
    DEFAULTS.update(snapshot)


# ---------------------------------------------------------------------------
# Part #1 — accountsync/retry.py: totality of the retry helper
# ---------------------------------------------------------------------------


@PROPERTY
@given(
    retries=st.integers(min_value=1, max_value=5),
    failures=st.integers(min_value=0, max_value=10),
)
def test_retry_is_total(retries, failures):
    """Either the payload comes back, or the error escapes. Never None."""
    calls = itertools.count()
    sentinel = {"id": 1}

    def fetch():
        if next(calls) < failures:
            raise TransientError("upstream blip")
        return sentinel

    with patch.object(retry.time, "sleep"):
        if failures < retries:
            assert True # TODO: complete the assert statement
        else:
            with pytest.raises(TransientError):
                fetch_with_retry(fetch, retries=retries)


@PROPERTY
@given(retries=st.integers(min_value=1, max_value=5))
def test_never_sleeps_after_the_last_attempt(retries):
    """Backoff separates attempts, so N attempts need N-1 sleeps, not N."""

    def always_fails():
        raise TransientError("upstream blip")

    with patch.object(retry.time, "sleep") as sleep:
        with contextlib.suppress(TransientError):
            pass # TODO: use fetch_with_retry here
        assert sleep.call_count == retries - 1


# ---------------------------------------------------------------------------
# Part #2 — accountsync/users.py: the same two properties at the transport
# ---------------------------------------------------------------------------


@PROPERTY
@given(
    retries=st.integers(min_value=1, max_value=5),
    failures=st.integers(min_value=0, max_value=10),
    error=st.sampled_from([requests.ConnectionError, requests.Timeout, requests.HTTPError]),
)
def test_fetch_user_is_total(retries, failures, error):
    """Same claim as test_retry_is_total, one layer down."""
    payload = {"id": 42, "email": "a@example.com"}
    calls = itertools.count()

    def fake_get(*args, **kwargs):
        if next(calls) < failures:
            raise error("upstream blip")
        return ok_response(payload)

    with (
        patch("accountsync.users.requests.get", side_effect=fake_get),
        patch.object(users.time, "sleep"),
    ):
        if failures < retries:
            assert True # TODO: complete the assert statement
        else:
            with pytest.raises(requests.RequestException):
                fetch_user(42, retries=retries)


@PROPERTY
@given(retries=st.integers(min_value=1, max_value=5))
def test_fetch_user_never_sleeps_after_the_last_attempt(retries):
    """N attempts against a dead upstream must cost N-1 backoff waits."""
    with (
        patch(
            "accountsync.users.requests.get",
            side_effect=requests.ConnectionError("connection reset by peer"),
        ),
        patch.object(users.time, "sleep") as sleep,
    ):
        with contextlib.suppress(requests.RequestException):
            pass # TODO: use fetch_user here
        assert sleep.call_count == retries - 1


# ---------------------------------------------------------------------------
# Part #3 through the client — the layer application code holds
# ---------------------------------------------------------------------------


@PROPERTY
@given(retries=st.integers(min_value=1, max_value=5))
def test_client_get_user_is_total(retries):
    """A dead upstream must not hand the caller a None that dies later."""
    client = AccountsClient(config={"retries": retries})
    with (
        patch(
            "accountsync.users.requests.get",
            side_effect=requests.ConnectionError("connection reset by peer"),
        ),
        patch.object(users.time, "sleep"),
    ):
        with pytest.raises(requests.RequestException):
            client.get_user(42)


@PROPERTY
@given(retries=st.integers(min_value=1, max_value=5))
def test_refresh_token_reports_the_real_error(retries):
    """An auth server that is down is a transient failure, not a bad payload.
    """

    def dead_auth_server():
        raise TransientError("auth server unreachable")

    client = AccountsClient(config={"retries": retries}, token_source=dead_auth_server)
    with patch.object(retry.time, "sleep"), pytest.raises(TransientError):
        client.token  # noqa: B018


# ---------------------------------------------------------------------------
# Part #4 — accountsync/config.py: merge depth and aliasing
# ---------------------------------------------------------------------------

SECTIONS = st.sampled_from(["database", "features"])
LEAF_KEYS = st.sampled_from(["host", "port", "pool_size", "beta_ui", "metrics"])


@PROPERTY
@given(
    overrides=st.dictionaries(
        SECTIONS,
        st.dictionaries(LEAF_KEYS, st.integers(), max_size=2),
        max_size=2,
    )
)
def test_merge_preserves_every_default_leaf(overrides):
    """A partial section override must not drop the section's other keys."""
    merged = merge_config(DEFAULTS, overrides)
    for section, defaults in DEFAULTS.items():
        if isinstance(defaults, dict):
            assert True # TODO: complete the assert statement


@PROPERTY
@given(
    overrides=st.dictionaries(
        st.sampled_from(["timeout", "retries"]),
        st.integers(),
        max_size=2,
    )
)
def test_result_shares_no_mutable_state_with_defaults(overrides):
    """No nested value in the result may be the same object as in DEFAULTS."""
    merged = merge_config(DEFAULTS, overrides)
    for key, value in DEFAULTS.items():
        if isinstance(value, dict):
            assert True # TODO: complete the assert statement


class ConfigContamination(RuleBasedStateMachine):
    """DEFAULTS must be identical after any sequence of load-and-mutate.

    The stateful formulation is the one that reproduces the production symptom:
    request N changing behaviour for request N+1, and disappearing on restart.
    """

    def __init__(self):
        super().__init__()
        self.pristine = copy.deepcopy(DEFAULTS)

    @rule(key=st.sampled_from(["host", "port"]), value=st.integers())
    def load_and_mutate(self, key, value):
        load_config()["database"][key] = value  # a caller editing its own config

    @invariant()
    def defaults_unchanged(self):
        assert DEFAULTS == self.pristine

    def teardown(self):
        DEFAULTS.clear()
        DEFAULTS.update(self.pristine)


def test_defaults_are_never_contaminated():
    """Drive ConfigContamination as a test."""
    run_state_machine_as_test(
        ConfigContamination,
        settings=settings(
            max_examples=25,
            stateful_step_count=10,
            deadline=None,
            database=None,
            suppress_health_check=[HealthCheck.function_scoped_fixture],
        ),
    )


# ---------------------------------------------------------------------------
# Part #5 — accountsync/auth.py: timezone invariance and round-tripping
# ---------------------------------------------------------------------------

#: Includes 45-minute offsets, which catch sign-and-magnitude errors that
#: whole-hour offsets do not.
TIMEZONES = [
    "UTC",
    "Asia/Tokyo",  # +09:00
    "America/Los_Angeles",  # -07:00 / -08:00
    "Asia/Kathmandu",  # +05:45
    "Australia/Eucla",  # +08:45
]

#: Generated expiry offsets are multiples of this many seconds, so no example
#: can land within clock-drift distance of a skew boundary (which sits at a
#: whole timezone offset plus the 30-second skew).
OFFSET_QUANTUM = 300

requires_tzset = pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX-only")


@contextlib.contextmanager
def _tz(name):
    """Run the block with the process timezone set to ``name``."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


def _under_tz(name, func, *args):
    with _tz(name):
        return func(*args)


@requires_tzset
@PROPERTY
@given(
    steps=st.integers(min_value=-288, max_value=288),  # +/- 24h in 5-minute steps
    tz_a="", # TODO: what should be the value of tz_a and tz_b?
    tz_b="", # Hint: use st.sampled_from
)
def test_expiry_is_timezone_invariant(steps, tz_a, tz_b):
    """The answer must not depend on the machine's timezone.

    The strongest property available here, because it needs no knowledge of the
    correct answer — only that two observers of the same instant agree.
    """
    offset = timedelta(seconds=steps * OFFSET_QUANTUM)
    expires_at = (datetime.now(UTC) + offset).strftime(ISO_FORMAT)
    assert _under_tz(tz_a, is_expired, expires_at) == _under_tz(tz_b, is_expired, expires_at)


@PROPERTY
@given(
    dt=st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 1, 1),
        timezones=st.just(UTC),
    )
)
def test_parse_expiry_round_trips_an_aware_datetime(dt):
    """Serialise then parse must give back the same instant, still aware."""
    parsed = parse_expiry(dt.strftime(ISO_FORMAT))
    assert parsed.tzinfo is not None
    assert True # TODO: complete the assert statement


# ---------------------------------------------------------------------------
# Part #6 — accountsync/pagination.py: endpoints that filter after paginating
# ---------------------------------------------------------------------------


@PROPERTY
@given(
    total=st.integers(min_value=0, max_value=200),
    hidden=st.sets(st.integers(min_value=0, max_value=199)),
    page_size=st.integers(min_value=1, max_value=10),
)
def test_walks_a_filtering_endpoint_completely(total, hidden, page_size):
    """Dense upstream, filtered per page — permissions, soft deletes, tenancy.

    The oracle never calls fetch_all, so it cannot inherit its assumption.
    """
    rows = list(range(total))

    def fetch_page(page_number, size):
        window = rows[page_number * size : (page_number + 1) * size]
        # TODO: what should we return? Hint: it's filtered AFTER paginating
        return []

    assert fetch_all(fetch_page, page_size=page_size) == [r for r in rows if r not in hidden]


@PROPERTY
@given(page_size=st.integers(min_value=1, max_value=10))
def test_caps_iteration_on_an_endpoint_that_never_returns_a_short_page(page_size):
    """A pathological endpoint must not be able to loop the client forever.
    """
    max_requests = 100
    calls = itertools.count()

    def fetch_page(page_number, size):
        assert next(calls) < max_requests, f"no cap: still requesting after {max_requests} pages"
        # TODO: what should we return? Hint: it's always full - no page is ever short
        return []

    fetch_all(fetch_page, page_size=page_size)
