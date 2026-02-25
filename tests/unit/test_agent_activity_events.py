"""Tests for AgentActivityEvent emission from coordinator handlers."""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
    AgentStopPayload,
    TeleClaudeEvents,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.send_message = AsyncMock()
    client.send_threaded_output = AsyncMock(return_value="msg-123")
    return client


@pytest.fixture
def mock_tts_manager():
    manager = MagicMock()
    manager.speak = AsyncMock()
    return manager


@pytest.fixture
def mock_headless_snapshot_service():
    return MagicMock()


@pytest.fixture
def coordinator(mock_client, mock_tts_manager, mock_headless_snapshot_service):
    return AgentCoordinator(mock_client, mock_tts_manager, mock_headless_snapshot_service)


@pytest.mark.asyncio
async def test_handle_tool_use_emits_activity_event(coordinator):
    """handle_tool_use should emit AGENT_ACTIVITY with event_type=tool_use."""
    session_id = "sess-tool-use"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({"tool_name": "Read"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    session = MagicMock()
    session.last_tool_use_at = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)

        # Verify activity event was emitted (may be followed by a session_status emit)
        assert mock_event_bus.emit.call_count >= 1
        activity_calls = [c for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY]
        assert len(activity_calls) == 1
        call_args = activity_calls[0]
        assert call_args[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        event: AgentActivityEvent = call_args[0][1]
        assert event.session_id == session_id
        assert event.event_type == "tool_use"
        assert event.tool_name == "Read"
        assert event.tool_preview == "Read"
        assert event.timestamp is not None


@pytest.mark.asyncio
async def test_handle_tool_use_records_first_per_turn(coordinator):
    """handle_tool_use should record DB timestamp only for first tool_use per turn."""
    session_id = "sess-first-use"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    # First call: last_tool_use_at is None → should write to DB
    session_first = MagicMock()
    session_first.last_tool_use_at = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus"),
    ):
        mock_db.get_session = AsyncMock(return_value=session_first)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)
        mock_db.update_session.assert_called_once()

    # Second call: last_tool_use_at is set → should skip DB write
    session_second = MagicMock()
    session_second.last_tool_use_at = "2024-01-01T00:00:00+00:00"

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus"),
    ):
        mock_db.get_session = AsyncMock(return_value=session_second)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)
        mock_db.update_session.assert_not_called()


@pytest.mark.asyncio
async def test_handle_tool_done_emits_activity_event(coordinator):
    """handle_tool_done should emit AGENT_ACTIVITY with event_type=tool_done."""
    session_id = "sess-tool-done"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({"agent_name": "claude"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_DONE, session_id=session_id, data=payload)

    session = MagicMock()
    session.active_agent = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        await coordinator.handle_tool_done(context)

        mock_event_bus.emit.assert_called_once()
        call_args = mock_event_bus.emit.call_args
        assert call_args[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        event: AgentActivityEvent = call_args[0][1]
        assert event.session_id == session_id
        assert event.event_type == "tool_done"
        assert event.tool_name is None
        assert event.tool_preview is None


@pytest.mark.asyncio
async def test_handle_agent_stop_emits_activity_event_with_summary(coordinator):
    """handle_agent_stop should emit AGENT_ACTIVITY with event_type=agent_stop and summary."""
    session_id = "sess-stop"
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="macbook",
        raw=MappingProxyType({"agent_name": "claude"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)

    session = MagicMock()
    session.active_agent = "claude"
    session.native_log_file = "/tmp/transcript.jsonl"
    session.last_tool_use_at = None
    session.last_checkpoint_at = None
    session.last_message_sent_at = None
    session.adapter_metadata = MagicMock()
    session.adapter_metadata.telegram = MagicMock()
    session.adapter_metadata.telegram.char_offset = 0
    session.output_message_id = None
    session.notification_sent = False
    session.initiator_session_id = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value="Test output")),
        patch.object(coordinator, "_summarize_output", new=AsyncMock(return_value="Summary of test")),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        mock_db.set_output_message_id = AsyncMock()
        mock_db.set_notification_flag = AsyncMock()
        await coordinator.handle_agent_stop(context)

        # Find the agent_stop activity event among all emit calls
        activity_calls = [c for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY]
        stop_calls = [c for c in activity_calls if c[0][1].event_type == "agent_stop"]
        assert len(stop_calls) == 1
        event: AgentActivityEvent = stop_calls[0][0][1]
        assert event.session_id == session_id
        assert event.summary == "Summary of test"


@pytest.mark.asyncio
async def test_activity_event_fields_are_populated(coordinator):
    """AgentActivityEvent should have all required fields populated."""
    session_id = "sess-fields"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({"toolName": "Bash"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    session = MagicMock()
    session.last_tool_use_at = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)

        event: AgentActivityEvent = next(
            c[0][1] for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        )
        # Verify all fields
        assert isinstance(event.session_id, str)
        assert event.session_id == session_id
        assert event.event_type in ("tool_use", "tool_done", "agent_stop", "user_prompt_submit")
        assert event.tool_name == "Bash"
        assert event.tool_preview == "Bash"
        assert event.timestamp is not None
        # timestamp should be ISO format
        assert "T" in event.timestamp


@pytest.mark.asyncio
async def test_handle_tool_use_builds_preview_from_command(coordinator):
    """tool_use preview should include tool name + command when command exists."""
    session_id = "sess-preview-cmd"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": "git status --short"},
            }
        ),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    session = MagicMock()
    session.last_tool_use_at = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)

        event: AgentActivityEvent = next(
            c[0][1] for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        )
        assert event.tool_name == "run_shell_command"
        assert event.tool_preview == "run_shell_command git status --short"


# ---------------------------------------------------------------------------
# Canonical contract field population (ucap-canonical-contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_tool_use_emits_canonical_contract_fields(coordinator):
    """handle_tool_use should emit an event with canonical_type, message_intent, delivery_scope."""
    session_id = "sess-canonical-tool"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({"tool_name": "Read"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    session = MagicMock()
    session.last_tool_use_at = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        await coordinator.handle_tool_use(context)

        event: AgentActivityEvent = next(
            c[0][1] for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        )
        # hook type preserved for compat
        assert event.event_type == "tool_use"
        # canonical contract fields present
        assert event.canonical_type == "agent_output_update"
        assert event.message_intent == "ctrl_activity"
        assert event.delivery_scope == "CTRL"


@pytest.mark.asyncio
async def test_handle_agent_stop_emits_canonical_contract_fields(coordinator):
    """handle_agent_stop should emit agent_output_stop as canonical_type."""
    session_id = "sess-canonical-stop"
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="macbook",
        raw=MappingProxyType({"agent_name": "claude"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)

    session = MagicMock()
    session.active_agent = "claude"
    session.native_log_file = "/tmp/transcript.jsonl"
    session.last_tool_use_at = None
    session.last_checkpoint_at = None
    session.last_message_sent_at = None
    session.adapter_metadata = MagicMock()
    session.adapter_metadata.telegram = MagicMock()
    session.adapter_metadata.telegram.char_offset = 0
    session.output_message_id = None
    session.notification_sent = False
    session.initiator_session_id = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        mock_db.set_notification_flag = AsyncMock()
        await coordinator.handle_agent_stop(context)

        activity_calls = [c for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY]
        stop_calls = [c for c in activity_calls if c[0][1].event_type == "agent_stop"]
        assert len(stop_calls) == 1
        event: AgentActivityEvent = stop_calls[0][0][1]
        # hook type preserved
        assert event.event_type == "agent_stop"
        # canonical fields
        assert event.canonical_type == "agent_output_stop"
        assert event.message_intent == "ctrl_activity"
        assert event.delivery_scope == "CTRL"


@pytest.mark.asyncio
async def test_handle_tool_done_emits_canonical_contract_fields(coordinator):
    """handle_tool_done should emit agent_output_update as canonical_type."""
    session_id = "sess-canonical-done"
    payload = AgentOutputPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        raw=MappingProxyType({"agent_name": "claude"}),
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_DONE, session_id=session_id, data=payload)

    session = MagicMock()
    session.active_agent = None

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_event_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        await coordinator.handle_tool_done(context)

        event: AgentActivityEvent = next(
            c[0][1] for c in mock_event_bus.emit.call_args_list if c[0][0] == TeleClaudeEvents.AGENT_ACTIVITY
        )
        assert event.event_type == "tool_done"
        assert event.canonical_type == "agent_output_update"
        assert event.message_intent == "ctrl_activity"
        assert event.delivery_scope == "CTRL"
