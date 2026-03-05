"""Test tab bar rendering: sky gaps, transition row, and color consistency."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rich.style import Style

_MOD = "teleclaude.cli.tui.widgets.box_tab_bar"

# Light-mode Solarized colors
TERMINAL_BG = "#FDF6E3"
INACTIVE_BG = "#EDE8D0"
SKY_FALLBACK = "#C8E8F8"


def _style_at(text, pos):
    """Extract the merged Style at a character position in a Rich Text."""
    style = Style.null()
    for span in text._spans:
        if span.start <= pos < span.end:
            style = style + span.style
    return style


def _bg_hex(style):
    """Extract bgcolor as lowercase hex from a Style."""
    if style.bgcolor:
        return style.bgcolor.get_truecolor().hex
    return None


def _make_fake_bar():
    """Create a fake self that BoxTabBar._render_tabs can use."""
    from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar

    fake = SimpleNamespace(
        TABS=BoxTabBar.TABS,
        active_tab="sessions",
        animation_engine=None,
        _click_regions=[],
        size=SimpleNamespace(width=80),
    )
    return fake


@pytest.fixture()
def _light_mode():
    with (
        patch(f"{_MOD}.is_dark_mode", return_value=False),
        patch(f"{_MOD}.get_terminal_background", return_value=TERMINAL_BG),
        patch(f"{_MOD}.resolve_haze", side_effect=lambda x: x),
        patch(f"{_MOD}.get_neutral_color", return_value="#888888"),
        patch(f"{_MOD}.blend_colors", side_effect=lambda a, b, p: a),
    ):
        yield


def _render(fake):
    from teleclaude.cli.tui.widgets.box_tab_bar import BoxTabBar

    result = BoxTabBar._render_tabs(fake)
    return list(result.renderables)


@pytest.mark.usefixtures("_light_mode")
def test_between_tabs_is_sky():
    """Gaps between tabs should still be sky-colored."""
    rows = _render(_make_fake_bar())
    # First tab: col=1, padded label " [1] AI Sessions " = 19 chars, +2 border = 21
    # So tab occupies x=1..21, gap starts at x=22 (with tab_gap=3: x=22,23,24)
    gap_x = 22
    bg = _bg_hex(_style_at(rows[1], gap_x))
    assert bg != TERMINAL_BG.lower(), f"Gap at x={gap_x} should be sky, got {bg}"


@pytest.mark.usefixtures("_light_mode")
def test_transition_row_under_tabs_is_pane():
    """Transition row under ALL tabs should use pane_bg."""
    rows = _render(_make_fake_bar())
    pane = TERMINAL_BG.lower()
    # Active tab (sessions) at x=5
    bg_active = _bg_hex(_style_at(rows[2], 5))
    assert bg_active == pane, f"Active tab transition should be pane_bg, got {bg_active}"
    # Inactive tab at x=79 (tab 4)
    bg_inactive = _bg_hex(_style_at(rows[2], 79))
    assert bg_inactive == pane, f"Inactive tab transition should be pane_bg, got {bg_inactive}"


@pytest.mark.usefixtures("_light_mode")
def test_active_tab_bg_uses_pane_bg():
    """Active tab bg should use pane_bg (terminal background) in light mode."""
    rows = _render(_make_fake_bar())
    # In light mode, active_tab_bg = pane_bg = resolve_haze(get_terminal_background())
    expected = TERMINAL_BG.lower()
    # Row 1 (label row), x=5 is inside active tab
    bg = _bg_hex(_style_at(rows[1], 5))
    assert bg == expected, f"Active tab bg should match pane_bg, got {bg}"
