"""Characterization tests for teleclaude.cli.tui.widgets.status_bar."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.widgets.status_bar import StatusBar

# --- StatusBar._build_pane_theming_cells ---


@pytest.mark.unit
def test_build_pane_theming_cells_returns_four_cells() -> None:
    bar = StatusBar()
    cells = bar._build_pane_theming_cells()
    assert len(cells) == 4


@pytest.mark.unit
def test_build_pane_theming_cells_all_outline_when_mode_off() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "off"
    cells = bar._build_pane_theming_cells()
    chars = [ch for ch, _ in cells]
    assert all(ch == "\u25fb" for ch in chars)  # all outline squares


@pytest.mark.unit
def test_build_pane_theming_cells_one_filled_when_highlight() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "highlight"
    cells = bar._build_pane_theming_cells()
    filled = sum(1 for ch, _ in cells if ch == "\u25fc")
    assert filled == 1


@pytest.mark.unit
def test_build_pane_theming_cells_two_filled_when_highlight2() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "highlight2"
    cells = bar._build_pane_theming_cells()
    filled = sum(1 for ch, _ in cells if ch == "\u25fc")
    assert filled == 2


@pytest.mark.unit
def test_build_pane_theming_cells_three_filled_when_agent() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "agent"
    cells = bar._build_pane_theming_cells()
    filled = sum(1 for ch, _ in cells if ch == "\u25fc")
    assert filled == 3


@pytest.mark.unit
def test_build_pane_theming_cells_four_filled_when_agent_plus() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "agent_plus"
    cells = bar._build_pane_theming_cells()
    filled = sum(1 for ch, _ in cells if ch == "\u25fc")
    assert filled == 4


# --- StatusBar.load_persisted_state ---


@pytest.mark.unit
def test_load_persisted_state_restores_animation_mode() -> None:
    bar = StatusBar()
    bar.load_persisted_state({"animation_mode": "periodic"})
    assert bar.animation_mode == "periodic"


@pytest.mark.unit
def test_load_persisted_state_ignores_invalid_animation_mode() -> None:
    bar = StatusBar()
    bar.animation_mode = "off"
    bar.load_persisted_state({"animation_mode": "invalid-mode"})
    assert bar.animation_mode == "off"


@pytest.mark.unit
def test_load_persisted_state_ignores_invalid_pane_theming_mode() -> None:
    bar = StatusBar()
    bar.pane_theming_mode = "off"
    bar.load_persisted_state({"pane_theming_mode": "bogus-invalid"})
    assert bar.pane_theming_mode == "off"


@pytest.mark.unit
def test_load_persisted_state_ignores_missing_animation_mode() -> None:
    bar = StatusBar()
    bar.animation_mode = "party"
    bar.load_persisted_state({})
    assert bar.animation_mode == "party"


# --- StatusBar.get_persisted_state ---


@pytest.mark.unit
def test_get_persisted_state_includes_animation_and_pane_theming() -> None:
    bar = StatusBar()
    state = bar.get_persisted_state()
    assert "animation_mode" in state
    assert "pane_theming_mode" in state


@pytest.mark.unit
def test_get_persisted_state_reflects_current_mode() -> None:
    bar = StatusBar()
    bar.animation_mode = "party"
    bar.pane_theming_mode = "agent"
    state = bar.get_persisted_state()
    assert state["animation_mode"] == "party"
    assert state["pane_theming_mode"] == "agent"
