"""Unit tests for TTY/tmux auth state behavior."""

from __future__ import annotations

from types import SimpleNamespace

from teleclaude.cli import session_auth


def test_read_current_session_email_ignores_non_tui_tmux(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "tmux-ctx")
    monkeypatch.delenv(session_auth.TUI_SESSION_ENV_KEY, raising=False)
    monkeypatch.setenv(session_auth.TUI_AUTH_EMAIL_ENV_KEY, "admin@example.com")

    assert session_auth.read_current_session_email() is None


def test_read_current_session_email_uses_bridged_email_for_tui(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "tmux-ctx")
    monkeypatch.setenv(session_auth.TUI_SESSION_ENV_KEY, "1")
    monkeypatch.setenv(session_auth.TUI_AUTH_EMAIL_ENV_KEY, "Admin@Example.com")

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="tc_tui\n")

    monkeypatch.setattr(session_auth.subprocess, "run", _fake_run)

    assert session_auth.read_current_session_email() == "admin@example.com"


def test_read_current_session_email_rejects_wrong_tmux_session(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "tmux-ctx")
    monkeypatch.setenv(session_auth.TUI_SESSION_ENV_KEY, "1")
    monkeypatch.setenv(session_auth.TUI_AUTH_EMAIL_ENV_KEY, "admin@example.com")

    def _fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="tc_worker\n")

    monkeypatch.setattr(session_auth.subprocess, "run", _fake_run)

    assert session_auth.read_current_session_email() is None
