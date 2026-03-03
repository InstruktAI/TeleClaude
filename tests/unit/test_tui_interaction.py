"""Unit tests for TreeInteractionState gesture classification."""

from teleclaude.cli.tui.views.interaction import (
    TreeInteractionAction,
    TreeInteractionState,
)


def _state() -> TreeInteractionState:
    return TreeInteractionState(double_press_threshold=0.65)


def test_first_press_previews():
    """First press on any item produces a PREVIEW action."""
    s = _state()
    d = s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.PREVIEW


def test_single_press_sticky_clears_preview():
    """Single press on a sticky session clears its preview."""
    s = _state()
    d = s.decide_preview_action("sess-1", now=1.0, is_sticky=True, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.CLEAR_STICKY_PREVIEW


def test_double_press_toggles_sticky():
    """Rapid double press toggles sticky state."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=True)
    d = s.decide_preview_action("sess-1", now=1.3, is_sticky=False, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.TOGGLE_STICKY


def test_double_press_on_sticky_clears_preview():
    """Double press on already-sticky session toggles off and clears preview."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=True, allow_sticky_toggle=True)
    d = s.decide_preview_action("sess-1", now=1.3, is_sticky=True, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.TOGGLE_STICKY
    assert d.clear_preview is True


def test_slow_double_press_previews_again():
    """Presses beyond threshold are treated as separate single presses."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=True)
    d = s.decide_preview_action("sess-1", now=2.0, is_sticky=False, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.PREVIEW


def test_triple_press_guarded():
    """Third rapid press after a toggle is suppressed by the guard."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=True)
    s.decide_preview_action("sess-1", now=1.3, is_sticky=False, allow_sticky_toggle=True)
    s.mark_double_press_guard("sess-1", now=1.3)
    d = s.decide_preview_action("sess-1", now=1.5, is_sticky=False, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.NONE


def test_guard_expires():
    """Guard window expires and allows normal actions again."""
    s = _state()
    s.mark_double_press_guard("sess-1", now=1.0)
    assert s.is_double_press_guarded("sess-1", now=1.3) is True
    assert s.is_double_press_guarded("sess-1", now=2.0) is False


def test_guard_different_item_not_blocked():
    """Guard on one item doesn't block a different item."""
    s = _state()
    s.mark_double_press_guard("sess-1", now=1.0)
    assert s.is_double_press_guarded("sess-2", now=1.3) is False


def test_sticky_toggle_disabled():
    """When allow_sticky_toggle=False, double press just previews again."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=False)
    d = s.decide_preview_action("sess-1", now=1.3, is_sticky=False, allow_sticky_toggle=False)
    assert d.action == TreeInteractionAction.PREVIEW


def test_different_items_dont_double_press():
    """Pressing different items in quick succession doesn't trigger toggle."""
    s = _state()
    s.decide_preview_action("sess-1", now=1.0, is_sticky=False, allow_sticky_toggle=True)
    d = s.decide_preview_action("sess-2", now=1.3, is_sticky=False, allow_sticky_toggle=True)
    assert d.action == TreeInteractionAction.PREVIEW


def test_mark_press_updates_state():
    """mark_press records timestamp and item."""
    s = _state()
    s.mark_press("sess-1", now=5.0)
    assert s.last_press_item_id == "sess-1"
    assert s.last_press_time == 5.0
