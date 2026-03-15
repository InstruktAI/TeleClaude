"""Characterization tests for teleclaude.cli.tui.views.interaction."""

from __future__ import annotations

import pytest

from teleclaude.cli.tui.views.interaction import (
    TreeInteractionAction,
    TreeInteractionDecision,
    TreeInteractionState,
)

# --- TreeInteractionAction ---


@pytest.mark.unit
def test_tree_interaction_action_has_expected_values() -> None:
    assert TreeInteractionAction.NONE.value == "none"
    assert TreeInteractionAction.PREVIEW.value == "preview"
    assert TreeInteractionAction.TOGGLE_STICKY.value == "toggle_sticky"
    assert TreeInteractionAction.CLEAR_STICKY_PREVIEW.value == "clear_sticky_preview"


# --- TreeInteractionDecision ---


@pytest.mark.unit
def test_tree_interaction_decision_stores_action_and_now() -> None:
    decision = TreeInteractionDecision(action=TreeInteractionAction.PREVIEW, now=1.0)
    assert decision.action is TreeInteractionAction.PREVIEW
    assert decision.now == 1.0
    assert decision.clear_preview is False


@pytest.mark.unit
def test_tree_interaction_decision_clear_preview_default_is_false() -> None:
    decision = TreeInteractionDecision(TreeInteractionAction.NONE, now=0.0)
    assert decision.clear_preview is False


# --- TreeInteractionState.mark_press ---


@pytest.mark.unit
def test_mark_press_records_item_id_and_time() -> None:
    state = TreeInteractionState()
    state.mark_press("item-1", 1.5)
    assert state.last_press_item_id == "item-1"
    assert state.last_press_time == 1.5


# --- TreeInteractionState.mark_double_press_guard ---


@pytest.mark.unit
def test_mark_double_press_guard_sets_guard_item_and_expiry() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.mark_double_press_guard("item-1", 2.0)
    assert state.double_press_guard_item_id == "item-1"
    assert state.double_press_guard_until == 2.5


# --- TreeInteractionState.is_double_press_guarded ---


@pytest.mark.unit
def test_is_double_press_guarded_returns_false_when_no_guard() -> None:
    state = TreeInteractionState()
    assert state.is_double_press_guarded("item-1", 1.0) is False


@pytest.mark.unit
def test_is_double_press_guarded_returns_false_for_different_item() -> None:
    state = TreeInteractionState()
    state.mark_double_press_guard("item-1", 1.0)
    assert state.is_double_press_guarded("item-2", 1.2) is False


@pytest.mark.unit
def test_is_double_press_guarded_returns_true_within_window() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.mark_double_press_guard("item-1", 1.0)
    assert state.is_double_press_guarded("item-1", 1.3) is True


@pytest.mark.unit
def test_is_double_press_guarded_returns_false_and_clears_after_expiry() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.mark_double_press_guard("item-1", 1.0)
    # At or after guard_until (1.5) it should be cleared
    result = state.is_double_press_guarded("item-1", 1.5)
    assert result is False
    assert state.double_press_guard_item_id is None
    assert state.double_press_guard_until is None


# --- TreeInteractionState.decide_preview_action ---


@pytest.mark.unit
def test_decide_preview_action_returns_preview_on_first_press() -> None:
    state = TreeInteractionState()
    decision = state.decide_preview_action("item-1", 1.0, is_sticky=False, allow_sticky_toggle=True)
    assert decision.action is TreeInteractionAction.PREVIEW


@pytest.mark.unit
def test_decide_preview_action_returns_clear_sticky_when_sticky() -> None:
    state = TreeInteractionState()
    decision = state.decide_preview_action("item-1", 1.0, is_sticky=True, allow_sticky_toggle=True)
    assert decision.action is TreeInteractionAction.CLEAR_STICKY_PREVIEW


@pytest.mark.unit
def test_decide_preview_action_returns_toggle_sticky_on_double_press() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    # First press
    state.decide_preview_action("item-1", 1.0, is_sticky=False, allow_sticky_toggle=True)
    # Second press within threshold
    decision = state.decide_preview_action("item-1", 1.3, is_sticky=False, allow_sticky_toggle=True)
    assert decision.action is TreeInteractionAction.TOGGLE_STICKY


@pytest.mark.unit
def test_decide_preview_action_returns_none_when_guarded() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.mark_double_press_guard("item-1", 1.0)
    decision = state.decide_preview_action("item-1", 1.2, is_sticky=False, allow_sticky_toggle=True)
    assert decision.action is TreeInteractionAction.NONE


@pytest.mark.unit
def test_decide_preview_action_ignores_toggle_when_not_allowed() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.mark_press("item-1", 1.0)
    # Double-press timing, but allow_sticky_toggle=False
    decision = state.decide_preview_action("item-1", 1.3, is_sticky=False, allow_sticky_toggle=False)
    assert decision.action is TreeInteractionAction.PREVIEW


@pytest.mark.unit
def test_decide_preview_action_clear_preview_set_when_toggle_sticky_and_was_sticky() -> None:
    state = TreeInteractionState(double_press_threshold=0.5)
    state.decide_preview_action("item-1", 1.0, is_sticky=False, allow_sticky_toggle=True)
    decision = state.decide_preview_action("item-1", 1.3, is_sticky=True, allow_sticky_toggle=True)
    assert decision.action is TreeInteractionAction.TOGGLE_STICKY
    assert decision.clear_preview is True
