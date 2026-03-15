from __future__ import annotations

import pytest

from teleclaude.cli.tui.state import Intent, IntentType, TuiState, reduce_state


@pytest.mark.unit
def test_preview_intents_set_and_clear_the_current_preview() -> None:
    state = TuiState()

    reduce_state(state, Intent(IntentType.SET_PREVIEW, {"session_id": "session-1"}))
    assert state.sessions.preview is not None
    assert state.sessions.preview.session_id == "session-1"

    reduce_state(state, Intent(IntentType.CLEAR_PREVIEW))
    assert state.sessions.preview is None


@pytest.mark.unit
def test_toggle_sticky_keeps_only_the_first_five_sessions() -> None:
    state = TuiState()

    for session_id in ["s1", "s2", "s3", "s4", "s5", "s6"]:
        reduce_state(state, Intent(IntentType.TOGGLE_STICKY, {"session_id": session_id}))

    assert [item.session_id for item in state.sessions.sticky_sessions] == ["s1", "s2", "s3", "s4", "s5"]


@pytest.mark.unit
def test_sync_sessions_prunes_preview_and_cached_output_data_but_not_selected_session() -> None:
    state = TuiState()
    reduce_state(state, Intent(IntentType.SET_PREVIEW, {"session_id": "s1"}))
    for session_id in ["s1", "s2", "s3"]:
        reduce_state(state, Intent(IntentType.TOGGLE_STICKY, {"session_id": session_id}))
    state.sessions.selected_session_id = "s2"
    state.sessions.last_output_summary = {"s2": "summary", "gone": "stale"}
    state.sessions.output_highlights = {"s2", "gone"}

    reduce_state(state, Intent(IntentType.SYNC_SESSIONS, {"session_ids": ["s1", "s3"]}))

    assert state.sessions.preview is None
    assert [item.session_id for item in state.sessions.sticky_sessions] == ["s1", "s3"]
    assert state.sessions.selected_session_id == "s2"
    assert state.sessions.last_output_summary == {}
    assert state.sessions.output_highlights == set()
