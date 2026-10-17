"""Tests for accountsync.auth."""

from datetime import UTC, datetime, timedelta

from accountsync.auth import ISO_FORMAT, is_expired, parse_expiry, seconds_remaining


def _stamp(delta):
    return (datetime.now(UTC) + delta).strftime(ISO_FORMAT)


def test_parses_iso_timestamp():
    assert parse_expiry("2026-08-30T12:00:00Z") == datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def test_token_in_the_past_is_expired():
    assert is_expired(_stamp(timedelta(hours=-1))) is True


def test_token_an_hour_out_is_valid():
    assert is_expired(_stamp(timedelta(hours=1))) is False


def test_token_inside_skew_window_is_expired():
    assert is_expired(_stamp(timedelta(seconds=10))) is True


def test_token_outside_skew_window_is_valid():
    assert is_expired(_stamp(timedelta(seconds=120))) is False


def test_seconds_remaining_is_never_negative():
    assert seconds_remaining(_stamp(timedelta(hours=-5))) == 0.0


def test_seconds_remaining_counts_down():
    remaining = seconds_remaining(_stamp(timedelta(minutes=10)))
    assert 590 <= remaining <= 600
