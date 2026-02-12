"""Unit tests for TUI footer separator rendering."""

from __future__ import annotations

from teleclaude.cli.tui.app import TelecApp
from tests.conftest import MockAPIClient


class _DummyView:
    def render(self, _stdscr: object, _row: int, _height: int, _width: int) -> None:
        return None

    def get_action_bar(self) -> str:
        return ""

    def rebuild_for_focus(self) -> None:
        return None


class _FakeScreen:
    def __init__(self, height: int, width: int) -> None:
        self._height = height
        self._width = width
        self.calls: list[tuple[int, int, str, int | None]] = []

    def erase(self) -> None:
        return None

    def getmaxyx(self) -> tuple[int, int]:
        return self._height, self._width

    def addstr(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.calls.append((row, col, text, attr))

    def move(self, _y: int, _x: int) -> None:
        return None

    def refresh(self) -> None:
        return None


def test_footer_separator_uses_tab_line_attr(monkeypatch) -> None:
    app = TelecApp(MockAPIClient())
    app.views[1] = _DummyView()
    app.current_view = 1
    app.tab_bar.render = lambda *_args, **_kwargs: None

    sentinel_attr = 999
    monkeypatch.setattr("teleclaude.cli.tui.app.get_tab_line_attr", lambda: sentinel_attr)
    monkeypatch.setattr("teleclaude.cli.tui.app.render_banner", lambda *_args, **_kwargs: None)

    screen = _FakeScreen(height=20, width=40)
    app._render(screen)

    separator_row = 20 - 4
    matches = [call for call in screen.calls if call[0] == separator_row and call[2] == "─" * 39]

    assert matches, "Separator line not rendered"
    assert matches[0][3] == sentinel_attr
