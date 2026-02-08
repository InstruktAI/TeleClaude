from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentOutputPayload, AgentStopPayload
from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.send_message = AsyncMock()
    client.edit_message = AsyncMock()
    client.send_threaded_footer = AsyncMock()
    client.send_threaded_output = AsyncMock()
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
    """Verify first output sends new message, stores ID, and does NOT update cursor."""
    session_id = "session-123"
    payload = AgentOutputPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_OUTPUT, session_id=session_id, data=payload)

    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(),  # No telegram metadata initially
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.render_clean_agent_output") as mock_render_clean,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=1),
        patch("teleclaude.core.agent_coordinator.telegramify_markdown", return_value="Message 1"),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        # mock_render.return_value = ("Message 1", "timestamp") # Not called if count=1
        mock_render_clean.return_value = ("Message 1", "timestamp")

        # Mock send_message returning an ID
        mock_client.send_message.return_value = "msg_123"

        # Mock build_threaded_footer_text
        with patch.object(coordinator, "_build_threaded_footer_text", return_value="footer"):
            await coordinator.handle_agent_output(context)

        # 1. Should call send_threaded_output
        mock_client.send_threaded_output.assert_called_once_with(
            session, "Message 1", footer_text="footer", multi_message=False
        )

        # 2. Should update session to persist metadata (cursor check)
        # Verify cursor update was NOT called (no LAST_AGENT_OUTPUT_AT in kwargs)
        for call in mock_update_session.call_args_list:
            args, kwargs = call
            assert "last_agent_output_at" not in kwargs, "Cursor should not be updated on initial threaded send"


@pytest.mark.asyncio
async def test_threaded_output_subsequent_update_edits_message(coordinator, mock_client):
    """Verify subsequent output edits existing message and skips cursor update."""
    session_id = "session-123"
    payload = AgentOutputPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_OUTPUT, session_id=session_id, data=payload)

    # Session with existing message ID (top-level column, not nested in adapter_metadata)
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata()),
        output_message_id="msg_123",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=2),
        patch("teleclaude.core.agent_coordinator.telegramify_markdown", return_value="Message 1 + 2"),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        mock_render.return_value = ("Message 1 + 2", "timestamp_2")

        # Mock build_threaded_footer_text
        with patch.object(coordinator, "_build_threaded_footer_text", return_value="footer"):
            await coordinator.handle_agent_output(context)

        # 1. Should call send_threaded_output
        mock_client.send_threaded_output.assert_called_once_with(
            session, "Message 1 + 2", footer_text="footer", multi_message=True
        )

        # 2. Should call update_session (heartbeat) but NOT update cursor
        mock_update_session.assert_called_once()
        args, kwargs = mock_update_session.call_args
        assert kwargs["reason"] == "agent_output"
        assert "last_agent_output_at" not in kwargs, "Cursor should NOT be updated during accumulation"


@pytest.mark.asyncio
async def test_handle_agent_stop_clears_tracking_id(coordinator, mock_client):
    """Verify agent_stop clears the output message ID."""
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
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata()),
        output_message_id="msg_123",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks", return_value=2),
        patch("teleclaude.core.agent_coordinator.telegramify_markdown", return_value="Final Message"),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_sum,
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract,
        patch(
            "teleclaude.core.agent_coordinator.db.set_output_message_id", new_callable=AsyncMock
        ) as mock_set_output_msg,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [{"role": "assistant", "content": []}]
        mock_render.return_value = ("Final Message", "final_ts")
        mock_sum.return_value = ("Title", "Summary")
        mock_extract.return_value = "last message"

        # Mock build_threaded_footer_text
        with patch.object(coordinator, "_build_threaded_footer_text", return_value="footer"):
            await coordinator.handle_agent_stop(context)

        # 1. Should call send_threaded_output (final update)
        mock_client.send_threaded_output.assert_called_once_with(
            session, "Final Message", footer_text="footer", multi_message=True
        )

        # 2. Should clear output_message_id via dedicated column write
        mock_set_output_msg.assert_called_once_with(session_id, None)

        # 3. Verify DB updates: adapter_metadata (char_offset reset) and cursor clear
        calls = mock_update_session.call_args_list

        meta_update_found = False
        cursor_clear_found = False

        for call in calls:
            _, kwargs = call
            if "adapter_metadata" in kwargs:
                meta_update_found = True
            if "last_agent_output_at" in kwargs and kwargs["last_agent_output_at"] is None:
                cursor_clear_found = True

        assert meta_update_found, "Should persist adapter_metadata (char_offset reset)"
        assert cursor_clear_found, "Should clear turn cursor"
