"""Unit tests for TUI theme background derivation."""

from __future__ import annotations

from teleclaude.cli.tui import theme


def test_terminal_background_light_mode_uses_paper_when_no_hint(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", False)
    monkeypatch.setattr(theme, "_terminal_bg_cache", None)
    monkeypatch.setattr(theme, "_read_terminal_bg_from_appearance", lambda: None)

    assert theme.get_terminal_background() == "#fdf6e3"


def test_terminal_background_dark_mode_uses_black_when_no_hint(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", True)
    monkeypatch.setattr(theme, "_terminal_bg_cache", None)
    monkeypatch.setattr(theme, "_read_terminal_bg_from_appearance", lambda: None)

    assert theme.get_terminal_background() == "#000000"


def test_terminal_background_blends_with_matching_hint(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", False)
    monkeypatch.setattr(theme, "_terminal_bg_cache", None)
    monkeypatch.setattr(theme, "_read_terminal_bg_from_appearance", lambda: "#faf2d8")

    # Matching light hint should influence baseline paper color.
    result = theme.get_terminal_background()
    assert result != "#fdf6e3"
    assert result.startswith("#")
    assert len(result) == 7


def test_terminal_background_ignores_mode_conflicting_hint(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_is_dark_mode", False)
    monkeypatch.setattr(theme, "_terminal_bg_cache", None)
    # Very dark hint conflicts with light mode and should be rejected.
    monkeypatch.setattr(theme, "_read_terminal_bg_from_appearance", lambda: "#101010")

    assert theme.get_terminal_background() == "#fdf6e3"


def test_init_colors_resets_terminal_cache(monkeypatch) -> None:
    monkeypatch.setattr(theme, "_terminal_bg_cache", "#abc123")
    monkeypatch.setattr(theme, "is_dark_mode", lambda: True)
    monkeypatch.setattr(theme.curses, "start_color", lambda: None)
    monkeypatch.setattr(theme.curses, "use_default_colors", lambda: None)
    monkeypatch.setattr(theme.curses, "init_pair", lambda *_args, **_kwargs: None)

    theme.init_colors()

    assert theme._terminal_bg_cache is None
