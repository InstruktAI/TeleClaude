"""Unit tests for footer widget rendering and click target behavior."""

from __future__ import annotations

import curses

from teleclaude.cli.tui.theme import AGENT_COLORS
from teleclaude.cli.tui.widgets.footer import Footer


class _FakeScreen:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str, int | None]] = []

    def addstr(self, row: int, col: int, text: str, attr: int | None = None) -> None:
        self.calls.append((row, col, text, attr))


def _assert_indicator(
    screen: _FakeScreen,
    footer: Footer,
    *,
    fill_attrs: dict[int, int],
    expected_width: int = 4,
) -> None:
    indicator_cells = [
        call for call in screen.calls if footer._pane_theming_col_start <= call[1] < footer._pane_theming_col_end
    ]
    assert len(indicator_cells) == expected_width
    expected_box_chars: list[str] = []
    for slot in range(4):
        expected_box_chars.append("◼" if slot in fill_attrs else "◻")
    assert [cell[2] for cell in indicator_cells] == expected_box_chars
    outline_attr = 33 | curses.A_DIM
    for idx, (_, _, char, attr) in enumerate(indicator_cells):
        if char == " ":
            assert attr == curses.A_DIM
        elif idx in fill_attrs:
            assert attr == fill_attrs[idx]
        else:
            assert attr == outline_attr


def test_footer_renders_enabled_tts_icon_and_click_region(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.curses.color_pair", lambda n: n)
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.get_agent_status_color_pair", lambda agent, muted: 33)

    footer = Footer({}, tts_enabled=True, pane_theming_mode="full", pane_theming_agent="codex")
    screen = _FakeScreen()
    footer.render(screen, row=0, width=80)

    _assert_indicator(
        screen,
        footer,
        fill_attrs={
            0: AGENT_COLORS["claude"]["normal"],
            1: AGENT_COLORS["gemini"]["normal"],
            2: AGENT_COLORS["codex"]["normal"],
            3: AGENT_COLORS["codex"]["highlight"],
        },
    )

    assert any(text == "🔊" for _, _, text, _ in screen.calls)
    assert footer._tts_col_end - footer._tts_col_start == Footer._display_width("🔊")
    assert footer._pane_theming_col_end - footer._pane_theming_col_start == 4
    assert footer.handle_click(footer._tts_col_start) == "tts"
    assert footer.handle_click(footer._tts_col_end) is None
    assert footer.handle_click(footer._pane_theming_col_start) == "pane_theming_mode"


def test_footer_renders_off_theming_mode(monkeypatch) -> None:
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.curses.color_pair", lambda n: n)
    monkeypatch.setattr("teleclaude.cli.tui.widgets.footer.get_agent_status_color_pair", lambda agent, muted: 33)

    footer = Footer({}, tts_enabled=False, pane_theming_mode="off", pane_theming_agent="claude")
    screen = _FakeScreen()
    footer.render(screen, row=0, width=80)

    _assert_indicator(
        screen,
        footer,
        fill_attrs={},
    )

    assert any(text == "🔇" for _, _, text, _ in screen.calls)
    assert footer._pane_theming_col_end - footer._pane_theming_col_start == 4
    assert footer._tts_col_end - footer._tts_col_start == Footer._display_width("🔇")
