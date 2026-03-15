"""Characterization tests for teleclaude.cli.tui.views.sessions_highlights."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.views.sessions_highlights import (
    HIDDEN_SESSION_STATUSES,
    PREVIEW_HIGHLIGHT_DURATION,
    SessionsViewHighlightsMixin,
)

# --- module constants ---


@pytest.mark.unit
def test_preview_highlight_duration_pinned() -> None:
    assert PREVIEW_HIGHLIGHT_DURATION == 3.0


@pytest.mark.unit
def test_hidden_session_statuses_contains_closing_and_closed() -> None:
    assert "closing" in HIDDEN_SESSION_STATUSES
    assert "closed" in HIDDEN_SESSION_STATUSES


# --- SessionsViewHighlightsMixin (via minimal fake host) ---


def _make_mixin() -> SessionsViewHighlightsMixin:
    """Build a minimal fake host object that satisfies the mixin's attr requirements."""
    obj = SessionsViewHighlightsMixin()
    obj._input_highlights = set()
    obj._output_highlights = set()
    obj._last_output_summary = {}
    obj._nav_items = []
    obj._sticky_session_ids = set()
    obj._collapsed_sessions = set()
    obj._optimistically_hidden_session_ids = set()
    obj._sessions = []
    obj._computers = []
    obj._projects = []
    obj._availability = {}
    obj._highlighted_session_id = None
    obj.preview_session_id = None
    obj._cancel_highlight_timer = MagicMock()
    obj._schedule_highlight_clear = MagicMock()
    obj._notify_state_changed = MagicMock()
    obj.update_data = MagicMock()
    return obj


@pytest.mark.unit
def test_set_input_highlight_adds_session_to_input_set() -> None:
    host = _make_mixin()
    host.set_input_highlight("sess-1")
    assert "sess-1" in host._input_highlights


@pytest.mark.unit
def test_set_input_highlight_removes_from_output_set() -> None:
    host = _make_mixin()
    host._output_highlights.add("sess-1")
    host.set_input_highlight("sess-1")
    assert "sess-1" not in host._output_highlights


@pytest.mark.unit
def test_set_output_highlight_adds_session_to_output_set() -> None:
    host = _make_mixin()
    host.set_output_highlight("sess-2")
    assert "sess-2" in host._output_highlights


@pytest.mark.unit
def test_set_output_highlight_removes_from_input_set() -> None:
    host = _make_mixin()
    host._input_highlights.add("sess-2")
    host.set_output_highlight("sess-2")
    assert "sess-2" not in host._input_highlights


@pytest.mark.unit
def test_set_output_highlight_stores_summary() -> None:
    host = _make_mixin()
    host.set_output_highlight("sess-3", summary="done")
    summary_entry = host._last_output_summary.get("sess-3")
    assert summary_entry is not None
    assert summary_entry["text"] == "done"


@pytest.mark.unit
def test_clear_highlight_removes_from_both_sets() -> None:
    host = _make_mixin()
    host._input_highlights.add("sess-4")
    host._output_highlights.add("sess-4")
    host.clear_highlight("sess-4")
    assert "sess-4" not in host._input_highlights
    assert "sess-4" not in host._output_highlights


@pytest.mark.unit
def test_set_input_highlight_calls_notify_state_changed() -> None:
    host = _make_mixin()
    host.set_input_highlight("sess-5")
    host._notify_state_changed.assert_called_once()


@pytest.mark.unit
def test_get_persisted_state_includes_required_keys() -> None:
    host = _make_mixin()
    state = host.get_persisted_state()
    assert "sticky_sessions" in state
    assert "input_highlights" in state
    assert "output_highlights" in state
    assert "last_output_summary" in state
    assert "collapsed_sessions" in state
    assert "preview" in state
    assert "highlighted_session_id" in state


@pytest.mark.unit
def test_get_persisted_state_sticky_sessions_contains_all_ids() -> None:
    host = _make_mixin()
    host._sticky_session_ids.add("z-session")
    host._sticky_session_ids.add("a-session")
    state = host.get_persisted_state()
    ids = {item["session_id"] for item in state["sticky_sessions"]}
    assert ids == {"z-session", "a-session"}


@pytest.mark.unit
def test_get_persisted_state_preview_is_none_when_no_preview() -> None:
    host = _make_mixin()
    state = host.get_persisted_state()
    assert state["preview"] is None


@pytest.mark.unit
def test_get_persisted_state_preview_wraps_session_id_when_set() -> None:
    host = _make_mixin()
    host.preview_session_id = "sess-preview"
    state = host.get_persisted_state()
    assert state["preview"] == {"session_id": "sess-preview"}
