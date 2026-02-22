"""Unit tests for TUI theme mode source precedence."""

from __future__ import annotations

from types import SimpleNamespace

from teleclaude.cli.tui import theme


def test_is_dark_mode_prefers_env_override(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: "light")
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: "dark")
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")

    # refresh_mode re-probes and updates the cached value
    theme.refresh_mode()
    assert theme.is_dark_mode() is False


def test_is_dark_mode_prefers_system_over_tmux(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: "light")
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")

    theme.refresh_mode()
    assert theme.is_dark_mode() is False


def test_is_dark_mode_uses_tmux_when_system_unknown(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_env_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: None)
    monkeypatch.setattr(theme, "_get_tmux_appearance_mode", lambda: "dark")
    # Force non-darwin so the tmux fallback path is reached (darwin short-circuits
    # to the module-level cached value, skipping tmux intentionally).
    monkeypatch.setattr(theme.sys, "platform", "linux")

    theme.refresh_mode()
    assert theme.is_dark_mode() is True


def test_get_system_dark_mode_none_when_unknown(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_get_system_appearance_mode", lambda: None)
    assert theme.get_system_dark_mode() is None


def test_system_appearance_mode_returns_light_for_missing_key(monkeypatch) -> None:
    monkeypatch.setattr(theme.sys, "platform", "darwin")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="",
            stderr="The domain/default pair of (-g, AppleInterfaceStyle) does not exist",
            returncode=1,
        ),
    )

    assert theme._get_system_appearance_mode() == "light"


def test_system_appearance_mode_returns_none_for_other_errors(monkeypatch) -> None:
    monkeypatch.setattr(theme.sys, "platform", "darwin")
    monkeypatch.setattr(
        theme.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="",
            stderr="launch services unavailable",
            returncode=1,
        ),
    )

    assert theme._get_system_appearance_mode() is None
