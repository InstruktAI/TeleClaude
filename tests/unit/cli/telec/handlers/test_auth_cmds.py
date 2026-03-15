from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

auth_cmds = importlib.import_module("teleclaude.cli.telec.handlers.auth_cmds")


def test_handle_auth_routes_conversational_whoami(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    monkeypatch.delenv(auth_cmds.TMUX_ENV_KEY, raising=False)
    monkeypatch.setattr(auth_cmds, "_handle_whoami", lambda args: received.append(args))

    auth_cmds._handle_auth(["who", "am", "i?", "extra"])

    assert received == [["extra"]]


def test_handle_auth_rejects_tmux_sessions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv(auth_cmds.TMUX_ENV_KEY, "1")

    with pytest.raises(SystemExit) as exc_info:
        auth_cmds._handle_auth(["login", "person@example.com"])

    assert exc_info.value.code == 1
    assert "tmux" in capsys.readouterr().out


def test_role_for_email_matches_loaded_person() -> None:
    people = [SimpleNamespace(email="person@example.com", role="admin")]
    loader_module = SimpleNamespace(load_global_config=lambda: SimpleNamespace(people=people))

    with patch.dict(sys.modules, {"teleclaude.config.loader": loader_module}):
        assert auth_cmds._role_for_email(" PERSON@example.com ") == "admin"


def test_handle_login_records_email_and_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    auth_state = SimpleNamespace(
        email="person@example.com",
        context=SimpleNamespace(tty="ttys001", auth_path=Path("/tmp/telec-auth")),
    )

    monkeypatch.setattr(auth_cmds, "write_current_session_email", lambda _email: auth_state)
    monkeypatch.setattr(auth_cmds, "_role_for_email", lambda _email: "admin")

    auth_cmds._handle_login(["person@example.com"])

    output = capsys.readouterr().out
    assert "person@example.com" in output
    assert "ttys001" in output
    assert "/tmp/telec-auth" in output


def test_handle_whoami_reads_tty_session_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = SimpleNamespace(tty="ttys001", auth_path=Path("/tmp/telec-auth"))

    monkeypatch.delenv("TELEC_SESSION_TOKEN", raising=False)
    monkeypatch.setattr(auth_cmds, "get_current_session_context", lambda: context)
    monkeypatch.setattr(auth_cmds, "read_current_session_email", lambda: "person@example.com")
    monkeypatch.setattr(auth_cmds, "_role_for_email", lambda _email: "operator")

    auth_cmds._handle_whoami([])

    output = capsys.readouterr().out
    assert "person@example.com" in output
    assert "operator" in output
    assert "ttys001" in output


def test_handle_logout_clears_current_tty_login(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        auth_cmds,
        "get_current_session_context",
        lambda: SimpleNamespace(tty="ttys001", auth_path=Path("/tmp/telec-auth")),
    )
    monkeypatch.setattr(auth_cmds, "clear_current_session_email", lambda: True)

    auth_cmds._handle_logout([])

    assert "ttys001" in capsys.readouterr().out
