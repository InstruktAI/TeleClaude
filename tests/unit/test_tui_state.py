"""Unit tests for TUI reducer highlight transitions."""

from teleclaude.cli.tui.state import Intent, IntentType, TuiState, reduce_state


def test_agent_output_clears_input_and_sets_temp_output_highlight() -> None:
    """Agent output should move highlight from input to temporary output."""
    state = TuiState()
    session_id = "sess-1"
    state.sessions.input_highlights.add(session_id)
    state.sessions.output_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.SESSION_ACTIVITY,
            {"session_id": session_id, "reason": "agent_output"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id not in state.sessions.output_highlights
    assert session_id in state.sessions.temp_output_highlights


def test_agent_stopped_sets_permanent_output_highlight() -> None:
    """Agent stop should clear temporary/input highlights and persist output highlight."""
    state = TuiState()
    session_id = "sess-2"
    state.sessions.input_highlights.add(session_id)
    state.sessions.temp_output_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.SESSION_ACTIVITY,
            {"session_id": session_id, "reason": "agent_stopped"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id not in state.sessions.temp_output_highlights
    assert session_id in state.sessions.output_highlights


def test_agent_activity_after_model_signals_timer_reset() -> None:
    """after_model event should clear input, set temp highlight, and signal timer reset."""
    state = TuiState()
    session_id = "sess-activity-1"
    state.sessions.input_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "after_model", "tool_name": "Edit"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert state.sessions.active_tool[session_id] == "Edit"


def test_agent_activity_agent_output_signals_timer_reset() -> None:
    """agent_output event should keep temp highlight, clear tool, and signal timer reset."""
    state = TuiState()
    session_id = "sess-activity-2"
    state.sessions.input_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Edit"

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "agent_output"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert session_id not in state.sessions.active_tool


def test_agent_activity_agent_stop_clears_temp_and_sets_output() -> None:
    """agent_stop should clear temp/input highlights and set permanent output."""
    state = TuiState()
    session_id = "sess-activity-3"
    state.sessions.temp_output_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Read"

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "agent_stop"},
        ),
    )

    assert session_id not in state.sessions.temp_output_highlights
    assert session_id not in state.sessions.active_tool
    assert session_id in state.sessions.output_highlights


def test_user_input_clears_any_output_highlight_and_sets_input() -> None:
    """User input should always return to input highlight state."""
    state = TuiState()
    session_id = "sess-3"
    state.sessions.output_highlights.add(session_id)
    state.sessions.temp_output_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.SESSION_ACTIVITY,
            {"session_id": session_id, "reason": "user_input"},
        ),
    )

    assert session_id in state.sessions.input_highlights
    assert session_id not in state.sessions.output_highlights
    assert session_id not in state.sessions.temp_output_highlights
