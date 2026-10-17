# Make the Property Suite Green — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five audited defects in the `accountsync` library and complete the exercise stubs so the full suite — including the deliberately failing property-based tests in `tests/test_properties.py` — passes under `make lint` and `make test`.

**Architecture:** The property tests are counterexamples the example-based suite cannot reach; several directly contradict legacy tests that currently assert the *buggy* behaviour. The work is therefore: (1) activate the property suite, (2) fix the library (`retry`, `users`, `config`, `auth`, `pagination`), (3) update the legacy tests that pinned the buggy contract, (4) complete the `TODO` stubs in the property tests. Each library fix is one commit and keeps the suite green before the next fix starts.

**Tech Stack:** Python ≥3.11, pytest, Hypothesis, `uv` (the Makefile uses `uv run`, so no venv activation is needed), ruff for lint/format.

**Working directory for every command below:** `/opt/github/conferences/pycontw2026/p6rguvyrst/audit-ai-workshop` (branch `review`).

**Design decision recorded up front (pagination):** `fetch_all`'s "short page means end of data" heuristic is *unsound* for endpoints that filter after paginating (a short/empty filtered page can occur mid-stream), and it *never terminates* against an endpoint that never returns a short page. The fix changes the contract: the `fetch_page` callback signals end-of-data by returning `None`, and `fetch_all` gains a `max_pages` safety cap (default 1000). The cap is a *caller* decision — the pathological-endpoint property passes `max_pages=100` explicitly at its call site. No single default cap can satisfy both pagination properties (the filtering property needs up to 201 pages; the cap property must stop within 100), which is why the call-site edit is part of the exercise.

---

### Task 1: Activate the property suite and record the baseline

**Files:**
- Rename: `tests/test_properties.py.txt` → `tests/test_properties.py`

- [ ] **Step 1: Rename the exercise file**

```bash
mv tests/test_properties.py.txt tests/test_properties.py
```

- [ ] **Step 2: Run the suite and confirm the 10 expected failures**

Run: `uv run pytest -q`
Expected: **10 failed, 57 passed** — the failures are the property tests listed in the table below (the baseline). Do not fix anything yet.

| Failing test | Root cause (library) |
|---|---|
| `test_retry_is_total` | `retry.py` swallows the last `TransientError`, returns `None` |
| `test_never_sleeps_after_the_last_attempt` | sleeps after the final attempt (and the stub never calls the function) |
| `test_fetch_user_is_total` | `users.py` swallows the last `RequestException`, returns `None` |
| `test_fetch_user_never_sleeps_after_the_last_attempt` | same as above |
| `test_client_get_user_is_total` | inherits the `users.py` `None` return |
| `test_refresh_token_reports_the_real_error` | `TransientError` swallowed → `Token.from_payload(None)` → misleading `AuthError` |
| `test_defaults_are_never_contaminated` | `merge_config` shallow-copies `DEFAULTS` |
| `test_expiry_is_timezone_invariant` | invalid `""` strategies (test stub) + naive-clock comparison (library) |
| `test_parse_expiry_round_trips_an_aware_datetime` | `parse_expiry` returns a naive datetime |
| `test_walks_a_filtering_endpoint_completely` | short-page heuristic stops early (and the stub returns `[]`) |

> **Amendment during execution:** `hypothesis` was missing from the `dev` dependency group — without it, plain `uv run pytest` never collected the property module at all (54 passed; the `.py.txt` file is not a test pattern, so the `importorskip` guard never even ran). Added in commit `9454d7d` (`uv add --group dev hypothesis`); the 10-failed/57-passed baseline above is now reachable without `--with`.
>
> **Known interim state:** activating the file pulls its pre-existing stub content into lint scope, so `uv run ruff check .` reports 5 findings (F841/B007 inside `TODO` stub bodies) until Task 7 rewrites them — this self-heals. `ruff format` has been applied to the file so the format check stays green throughout.

- [ ] **Step 3: Commit the rename**

```bash
git add tests/test_properties.py.txt tests/test_properties.py
git commit -m "Activate the property-based exercise suite"
```

---

### Task 2: Fix `retry.py` — never return `None`, never sleep after the last attempt

**Files:**
- Modify: `accountsync/retry.py` (whole module, 20 lines)
- Modify: `tests/test_retry.py:26-43` (two legacy tests assert the buggy contract)

- [ ] **Step 1: Update the two legacy tests that pin the bug** (they must fail against the current code's *opposite*; run them first to see them fail is not possible yet — they pass today because the code returns `None`. Edit them now; they will go red after the fix lands and green again immediately after.)

Replace `tests/test_retry.py:26-43` with:

```python
def test_stops_after_retry_limit():
    calls = []

    def always_fails():
        calls.append(1)
        raise TransientError("boom")

    with pytest.raises(TransientError):
        fetch_with_retry(always_fails, retries=3, backoff=0)
    assert len(calls) == 3


def test_exhausted_retries_raise_the_last_transient_error():
    def always_fails():
        raise TransientError("boom")

    with pytest.raises(TransientError):
        fetch_with_retry(always_fails, retries=2, backoff=0)
```

(The old `test_survives_total_failure` — "the helper should absorb transient errors" — is deleted: it asserted exactly the defect the property suite exists to expose. A silent `None` from a dead upstream is what `test_client_get_user_is_total` calls "hand the caller a None that dies later".)

- [ ] **Step 2: Rewrite `accountsync/retry.py`**

Replace the whole file with:

```python
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
```

- [ ] **Step 3: Run the retry-related tests**

Run: `uv run pytest tests/test_retry.py tests/test_properties.py::test_retry_is_total tests/test_properties.py::test_never_sleeps_after_the_last_attempt -q`
Expected: all PASS. (The two sleep-count tests still fail if the `pass` stub is untouched — they are completed in Task 7; if you want them green now, replace `pass # TODO: use fetch_with_retry here` with `fetch_with_retry(always_fails, retries=retries)`. The plan completes all stubs together in Task 7.)

- [ ] **Step 4: Run the rest of the suite for regressions**

Run: `uv run pytest -q`
Expected: the 10 baseline failures minus `test_retry_is_total` → **9 failed**, no *new* failures.

- [ ] **Step 5: Commit**

```bash
git add accountsync/retry.py tests/test_retry.py
git commit -m "retry: re-raise the last transient error and sleep only between attempts"
```

---

### Task 3: Fix `users.py` — same two defects at the transport layer

**Files:**
- Modify: `accountsync/users.py:10-18`
- Modify: `tests/test_users.py:93-125`
- Modify: `tests/test_client.py:30-37`

- [ ] **Step 1: Update the legacy tests that pin the bug**

In `tests/test_users.py`, replace `test_gives_up_after_the_retry_limit` (line 93), `test_backs_off_exponentially` (line 111) and `test_upstream_outage_does_not_raise` (line 120) with:

```python
@patch("accountsync.users.requests.get")
def test_gives_up_after_the_retry_limit(mock_get):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42, retries=3)

    assert mock_get.call_count == 3


```python
@patch("accountsync.users.requests.get")
def test_backs_off_between_attempts(mock_get, no_sleep):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42, retries=3, backoff=0.5)

    assert [call.args[0] for call in no_sleep.call_args_list] == [0.5, 1.0]


@patch("accountsync.users.requests.get")
def test_upstream_outage_raises_instead_of_returning_none(mock_get):
    """A dead upstream is reported, not swallowed into a None return."""
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")

    with pytest.raises(requests.RequestException):
        fetch_user(42)
```

(3 attempts now cost 2 sleeps: `[0.5, 1.0]` instead of the old `[0.5, 1.0, 2.0]` — this is the deliberate resolution of the contradiction named in the property-suite docstring.)

In `tests/test_client.py`, update `test_get_user_uses_the_configured_retry_count` (the fixed `fetch_user` now reports the outage instead of returning `None`, so the call must expect the exception):

```python
@patch("accountsync.users.requests.get")
def test_get_user_uses_the_configured_retry_count(mock_get, fresh_token):
    mock_get.side_effect = requests.ConnectionError("connection reset by peer")
    client = AccountsClient(config={"retries": 5}, token=fresh_token)

    with pytest.raises(requests.RequestException):
        client.get_user(42)

    assert mock_get.call_count == 5
```

- [ ] **Step 2: Rewrite `fetch_user` in `accountsync/users.py`**

Replace lines 10-18 with:

```python
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
```

- [ ] **Step 3: Run the affected tests**

Run: `uv run pytest tests/test_users.py tests/test_client.py tests/test_cli.py -q`
Expected: all PASS (the `None`-return fixes cascade into `test_client_get_user_is_total`, but the two stub-gated properties stay red until Task 7).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: **7 failed** (baseline 10 − retry totality − retry sleeps), no new failures.

- [ ] **Step 5: Commit**

```bash
git add accountsync/users.py tests/test_users.py tests/test_client.py
git commit -m "users: re-raise the last request error and sleep only between attempts"
```

---

### Task 4: Fix `config.py` — deep copy and deep merge

**Files:**
- Modify: `accountsync/config.py:36-49`

- [ ] **Step 1: Replace `merge_config`**

In `accountsync/config.py`, add `import copy` to the imports and replace `merge_config` and `load_config` with:

```python
def merge_config(defaults, overrides):
    """Merge ``overrides`` on top of ``defaults`` and return a new config.

    Nested sections are deep-merged, so overriding one key keeps the
    section's other keys, and the result shares no mutable state with
    ``defaults``: a single module-level default config can be safely
    reused across callers.
    """
    merged = copy.deepcopy(defaults)
    _deep_merge(merged, overrides)
    return merged


def _deep_merge(target, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def load_config(overrides=None):
    """Build the effective config for this caller."""
    return merge_config(DEFAULTS, overrides or {})
```

- [ ] **Step 2: Run the config tests and the contamination property**

Run: `uv run pytest tests/test_config.py tests/test_properties.py::test_defaults_are_never_contaminated tests/test_properties.py::test_merge_preserves_every_default_leaf tests/test_properties.py::test_result_shares_no_mutable_state_with_defaults -q`

Expected: `test_defaults_are_never_contaminated` PASSES. The two merge properties still FAIL — their `assert True` stubs are completed in Task 7. No `tests/test_config.py` test breaks: `test_nested_section_can_be_overridden` passes an override covering every key of the `database` section, so deep-merge and replacement produce the same result there.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: **7 failed** (same set as after Task 3), no new failures.

- [ ] **Step 4: Commit**

```bash
git add accountsync/config.py
git commit -m "config: deep-copy defaults and deep-merge nested sections"
```

---

### Task 5: Fix `auth.py` — aware datetimes, TZ-invariant expiry

**Files:**
- Modify: `accountsync/auth.py` (module clock logic)
- Modify: `tests/helpers.py:11-13` (the shared `stamp()` helper — it builds "UTC" stamps from the naive local clock, which is exactly the assumption being fixed)
- Modify: `tests/test_auth.py:8-13`

This task must land as one commit: the legacy tests build stamps from `datetime.now()` while the fixed library reads `datetime.now(UTC)`; changing only one side makes the suite TZ-dependent.

- [ ] **Step 1: Fix the stamp helpers**

In `tests/helpers.py`, replace `stamp`:

```python
from datetime import UTC, datetime
from unittest.mock import Mock

import requests

from accountsync.auth import ISO_FORMAT


def stamp(delta):
    """An ``expires_at`` timestamp ``delta`` away from *UTC* now."""
    return (datetime.now(UTC) + delta).strftime(ISO_FORMAT)
```

In `tests/test_auth.py`, replace the local `_stamp` and the parse assertion:

```python
from datetime import UTC, datetime, timedelta

from accountsync.auth import ISO_FORMAT, is_expired, parse_expiry, seconds_remaining


def _stamp(delta):
    return (datetime.now(UTC) + delta).strftime(ISO_FORMAT)


def test_parses_iso_timestamp():
    assert parse_expiry("2026-08-30T12:00:00Z") == datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)
```

- [ ] **Step 2: Fix the library clock**

In `accountsync/auth.py`:

1. Change the import to `from datetime import UTC, datetime, timedelta`.
2. Replace `parse_expiry`, `is_expired`, and `seconds_remaining` with:

```python
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
```

- [ ] **Step 3: Run the auth-related tests**

Run: `uv run pytest tests/test_auth.py tests/test_cli.py tests/test_client.py tests/test_properties.py::test_parse_expiry_round_trips_an_aware_datetime -q`

Expected: `test_parse_expiry_round_trips_an_aware_datetime` still FAILS — it has an `assert True` stub (Task 7) and its failing assert (`parsed.tzinfo is not None`) will only pass after this fix, which is the point. Everything else PASSES. Confirm the actual result: all auth/client/cli tests pass, one property failure.

> **Owner decision (UTC-only):** the deployment has exactly one timezone — UTC. The fix here pins UTC explicitly in code (parse as UTC, compare against `now(UTC)`), because the defect is *silently reading the host clock*, and host TZ is not guaranteed even in a UTC-only world (e.g. macOS dev machines). The tz-matrix property (`test_expiry_is_timezone_invariant` and its `tzset` machinery) tests a world that does not exist here; it is **removed** in Task 7 rather than completed.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: **6 failed** (the remaining property failures), no new failures.

- [ ] **Step 5: Commit**

```bash
git add accountsync/auth.py tests/helpers.py tests/test_auth.py
git commit -m "auth: timezone-aware expiry — parse Z suffix as UTC, compare against UTC now"
```

---

### Task 6: Fix `pagination.py` — explicit end-of-data signal and a page cap

**Files:**
- Modify: `accountsync/pagination.py` (whole module)
- Modify: `accountsync/client.py:62-68` (the `list_users` page wrapper)
- Modify: `tests/test_pagination.py` (fakes signal end explicitly)
- Modify: `tests/test_client.py:40-62` (two tests need a final empty page)
- Modify: `tests/test_cli.py:80-88` (sync test needs a final empty page)

- [ ] **Step 1: Rewrite `accountsync/pagination.py`**

```python
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
    """
    records = []
    for page_number in range(max_pages):
        page = fetch_page(page_number, page_size)
        if page is None:
            break
        records.extend(page)
    return records
```

- [ ] **Step 2: Adapt the client's page wrapper**

In `accountsync/client.py`, replace `list_users` (lines 62-68) with:

```python
    def list_users(self, page_size=DEFAULT_PAGE_SIZE):
        """Every user visible to this tenant, across all pages."""

        def page(page_number, size):
            data = list_users_page(page_number, size, base_url=self.base_url)
            return data or None  # an empty page means the collection ended

        return fetch_all(page, page_size=page_size)
```

- [ ] **Step 3: Update the pagination test fakes**

In `tests/test_pagination.py`, replace `make_api` with:

```python
def make_api(records, page_size):
    """A well-behaved endpoint: every page is full except the last."""

    def fetch_page(page_number, size):
        assert size == page_size
        start = page_number * size
        page = records[start : start + size]
        return page or None  # end-of-data is signalled explicitly

    return fetch_page
```

All five existing tests in the file pass unchanged against the new contract.

- [ ] **Step 4: Give the mocked upstreams a final empty page**

In `tests/test_client.py`, update `test_list_users_walks_every_page` and `test_sync_users_writes_json`:

```python
@patch("accountsync.users.requests.get")
def test_list_users_walks_every_page(mock_get, fresh_token):
    mock_get.side_effect = [
        ok_response({"data": [{"id": i} for i in range(10)]}),
        ok_response({"data": [{"id": i} for i in range(10, 17)]}),
        ok_response({"data": []}),  # end of the collection
    ]
    client = AccountsClient(token=fresh_token)

    users = client.list_users(page_size=10)

    assert [u["id"] for u in users] == list(range(17))
    assert mock_get.call_count == 3
```

```python
@patch("accountsync.users.requests.get")
def test_sync_users_writes_json(mock_get, tmp_path, fresh_token):
    mock_get.side_effect = [
        ok_response({"data": [{"id": 1}, {"id": 2}]}),
        ok_response({"data": []}),  # end of the collection
    ]
    destination = tmp_path / "out" / "users.json"

    written = AccountsClient(token=fresh_token).sync_users(destination, page_size=10)

    assert written == 2
    assert json.loads(destination.read_text()) == [{"id": 1}, {"id": 2}]
```

In `tests/test_cli.py`, update `test_sync_writes_the_destination_file`:

```python
@patch("accountsync.users.requests.get")
def test_sync_writes_the_destination_file(mock_get, in_tmp_cwd, capsys):
    mock_get.side_effect = [
        ok_response({"data": [{"id": 1}]}),
        ok_response({"data": []}),  # end of the collection
    ]
    destination = in_tmp_cwd / "users.json"

    assert main(["sync", str(destination), "--page-size", "10"]) == 0

    assert json.loads(destination.read_text()) == [{"id": 1}]
    assert "wrote 1 user(s)" in capsys.readouterr().err
```

- [ ] **Step 5: Run the affected tests**

Run: `uv run pytest tests/test_pagination.py tests/test_client.py tests/test_cli.py tests/test_properties.py::test_walks_a_filtering_endpoint_completely tests/test_properties.py::test_caps_iteration_on_an_endpoint_that_never_returns_a_short_page -q`

Expected: the two pagination properties still FAIL (their stubs are completed in Task 7). Everything else PASSES.

- [ ] **Step 6: Full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: **6 failed** (the remaining property stubs), lint clean.

- [ ] **Step 7: Commit**

```bash
git add accountsync/pagination.py accountsync/client.py tests/test_pagination.py tests/test_client.py tests/test_cli.py
git commit -m "pagination: explicit end-of-data signal plus a max-pages safety cap"
```

---

### Task 7: Complete the property-test stubs (the exercise TODOs)

**Files:**
- Modify: `tests/test_properties.py` (eight TODO sites)

- [ ] **Step 1: Part 1 — retry totality** (`tests/test_properties.py:104` and `:120`)

Replace, in `test_retry_is_total`:

```python
        if failures < retries:
            result = fetch_with_retry(fetch, retries=retries)
            assert result is sentinel
```

and in `test_never_sleeps_after_the_last_attempt`:

```python
        with contextlib.suppress(TransientError):
            fetch_with_retry(always_fails, retries=retries)
```

- [ ] **Step 2: Part 2 — transport totality** (`tests/test_properties.py:150` and `:168`)

In `test_fetch_user_is_total`:

```python
        if failures < retries:
            assert fetch_user(42, retries=retries) == payload
```

in `test_fetch_user_never_sleeps_after_the_last_attempt`:

```python
        with contextlib.suppress(requests.RequestException):
            fetch_user(42, retries=retries)
```

- [ ] **Step 3: Part 4 — merge properties** (`tests/test_properties.py:228` and `:244`)

In `test_merge_preserves_every_default_leaf`:

```python
    for section, defaults in DEFAULTS.items():
        if isinstance(defaults, dict):
            expected = {**defaults, **overrides.get(section, {})}
            assert merged[section] == expected
```

in `test_result_shares_no_mutable_state_with_defaults`:

```python
    for key, value in DEFAULTS.items():
        if isinstance(value, dict):
            assert merged[key] is not value
```

- [ ] **Step 4: Part 5 — remove the tz matrix (UTC-only deployment), keep the round-trip** (`tests/test_properties.py:289-358`)

Per the owner's decision, the deployment has exactly one timezone — UTC — so a two-observer timezone matrix tests a world that does not exist here. Delete the machinery and the property:

- the `TIMEZONES` list, `OFFSET_QUANTUM` constant, `requires_tzset` marker, `_tz` and `_under_tz` helpers (the block from `#: Includes 45-minute offsets...` down to the end of `test_expiry_is_timezone_invariant`)

Expiry correctness under UTC-only remains witnessed by `test_parse_expiry_round_trips_an_aware_datetime`, the `test_token_*` skew tests, and the CLI `token` tests.

Then complete the round-trip assert (the `ISO_FORMAT` template has no microseconds, so the instant is quantised to whole seconds):

```python
    assert parsed == dt.replace(microsecond=0)
```

- [ ] **Step 5: Part 6 — pagination oracles** (`tests/test_properties.py:382` and `:398`)

In `test_walks_a_filtering_endpoint_completely` (a slice beyond the end is empty — that is the upstream exhaustion signal; a mid-stream window can only filter to `[]`, never become an empty *slice*):

```python
    def fetch_page(page_number, size):
        window = rows[page_number * size : (page_number + 1) * size]
        if not window:  # the upstream ran out of rows
            return None
        return [r for r in window if r not in hidden]  # filtered AFTER paginating
```

In `test_caps_iteration_on_an_endpoint_that_never_returns_a_short_page` (the cap is the caller's decision — pass it explicitly so the 100-call bound under test is the *client's* choice):

```python
    def fetch_page(page_number, size):
        assert next(calls) < max_requests, f"no cap: still requesting after {max_requests} pages"
        return list(range(size))  # always full - no page is ever short

    fetch_all(fetch_page, page_size=page_size, max_pages=100)
```

- [ ] **Step 6: Run the property suite**

Run: `uv run pytest tests/test_properties.py -q`
Expected: **all PASS**. If `test_walks_a_filtering_endpoint_completely` still fails, re-run with `-vv` and check the counterexample against the Task 4/5/6 library fixes before touching the test again.

- [ ] **Step 7: Commit**

```bash
git add tests/test_properties.py
git commit -m "properties: complete the exercise stubs"
```

---

### Task 8: Full verification

- [ ] **Step 1: Lint and format check**

Run: `make lint`
Expected: clean (no output, exit 0). If formatting drifts, run `make format` and re-run `make lint`.

- [ ] **Step 2: Full suite**

Run: `make test`
Expected: **66 passed** (the tz-matrix property was removed per the UTC-only owner decision).

- [ ] **Step 3: Property hardening run** (more examples than CI's 50 before trusting green)

Run: `HYPOTHESIS_MAX_EXAMPLES=1000 uv run pytest tests/test_properties.py -q`
Expected: all PASS.

- [ ] **Step 4: Coverage**

Run: `make cov`
Expected: all `accountsync` modules at 100% line and branch coverage (the new `raise last_error`, `max_pages` loop and deep-merge branches are exercised by the property suite; if any line is missed, add a focused example-based test for it before committing).

- [ ] **Step 5: Final commit (if Steps 1–4 produced changes)**

```bash
git add -A
git commit -m "Verify full suite green under lint, tests and coverage"
```
