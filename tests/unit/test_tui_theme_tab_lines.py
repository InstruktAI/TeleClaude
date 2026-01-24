"""Unit tests for TUI theme tab line attributes."""

from __future__ import annotations

from teleclaude.cli.tui import theme


def test_get_tab_line_attr_dark_mode_uses_color_pair(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", True)
    monkeypatch.setattr(theme.curses, "color_pair", lambda pair_id: pair_id)

    assert theme.get_tab_line_attr() == theme._TAB_LINE_PAIR_ID


def test_get_tab_line_attr_light_mode_uses_normal(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", False)

    assert theme.get_tab_line_attr() == theme.curses.A_NORMAL
