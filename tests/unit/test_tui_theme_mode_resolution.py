"""Unit tests for TUI theme mode source precedence."""

from __future__ import annotations

from teleclaude.cli.tui import theme


def test_is_dark_mode_prefers_env_override(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: "light")
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: "dark")
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")

    assert theme.is_dark_mode() is False


def test_is_dark_mode_prefers_system_over_tmux(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: "light")
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")

    assert theme.is_dark_mode() is False


def test_is_dark_mode_uses_tmux_when_system_unknown(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")

    assert theme.is_dark_mode() is True


def test_get_system_dark_mode_none_when_unknown(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: None)
    assert theme.get_system_dark_mode() is None
