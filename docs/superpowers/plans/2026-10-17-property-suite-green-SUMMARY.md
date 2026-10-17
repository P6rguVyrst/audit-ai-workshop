# Executive Summary — Making the Property Suite Green

**Plan:** `2026-10-17-property-suite-green.md` · **Branch:** `review` · **Date:** 2026-10-17

## What you're reviewing

This repo is the workshop's deliberately buggy "AI-generated" client library. The audit instrument — `tests/test_properties.py` — is shipped as a `.txt` file so it never runs. Activating it produces **10 failures against 5 real defects**. The proposal: **fix the library to satisfy the properties, not the other way round.** The property tests' own `TODO` stubs get completed exactly per their inline hints.

## The five defects (what the code does wrong today)

1. **Retry swallows total failure** (`retry.py`, `users.py` — same copy-pasted loop). When every attempt fails, the function returns `None`. Callers can't tell "server down" from "no data" — the failure surfaces later, elsewhere, as a confusing `TypeError` or a misleading `AuthError`.
2. **Backoff sleeps after the last attempt.** N attempts cost N sleeps instead of N−1: pure added latency on the failure path.
3. **Global config contamination** (`config.py`). Merging config is a shallow copy, so every caller's `load_config()` result *shares* the nested `database`/`features` dicts with the module-level `DEFAULTS`. One caller editing their own config mutates every future caller until restart. Classic stateful bug.
4. **Token expiry depends on the machine's timezone** (`auth.py`). Expiry strings (UTC) are parsed into *naive* datetimes and compared against local time. The same token is "expired" in Tokyo and "valid" in Los Angeles.
5. **Pagination termination is unsound** (`pagination.py`). "A short page means end of data" breaks for endpoints that filter after paginating (silently drops records) and loops forever against endpoints that never return a short page.

## Behavioural changes a caller will see (breaking)

- `fetch_user` / `fetch_with_retry` **raise** the last error on total failure instead of returning `None`.
- Backoff sleeps **between** attempts only.
- Config results are **independent copies**; section overrides **keep sibling keys**.
- `parse_expiry`/`is_expired` are **timezone-aware** (UTC).
- `fetch_all`'s `fetch_page` callback must **signal end-of-data by returning `None`**; a new `max_pages` cap (default 1000) bounds pathological endpoints.

## The deliberate contradictions (choices being made for you to veto)

The workshop ships pairs of tests that cannot both hold; the legacy example-based tests assert the *buggy* behaviour. We side with the properties and rewrite the legacy tests:

| Legacy test (asserting the bug) | Replaced by |
|---|---|
| `test_survives_total_failure`, `test_upstream_outage_does_not_raise` | Total failure now raises |
| `test_backs_off_exponentially` asserting `[0.5, 1.0, 2.0]` | `[0.5, 1.0]` — no sleep after the last attempt |
| Short-page termination in pagination fakes | Explicit end-of-data signal |

## The one design decision needing your sign-off

**Pagination contract change.** No single default page cap satisfies both pagination properties (the filtering property needs up to 201 pages; the cap property must stop within 100). Resolution: the cap is the *caller's* decision — `fetch_all` gains `max_pages` (default 1000), and the pathological-endpoint property passes `max_pages=100` explicitly at its call site. This edits one line beyond the marked `TODO` in that test.

## Owner decisions made during execution (2026-10-17)

1. **UTC-only.** "There is one timezone and only one timezone: UTC." The library still pins UTC explicitly in code (parse as UTC, compare against `now(UTC)`) — the defect is that it silently reads the *host* clock, and host TZ is not guaranteed even in a UTC-only world. The timezone-matrix property (`test_expiry_is_timezone_invariant`) and its `tzset` machinery are **removed** rather than completed; they test a world that does not exist here. Suite total becomes 66 tests, not 67.
2. **`hypothesis` added to dev dependencies** (commit `9454d7d`) — it was missing, so plain `uv run pytest` never collected the property module at all (the `.py.txt` name is not a test pattern). Required for any of this work to be verifiable. Known interim state: the activated stub file carries 5 lint findings inside its `TODO` bodies that self-heal when Task 7 rewrites them.

## Blast radius

Library: `retry.py`, `users.py`, `config.py`, `auth.py`, `pagination.py`, one wrapper in `client.py`. Tests: complete 9 stubs and remove the tz-matrix property in `test_properties.py`; update 12 legacy tests in `test_retry.py`, `test_users.py`, `test_client.py`, `test_cli.py`, `test_pagination.py` + the naive-clock `stamp()` helpers (same commit as the auth fix, or the suite becomes host-clock-dependent).

**Not in scope:** no new features, no CI changes, no weakening of any property or coverage gate. (One dependency change was forced during execution: `hypothesis` added to the dev group — see owner decisions.)

## Definition of done

`make lint` clean · `make test` → **66 passed** · properties green at 1000 examples per strategy · coverage 94% total, identical to base; all five fixed modules at 100%. One defect per commit, suite green after each.
