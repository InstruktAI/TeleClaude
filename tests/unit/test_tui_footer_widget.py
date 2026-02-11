"""Unit tests for footer widget rendering and click target behavior."""

from __future__ import annotations

from teleclaude.cli.tui.widgets.footer import Footer


class _FakeScreen:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str, int | None]] = []

    def addstr(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.calls.append((row, col, text, attr))


def test_footer_renders_enabled_tts_icon_and_click_region(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.curses.color_pair", lambda n: n)
    footer = Footer({}, tts_enabled=True)
    screen = _FakeScreen()

    footer.render(screen, row=0, width=80)

    assert any(text == "🔊" for _, _, text, _ in screen.calls)
    assert footer._tts_col_end - footer._tts_col_start == Footer._display_width("🔊")
    assert footer.handle_click(footer._tts_col_start) is True
    assert footer.handle_click(footer._tts_col_end) is False


def test_footer_renders_disabled_tts_icon(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.curses.color_pair", lambda n: n)
    footer = Footer({}, tts_enabled=False)
    screen = _FakeScreen()

    footer.render(screen, row=0, width=80)

    assert any(text == "🔇" for _, _, text, _ in screen.calls)
    assert footer._tts_col_end - footer._tts_col_start == Footer._display_width("🔇")
