"""Tests for AgentActivityEvent broadcast via API server and TUI state machine handling."""

from unittest.mock import MagicMock

import pytest

from teleclaude.cli.tui.state import Intent, IntentType, TuiState, reduce_state
from teleclaude.core.events import AgentActivityEvent

# --- API Server Broadcast Tests ---


@pytest.mark.asyncio
async def test_api_server_broadcasts_activity_event():
    """_handle_agent_activity_event should broadcast DTO to WebSocket clients."""
    from teleclaude.api_server import APIServer

    handler = APIServer.__new__(APIServer)
    handler._broadcast_payload = MagicMock()

    event = AgentActivityEvent(
        session_id="sess-1",
        event_type="tool_use",
        tool_name="Read",
        tool_preview="Read teleclaude/core/events.py",
        timestamp="2024-01-01T00:00:00+00:00",
    )

    await handler._handle_agent_activity_event("agent_activity", event)

    handler._broadcast_payload.assert_called_once()
    call_args = handler._broadcast_payload.call_args
    assert call_args[0][0] == "agent_activity"
    payload = call_args[0][1]
    assert payload["session_id"] == "sess-1"
    assert payload["type"] == "tool_use"
    assert payload["tool_name"] == "Read"
    assert payload["tool_preview"] == "Read teleclaude/core/events.py"
    assert payload["event"] == "agent_activity"


@pytest.mark.asyncio
async def test_api_server_broadcasts_tool_done():
    """tool_done events should broadcast with correct type."""
    from teleclaude.api_server import APIServer

    handler = APIServer.__new__(APIServer)
    handler._broadcast_payload = MagicMock()

    event = AgentActivityEvent(
        session_id="sess-2",
        event_type="tool_done",
    )

    await handler._handle_agent_activity_event("agent_activity", event)

    payload = handler._broadcast_payload.call_args[0][1]
    assert payload["type"] == "tool_done"
    assert "tool_name" not in payload  # excluded by exclude_none
    assert "tool_preview" not in payload  # excluded by exclude_none


@pytest.mark.asyncio
async def test_api_server_broadcasts_agent_stop_with_summary():
    """agent_stop events should include summary in broadcast."""
    from teleclaude.api_server import APIServer

    handler = APIServer.__new__(APIServer)
    handler._broadcast_payload = MagicMock()

    event = AgentActivityEvent(
        session_id="sess-3",
        event_type="agent_stop",
        summary="Completed file edit",
    )

    await handler._handle_agent_activity_event("agent_activity", event)

    payload = handler._broadcast_payload.call_args[0][1]
    assert payload["type"] == "agent_stop"
    assert payload["summary"] == "Completed file edit"


# --- TUI State Machine Tests ---


def test_tui_tool_use_clears_input_sets_temp_highlight():
    """tool_use event should clear input highlight and set temp output highlight."""
    state = TuiState()
    session_id = "sess-tui-1"
    state.sessions.input_highlights.add(session_id)

    reduce_state(
        state,
        Intent(IntentType.AGENT_ACTIVITY, {"session_id": session_id, "event_type": "tool_use", "tool_name": "Edit"}),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert state.sessions.active_tool[session_id] == "Edit"


def test_tui_tool_use_prefers_tool_preview():
    """tool_use should store tool_preview when it is available."""
    state = TuiState()
    session_id = "sess-tui-preview"

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {
                "session_id": session_id,
                "event_type": "tool_use",
                "tool_name": "Bash",
                "tool_preview": "Bash git status --short",
            },
        ),
    )

    assert state.sessions.active_tool[session_id] == "Bash git status --short"


def test_tui_tool_done_clears_tool_keeps_temp_highlight():
    """tool_done event should clear active tool and keep temp highlight."""
    state = TuiState()
    session_id = "sess-tui-2"
    state.sessions.input_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Edit"

    reduce_state(
        state,
        Intent(IntentType.AGENT_ACTIVITY, {"session_id": session_id, "event_type": "tool_done"}),
    )

    assert session_id not in state.sessions.input_highlights
    assert session_id in state.sessions.temp_output_highlights
    assert session_id in state.sessions.activity_timer_reset
    assert session_id not in state.sessions.active_tool


def test_tui_agent_stop_sets_permanent_highlight():
    """agent_stop event should set permanent output highlight and clear temp."""
    state = TuiState()
    session_id = "sess-tui-3"
    state.sessions.temp_output_highlights.add(session_id)
    state.sessions.active_tool[session_id] = "Bash"

    reduce_state(
        state,
        Intent(
            IntentType.AGENT_ACTIVITY,
            {"session_id": session_id, "event_type": "agent_stop", "summary": "Done editing"},
        ),
    )

    assert session_id not in state.sessions.temp_output_highlights
    assert session_id not in state.sessions.active_tool
    assert session_id in state.sessions.output_highlights
    assert state.sessions.last_output_summary[session_id] == "Done editing"


def test_tui_user_prompt_submit_sets_input_highlight():
    """user_prompt_submit event should set input highlight and clear output."""
    state = TuiState()
    session_id = "sess-tui-4"
    state.sessions.output_highlights.add(session_id)
    state.sessions.temp_output_highlights.add(session_id)

    reduce_state(
        state,
        Intent(IntentType.AGENT_ACTIVITY, {"session_id": session_id, "event_type": "user_prompt_submit"}),
    )

    assert session_id in state.sessions.input_highlights
    assert session_id not in state.sessions.output_highlights
    assert session_id not in state.sessions.temp_output_highlights


# --- Canonical contract field broadcast regression ---


@pytest.mark.asyncio
async def test_api_server_broadcasts_canonical_fields_when_present() -> None:
    """Canonical fields should appear in broadcast payload when event carries them."""
    from teleclaude.api_server import APIServer

    handler = APIServer.__new__(APIServer)
    handler._broadcast_payload = MagicMock()

    event = AgentActivityEvent(
        session_id="sess-canonical",
        event_type="tool_use",
        tool_name="Read",
        timestamp="2024-01-01T00:00:00+00:00",
        canonical_type="agent_output_update",
        message_intent="ctrl_activity",
        delivery_scope="CTRL",
    )

    await handler._handle_agent_activity_event("agent_activity", event)

    payload = handler._broadcast_payload.call_args[0][1]
    # hook type still present for compatibility
    assert payload["type"] == "tool_use"
    # canonical contract fields in broadcast
    assert payload["canonical_type"] == "agent_output_update"
    assert payload["message_intent"] == "ctrl_activity"
    assert payload["delivery_scope"] == "CTRL"


@pytest.mark.asyncio
async def test_api_server_excludes_canonical_fields_when_absent() -> None:
    """When canonical fields are None (legacy event), exclude_none should omit them."""
    from teleclaude.api_server import APIServer

    handler = APIServer.__new__(APIServer)
    handler._broadcast_payload = MagicMock()

    # Minimal event with no canonical fields (backward compat path)
    event = AgentActivityEvent(
        session_id="sess-legacy",
        event_type="tool_done",
    )

    await handler._handle_agent_activity_event("agent_activity", event)

    payload = handler._broadcast_payload.call_args[0][1]
    assert payload["type"] == "tool_done"
    # canonical fields absent (None excluded)
    assert "canonical_type" not in payload
    assert "message_intent" not in payload
    assert "delivery_scope" not in payload
