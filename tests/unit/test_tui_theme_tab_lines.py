"""Unit tests for TUI theme tab line attributes."""

from __future__ import annotations

from teleclaude.cli.tui import theme


def test_get_tab_line_attr_returns_zero_stub() -> None:
    """get_tab_line_attr is a legacy stub that returns 0."""
    assert theme.get_tab_line_attr() == 0


def test_get_tab_line_attr_light_mode_returns_zero(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", False)

    assert theme.get_tab_line_attr() == 0
