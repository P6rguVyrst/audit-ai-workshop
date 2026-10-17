"""Tests for accountsync.cli."""

import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from accountsync.cli import build_parser, main
from tests.helpers import ok_response, stamp


@pytest.fixture(autouse=True)
def in_tmp_cwd(tmp_path, monkeypatch):
    """Run each CLI test in an empty directory so no stray config is picked up."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_subcommand_is_required():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([])
    assert exc.value.code == 2


def test_unknown_subcommands_are_rejected():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["nope"])
    assert exc.value.code == 2


def test_config_prints_the_defaults(capsys):
    assert main(["config"]) == 0

    config = json.loads(capsys.readouterr().out)
    assert config["timeout"] == 30
    assert config["retries"] == 3


def test_config_file_overrides_the_defaults(in_tmp_cwd, capsys):
    path = in_tmp_cwd / "accountsync.json"
    path.write_text(json.dumps({"timeout": 5}))

    assert main(["--config", str(path), "config"]) == 0
    assert json.loads(capsys.readouterr().out)["timeout"] == 5


def test_the_environment_overrides_the_config_file(in_tmp_cwd, monkeypatch, capsys):
    path = in_tmp_cwd / "accountsync.json"
    path.write_text(json.dumps({"retries": 5}))
    monkeypatch.setenv("ACCOUNTSYNC_RETRIES", "9")

    assert main(["--config", str(path), "config"]) == 0
    assert json.loads(capsys.readouterr().out)["retries"] == 9


def test_command_line_flags_win(in_tmp_cwd, monkeypatch, capsys):
    monkeypatch.setenv("ACCOUNTSYNC_RETRIES", "9")

    assert main(["--retries", "2", "config"]) == 0
    assert json.loads(capsys.readouterr().out)["retries"] == 2


def test_a_broken_config_file_exits_non_zero(in_tmp_cwd, capsys):
    path = in_tmp_cwd / "accountsync.json"
    path.write_text("{not json")

    assert main(["--config", str(path), "config"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


@patch("accountsync.users.requests.get")
def test_user_prints_the_record(mock_get, capsys):
    mock_get.return_value = ok_response({"id": 42, "email": "ada@example.com"})

    assert main(["user", "42"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id": 42, "email": "ada@example.com"}


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


def test_token_reports_a_live_token(capsys):
    assert main(["token", stamp(timedelta(hours=1))]) == 0

    out = capsys.readouterr().out
    assert out.startswith("valid:")


def test_token_reports_a_dead_token(capsys):
    assert main(["token", stamp(timedelta(hours=-1))]) == 0

    out = capsys.readouterr().out
    assert out.startswith("expired:")
    assert "0s remaining" in out
