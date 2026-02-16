"""Unit tests for TUI reducer highlight transitions."""

from teleclaude.cli.tui.state import Intent, IntentType, PreviewState, TuiState, reduce_state


def test_toggle_sticky_clears_active_preview() -> None:
    """Adding a sticky session should clear active preview state."""
    state = TuiState()
    state.sessions.preview = PreviewState("sess-sticky")

    reduce_state(
        state,
        Intent(
            IntentType.TOGGLE_STICKY,
            {"session_id": "sess-sticky", "active_agent": "claude"},
        ),
    )

    assert state.sessions.preview is None
    assert [s.session_id for s in state.sessions.sticky_sessions] == ["sess-sticky"]


def test_clear_preview_intent_removes_active_preview() -> None:
    """CLEAR_PREVIEW intent should reset preview state."""
    state = TuiState()
    state.sessions.preview = PreviewState("sess-active")

    reduce_state(state, Intent(IntentType.CLEAR_PREVIEW, {}))

    assert state.sessions.preview is None


def test_tool_done_clears_input_and_sets_temp_output_highlight() -> None:
    """Tool done should move highlight from input to temporary output."""
    state = TuiState()
    session_id = "sess-1"
    state.sessions.input_highlights.add(session_id)
    state.sessions.output_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.SESSION_ACTIVITY,
            {"session_id": session_id, "reason": "tool_done"},
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


def test_agent_activity_tool_use_signals_timer_reset() -> None:
    """tool_use event should clear input, set temp highlight, and signal timer reset."""
    state = TuiState()
    session_id = "sess-activity-1"
    state.sessions.input_highlights.add(session_id)

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "tool_use", "tool_name": "Edit"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert state.sessions.active_tool[session_id] == "Edit"


def test_agent_activity_tool_done_signals_timer_reset() -> None:
    """tool_done event should keep temp highlight, clear tool, and signal timer reset."""
    state = TuiState()
    session_id = "sess-activity-2"
    state.sessions.input_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Edit"

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "tool_done"},
        ),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert session_id not in state.sessions.active_tool


def test_set_animation_mode() -> None:
    """SET_ANIMATION_MODE intent should update animation mode if valid."""
    state = TuiState()
    assert state.animation_mode == "periodic"

    # Valid modes
    reduce_state(state, Intent(IntentType.SET_ANIMATION_MODE, {"mode": "party"}))
    assert state.animation_mode == "party"

    reduce_state(state, Intent(IntentType.SET_ANIMATION_MODE, {"mode": "off"}))
    assert state.animation_mode == "off"

    # Invalid mode should be ignored
    reduce_state(state, Intent(IntentType.SET_ANIMATION_MODE, {"mode": "invalid"}))
    assert state.animation_mode == "off"


def test_set_config_subtab() -> None:
    """SET_CONFIG_SUBTAB intent should update config subtab if valid."""
    state = TuiState()
    assert state.config.active_subtab == "adapters"

    # Valid subtabs
    reduce_state(state, Intent(IntentType.SET_CONFIG_SUBTAB, {"subtab": "people"}))
    assert state.config.active_subtab == "people"

    reduce_state(state, Intent(IntentType.SET_CONFIG_SUBTAB, {"subtab": "validate"}))
    assert state.config.active_subtab == "validate"

    # Invalid subtab should be ignored
    reduce_state(state, Intent(IntentType.SET_CONFIG_SUBTAB, {"subtab": "invalid"}))
    assert state.config.active_subtab == "validate"


def test_set_config_guided_mode() -> None:
    """SET_CONFIG_GUIDED_MODE intent should update guided mode enabled state."""
    state = TuiState()
    assert state.config.guided_mode is False

    reduce_state(state, Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": True}))
    assert state.config.guided_mode is True

    reduce_state(state, Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": False}))
    assert state.config.guided_mode is False

    # Invalid type should be ignored
    reduce_state(state, Intent(IntentType.SET_CONFIG_GUIDED_MODE, {"enabled": "yes"}))  # type: ignore
    assert state.config.guided_mode is False


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


def test_clear_temp_highlight_promotes_output_and_clears_tool_state() -> None:
    state = TuiState()
    session_id = "sess-temp-clear"
    state.sessions.temp_output_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Read"

    reduce_state(state, Intent(IntentType.CLEAR_TEMP_HIGHLIGHT, {"session_id": session_id}))

    assert session_id not in state.sessions.temp_output_highlights
    assert session_id not in state.sessions.active_tool
    assert session_id in state.sessions.output_highlights
