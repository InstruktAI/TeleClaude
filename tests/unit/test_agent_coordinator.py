from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.agents import AgentName
from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
from teleclaude.core.models import Session


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.send_message = AsyncMock()
    client.send_threaded_output = AsyncMock(return_value="msg-123")
    client.send_threaded_footer = AsyncMock()
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
async def test_handle_agent_stop_experiment_enabled(coordinator, mock_client):
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
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=True),
        patch("teleclaude.core.agent_coordinator.is_threaded_output_include_tools_enabled", return_value=False),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks") as mock_count_blocks,
        patch("teleclaude.core.agent_coordinator.telegramify_markdown") as mock_telegramify,
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_summarize,
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = [
            {"role": "assistant", "content": [{"type": "text", "text": "A"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "B"}]},
        ]
        mock_count_blocks.return_value = 2
        mock_render.return_value = ("Summary message", None)
        mock_telegramify.return_value = "Summary message"
        mock_summarize.return_value = ("Title", "Summary")
        mock_extract.return_value = "last message"

        await coordinator.handle_agent_stop(context)

        mock_client.send_threaded_output.assert_called_once()
        call_args = mock_client.send_threaded_output.call_args
        assert call_args[0][0] is session
        assert call_args[0][1] == "Summary message"
        assert call_args[1]["multi_message"] is True
        assert "footer_text" in call_args[1]
        mock_client.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_stop_experiment_disabled(coordinator, mock_client):
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
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=False),
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks") as mock_count_blocks,
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract,
    ):
        mock_get_session.return_value = session
        mock_get_messages.return_value = []
        mock_count_blocks.return_value = 0
        mock_extract.return_value = "last message"

        await coordinator.handle_agent_stop(context)

        mock_client.send_message.assert_not_called()
        mock_client.send_threaded_footer.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_stop_experiment_not_applied_to_non_gemini(coordinator, mock_client):
    session_id = "session-123"
    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)

    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="codex",
        native_log_file="/path/to/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=False),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract,
    ):
        mock_get_session.return_value = session
        mock_extract.return_value = "last message"

        await coordinator.handle_agent_stop(context)

        mock_client.send_message.assert_not_called()
        mock_client.send_threaded_footer.assert_not_called()
