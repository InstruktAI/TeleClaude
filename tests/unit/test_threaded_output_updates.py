from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentOutputPayload, AgentStopPayload
from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata


@pytest.fixture(autouse=True)
def _mock_session_listeners(monkeypatch):
    """Mock session_listeners functions that now require DB."""
    monkeypatch.setattr(
        "teleclaude.core.agent_coordinator.notify_stop",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "teleclaude.core.agent_coordinator.notify_input_request",
        AsyncMock(return_value=0),
    )


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.send_message = AsyncMock()
    client.edit_message = AsyncMock()
    client.send_threaded_output = AsyncMock()
    client.break_threaded_turn = AsyncMock()
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
async def test_threaded_output_initial_send_stores_id_and_skips_cursor_update(coordinator, mock_client):
    """Verify first incremental send stores ID and does NOT update cursor."""
    session_id = "session-123"
    payload = AgentOutputPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.render_clean_agent_output") as mock_render_clean,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=1),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        mock_render_clean.return_value = ("Message 1", "timestamp")

        mock_client.send_message.return_value = "msg_123"

        await coordinator._maybe_send_incremental_output(session_id, payload)

        # 1. Should call send_threaded_output
        mock_client.send_threaded_output.assert_called_once_with(session, "Message 1", multi_message=False)

        # 2. Should update session to persist metadata (cursor check)
        # Verify cursor update was NOT called (no LAST_TOOL_DONE_AT in kwargs)
        for call in mock_update_session.call_args_list:
            args, kwargs = call
            assert "last_tool_done_at" not in kwargs, "Cursor should not be updated on initial threaded send"


@pytest.mark.asyncio
async def test_threaded_output_subsequent_update_edits_message(coordinator, mock_client):
    """Verify subsequent incremental output edits existing message and skips cursor update."""
    session_id = "session-123"
    payload = AgentOutputPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    # Session with existing message ID in adapter metadata
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(output_message_id="msg_123")),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=2),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        mock_render.return_value = ("Message 1 + 2", "timestamp_2")

        await coordinator._maybe_send_incremental_output(session_id, payload)

        # 1. Should call send_threaded_output to edit the existing message
        mock_client.send_threaded_output.assert_called_once_with(session, "Message 1 + 2", multi_message=True)

        # 2. Verify cursor was NOT updated (if update_session was called, it shouldn't include cursor)
        for call in mock_update_session.call_args_list:
            args, kwargs = call
            assert "last_tool_done_at" not in kwargs, "Cursor should NOT be updated during message edits"


@pytest.mark.asyncio
async def test_handle_agent_stop_clears_tracking_id(coordinator, mock_client):
    """Verify agent_stop delegates cleanup to break_threaded_turn."""
    session_id = "session-123"
    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)

    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(output_message_id="msg_123")),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=2),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_sum,
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        mock_render.return_value = ("Final Message", "final_ts")
        mock_sum.return_value = ("Title", "Summary")
        mock_extract.return_value = "last message"

        await coordinator.handle_agent_stop(context)

        # 1. Should call send_threaded_output (final update)
        mock_client.send_threaded_output.assert_called_once_with(session, "Final Message", multi_message=True)

        # 2. Should delegate cleanup to break_threaded_turn (clears per-adapter state)
        mock_client.break_threaded_turn.assert_called_once_with(session)

        # 3. Verify turn cursor is cleared
        cursor_clear_found = False
        for call in mock_update_session.call_args_list:
            _, kwargs = call
            if "last_tool_done_at" in kwargs and kwargs["last_tool_done_at"] is None:
                cursor_clear_found = True
        assert cursor_clear_found, "Should clear turn cursor"


@pytest.mark.asyncio
async def test_threaded_output_prefers_payload_agent_over_session_agent(coordinator, mock_client):
    """Incremental output must honor hook payload agent identity over stale session metadata."""
    session_id = "session-123"
    payload = AgentOutputPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "claude"},
    )
    # Session metadata is stale (gemini), payload identity is claude.
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled") as mock_enabled,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
    ):
        mock_get_session.return_value = session
        mock_enabled.side_effect = lambda agent: agent == "gemini"

        await coordinator._maybe_send_incremental_output(session_id, payload)

        # Claimed agent from payload should be used, disabling threaded output path.
        mock_enabled.assert_called_once_with("claude")
        mock_get_messages.assert_not_called()
        mock_client.send_threaded_output.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_incremental_output_fires_for_threaded_session(coordinator):
    session_id = "session-123"
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch.object(
            coordinator, "_maybe_send_incremental_output", new=AsyncMock(return_value=True)
        ) as mock_maybe_send,
    ):
        mock_get_session.return_value = session
        result = await coordinator.trigger_incremental_output(session_id)

    assert result is True
    mock_get_session.assert_awaited_once_with(session_id)
    mock_maybe_send.assert_awaited_once()
    payload = mock_maybe_send.await_args.args[1]
    assert payload.session_id == session_id
    assert payload.transcript_path == "/path/to/transcript.jsonl"


@pytest.mark.asyncio
async def test_trigger_incremental_output_skips_non_threaded_session(coordinator):
    session_id = "session-124"
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-124",
        title="Test Session",
        active_agent="claude",
        native_log_file="/path/to/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=False),
        patch.object(
            coordinator, "_maybe_send_incremental_output", new=AsyncMock(return_value=False)
        ) as mock_maybe_send,
    ):
        mock_get_session.return_value = session
        result = await coordinator.trigger_incremental_output(session_id)

    assert result is False
    mock_get_session.assert_awaited_once_with(session_id)
    mock_maybe_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_use_does_not_trigger_direct_incremental_output(coordinator):
    """tool_use hooks stay control-plane and do not fan out output directly."""
    session_id = "session-tool-use"
    payload = AgentOutputPayload(
        session_id="native-tool-use",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"tool_name": "Read"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_USE, session_id=session_id, data=payload)

    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()) as mock_incremental,
    ):
        mock_get_session.return_value = session
        await coordinator.handle_tool_use(context)

    mock_incremental.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_done_does_not_trigger_direct_incremental_output(coordinator):
    """tool_done hooks stay control-plane and do not fan out output directly."""
    session_id = "session-tool-done"
    payload = AgentOutputPayload(
        session_id="native-tool-done",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.TOOL_DONE, session_id=session_id, data=payload)

    with patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()) as mock_incremental:
        await coordinator.handle_tool_done(context)

    mock_incremental.assert_not_awaited()


# ---------------------------------------------------------------------------
# TUI lane: canonical contract path (R1, R4)
# ---------------------------------------------------------------------------


def test_agent_activity_message_carries_canonical_type() -> None:
    """AgentActivity message correctly stores canonical_type from contract."""
    from teleclaude.cli.tui.messages import AgentActivity

    msg = AgentActivity(
        session_id="sess-1",
        activity_type="agent_stop",
        canonical_type="agent_output_stop",
        summary="Done",
    )
    assert msg.canonical_type == "agent_output_stop"
    assert msg.activity_type == "agent_stop"


def test_agent_activity_canonical_type_defaults_to_none() -> None:
    """canonical_type defaults to None for backward compatibility."""
    from teleclaude.cli.tui.messages import AgentActivity

    msg = AgentActivity(
        session_id="sess-1",
        activity_type="tool_use",
    )
    assert msg.canonical_type is None


def test_agent_activity_output_update_carries_tool_metadata() -> None:
    """AgentActivity for agent_output_update carries tool name and preview."""
    from teleclaude.cli.tui.messages import AgentActivity

    msg = AgentActivity(
        session_id="sess-2",
        activity_type="tool_use",
        canonical_type="agent_output_update",
        tool_name="Read",
        tool_preview="Read: /tmp/file.py",
    )
    assert msg.canonical_type == "agent_output_update"
    assert msg.tool_name == "Read"
    assert msg.tool_preview == "Read: /tmp/file.py"


def test_agent_activity_user_prompt_submit_canonical_type() -> None:
    """AgentActivity for user_prompt_submit carries correct canonical_type."""
    from teleclaude.cli.tui.messages import AgentActivity

    msg = AgentActivity(
        session_id="sess-3",
        activity_type="user_prompt_submit",
        canonical_type="user_prompt_submit",
    )
    assert msg.canonical_type == "user_prompt_submit"


def test_serialize_agent_stop_produces_output_stop_for_tui() -> None:
    """agent_stop hook event serializes to agent_output_stop canonical type."""
    from teleclaude.core.activity_contract import serialize_activity_event

    event = serialize_activity_event(
        session_id="sess-abc",
        hook_event_type="agent_stop",
        timestamp="2025-01-01T00:00:00Z",
        summary="Output complete",
    )
    assert event is not None
    assert event.canonical_type == "agent_output_stop"
    assert event.hook_event_type == "agent_stop"


def test_serialize_tool_use_produces_output_update_for_tui() -> None:
    """tool_use hook event serializes to agent_output_update canonical type."""
    from teleclaude.core.activity_contract import serialize_activity_event

    event = serialize_activity_event(
        session_id="sess-abc",
        hook_event_type="tool_use",
        timestamp="2025-01-01T00:00:00Z",
        tool_name="Read",
        tool_preview="Read: /tmp/file.py",
    )
    assert event is not None
    assert event.canonical_type == "agent_output_update"
    assert event.tool_name == "Read"


def test_serialize_tool_done_produces_output_update_for_tui() -> None:
    """tool_done hook event serializes to agent_output_update canonical type (no tool_name)."""
    from teleclaude.core.activity_contract import serialize_activity_event

    event = serialize_activity_event(
        session_id="sess-abc",
        hook_event_type="tool_done",
        timestamp="2025-01-01T00:00:00Z",
    )
    assert event is not None
    assert event.canonical_type == "agent_output_update"
    assert event.tool_name is None


def test_canonical_event_carries_observability_fields_for_tui_lane() -> None:
    """Canonical event carries all required observability fields (R4: lane, event type, session)."""
    from teleclaude.core.activity_contract import serialize_activity_event

    event = serialize_activity_event(
        session_id="sess-obs",
        hook_event_type="tool_use",
        timestamp="2025-01-01T00:00:00Z",
        tool_name="Bash",
    )
    assert event is not None
    assert event.session_id == "sess-obs"
    assert event.canonical_type == "agent_output_update"
    assert event.hook_event_type == "tool_use"
    assert event.timestamp == "2025-01-01T00:00:00Z"
    assert event.message_intent == "ctrl_activity"
    assert event.delivery_scope == "CTRL"
