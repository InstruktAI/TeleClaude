"""Characterization tests for teleclaude.cli.tui.widgets.box_tab_bar."""

from __future__ import annotations

import pytest
from rich.console import Group

from teleclaude.cli.tui.widgets.box_tab_bar import PIPE_COLUMNS, BoxTabBar, _to_color

# --- _to_color ---


@pytest.mark.unit
def test_to_color_returns_string_longer_than_one_char() -> None:
    assert _to_color("#AABBCC") == "#AABBCC"


@pytest.mark.unit
def test_to_color_returns_none_for_single_char_string() -> None:
    assert _to_color("x") is None


@pytest.mark.unit
def test_to_color_returns_none_for_none() -> None:
    assert _to_color(None) is None


@pytest.mark.unit
def test_to_color_returns_none_for_int() -> None:
    assert _to_color(0) is None


# --- BoxTabBar._build_tab_specs ---


@pytest.mark.unit
def test_build_tab_specs_returns_one_entry_per_tab() -> None:
    bar = BoxTabBar()
    specs = bar._build_tab_specs(tab_gap=1)
    assert len(specs) == len(BoxTabBar.TABS)


@pytest.mark.unit
def test_build_tab_specs_marks_active_tab_correctly() -> None:
    bar = BoxTabBar()
    bar.active_tab = "sessions"
    specs = bar._build_tab_specs(tab_gap=1)
    active_entries = [(tab_id, is_active) for _, _, _, is_active, tab_id in specs]
    for tab_id, is_active in active_entries:
        if tab_id == "sessions":
            assert is_active is True
        else:
            assert is_active is False


@pytest.mark.unit
def test_build_tab_specs_columns_are_increasing() -> None:
    bar = BoxTabBar()
    specs = bar._build_tab_specs(tab_gap=1)
    cols = [col for col, _, _, _, _ in specs]
    assert cols == sorted(cols)


# --- BoxTabBar._tab_cell ---


@pytest.mark.unit
def test_tab_cell_returns_space_and_false_outside_tab_area() -> None:
    bar = BoxTabBar()
    tabs = bar._build_tab_specs(tab_gap=1)
    # x=0 should be before all tab columns (first tab starts at col=1)
    char, in_tab, _, _, _ = bar._tab_cell(
        x=0,
        y_offset=1,
        tabs=tabs,
        active_tab_bg="#FFF",
        active_tab_fg="#000",
        inactive_tab_bg="#888",
        inactive_tab_fg="#CCC",
    )
    assert in_tab is False
    assert char == " "


@pytest.mark.unit
def test_tab_cell_returns_label_char_at_y_offset_1() -> None:
    bar = BoxTabBar()
    bar.active_tab = "sessions"
    tabs = bar._build_tab_specs(tab_gap=1)
    # First tab starts at col=1, padded label = " [1] AI Sessions "
    # x=1 is inside the first tab
    char, in_tab, _, _, _ = bar._tab_cell(
        x=1,
        y_offset=1,
        tabs=tabs,
        active_tab_bg="#FFF",
        active_tab_fg="#000",
        inactive_tab_bg="#888",
        inactive_tab_fg="#CCC",
    )
    assert in_tab is True
    assert char == " "  # First char of " [1] AI Sessions " is space


@pytest.mark.unit
def test_tab_cell_returns_space_at_y_offset_0() -> None:
    """Sky row (y_offset=0): always returns space regardless of position."""
    bar = BoxTabBar()
    tabs = bar._build_tab_specs(tab_gap=1)
    char, _, _, _, _ = bar._tab_cell(
        x=2,
        y_offset=0,
        tabs=tabs,
        active_tab_bg="#FFF",
        active_tab_fg="#000",
        inactive_tab_bg="#888",
        inactive_tab_fg="#CCC",
    )
    assert char == " "


# --- BoxTabBar._label_cell foot extension ---


@pytest.mark.unit
def test_label_cell_extends_foot_pipe_when_no_tab_covers_column() -> None:
    """A foot column with no tab over it draws the support pipe down to the floor."""
    bar = BoxTabBar()
    foot_x = max(PIPE_COLUMNS)
    cell = (" ", False, False, None, None)  # not in any tab
    char, fg, _bg = bar._label_cell(foot_x, 8, cell, None, None, [], "#000000", "#808080", 60, 80)
    assert char == "║"
    assert fg == "#808080"


@pytest.mark.unit
def test_label_cell_draws_nothing_off_foot_columns() -> None:
    bar = BoxTabBar()
    off_x = max(PIPE_COLUMNS) + 1
    cell = (" ", False, False, None, None)
    char, _fg, _bg = bar._label_cell(off_x, 8, cell, None, None, [], "#000000", "#808080", 60, 80)
    assert char == " "


@pytest.mark.unit
def test_label_cell_does_not_overdraw_foot_when_tab_present() -> None:
    """A foot column covered by a tab keeps the tab label, not a pipe."""
    bar = BoxTabBar()
    foot_x = max(PIPE_COLUMNS)
    cell = ("X", True, False, "#FFFFFF", "#000000")  # inside a tab
    char, _fg, _bg = bar._label_cell(foot_x, 8, cell, None, None, [], "#000000", "#808080", 60, 80)
    assert char == "X"


@pytest.mark.unit
def test_render_uses_cached_group_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    bar = BoxTabBar()
    cached = Group()
    bar.set_cached_render(cached)
    monkeypatch.setattr(bar, "_render_tabs", lambda: (_ for _ in ()).throw(AssertionError("unexpected render")))

    assert bar.render() is cached
