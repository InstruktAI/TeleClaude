"""Unit tests for the canonical session-pane layout model."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.layout_model import (
    MAX_STICKY,
    CellOp,
    desired,
    diff_cells,
    enforce_i1,
    orphan_panes,
    tier_for,
)

# --- enforce_i1 (invariant I1) ---


@pytest.mark.unit
def test_enforce_i1_keeps_preview_when_not_sticky() -> None:
    preview = "c"
    assert enforce_i1(["a", "b"], preview) == preview


@pytest.mark.unit
def test_enforce_i1_drops_preview_when_already_sticky() -> None:
    assert enforce_i1(["a", "b"], "b") is None


@pytest.mark.unit
def test_enforce_i1_passes_through_none_preview() -> None:
    assert enforce_i1(["a"], None) is None


# --- desired() truth table ---


@pytest.mark.unit
def test_desired_no_preview_is_just_stickies() -> None:
    assert desired(["a", "b"], None) == ["a", "b"]


@pytest.mark.unit
def test_desired_preview_already_sticky_folds_to_stickies() -> None:
    # I1 fold: a preview that equals a sticky never adds a cell.
    assert desired(["a", "b"], "b") == ["a", "b"]


@pytest.mark.unit
def test_desired_preview_appended_when_under_max() -> None:
    assert desired(["a", "b"], "c") == ["a", "b", "c"]


@pytest.mark.unit
def test_desired_preview_appended_with_zero_stickies() -> None:
    assert desired([], "c") == ["c"]


@pytest.mark.unit
def test_desired_five_stickies_borrows_last_cell_for_preview() -> None:
    stickies = ["a", "b", "c", "d", "e"]
    # 5 stickies + non-sticky preview -> last sticky cell is borrowed.
    assert desired(stickies, "x") == ["a", "b", "c", "d", "x"]


@pytest.mark.unit
def test_desired_five_stickies_no_preview_keeps_all_five() -> None:
    stickies = ["a", "b", "c", "d", "e"]
    assert desired(stickies, None) == stickies


@pytest.mark.unit
def test_desired_borrow_and_revert_stay_same_tier() -> None:
    stickies = ["a", "b", "c", "d", "e"]
    borrowed = desired(stickies, "x")
    reverted = desired(stickies, None)
    assert len(borrowed) == len(reverted) == MAX_STICKY


@pytest.mark.unit
def test_desired_does_not_mutate_input() -> None:
    stickies = ["a", "b"]
    desired(stickies, "c")
    assert stickies == ["a", "b"]


# --- tier_for ---


@pytest.mark.unit
def test_tier_for_counts_the_tui_pane() -> None:
    assert tier_for(0) == 1
    assert tier_for(5) == 6


# --- diff_cells ---


@pytest.mark.unit
def test_diff_cells_flags_tier_change_when_counts_differ() -> None:
    result = diff_cells(["a", "b"], ["a", "b", "c"])
    assert result.tier_changed is True
    assert result.cells == []


@pytest.mark.unit
def test_diff_cells_same_tier_marks_only_changed_cell_as_swap() -> None:
    result = diff_cells(["a", "b", "c"], ["a", "b", "x"])
    assert result.tier_changed is False
    ops = {cell.index: cell.op for cell in result.cells}
    assert ops == {1: CellOp.KEEP, 2: CellOp.KEEP, 3: CellOp.SWAP}


@pytest.mark.unit
def test_diff_cells_borrow_revert_swaps_single_cell() -> None:
    borrowed = ["a", "b", "c", "d", "x"]
    reverted = ["a", "b", "c", "d", "e"]
    result = diff_cells(borrowed, reverted)
    assert result.tier_changed is False
    swaps = [cell.index for cell in result.cells if cell.op is CellOp.SWAP]
    assert swaps == [5]


@pytest.mark.unit
def test_diff_cells_carries_target_session_id_per_cell() -> None:
    target = "z"
    result = diff_cells(["a"], [target])
    assert result.cells[0].session_id == target
    assert result.cells[0].op is CellOp.SWAP


@pytest.mark.unit
def test_diff_cells_empty_to_empty_is_no_change() -> None:
    result = diff_cells([], [])
    assert result.tier_changed is False
    assert result.cells == []


# --- orphan_panes ---


@pytest.mark.unit
def test_orphan_panes_excludes_tui_and_kept_panes() -> None:
    live = {"%0", "%1", "%2", "%9"}
    result = orphan_panes(live, tui_pane="%0", keep_panes={"%1", "%2"})
    assert result == ["%9"]


@pytest.mark.unit
def test_orphan_panes_returns_empty_when_all_accounted_for() -> None:
    live = {"%0", "%1"}
    assert orphan_panes(live, tui_pane="%0", keep_panes={"%1"}) == []


@pytest.mark.unit
def test_orphan_panes_sorted_for_determinism() -> None:
    live = {"%0", "%5", "%3", "%4"}
    assert orphan_panes(live, tui_pane="%0", keep_panes=set()) == ["%3", "%4", "%5"]
