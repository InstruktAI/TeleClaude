import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
from teleclaude.core.models import Session
from teleclaude.core.agents import AgentName

@pytest.fixture
def mock_client():
    client = MagicMock()
    client.send_message = AsyncMock()
    return client

@pytest.fixture
def mock_tts_manager():
    return MagicMock()

@pytest.fixture
def mock_headless_snapshot_service():
    return MagicMock()

@pytest.fixture
def coordinator(mock_client, mock_tts_manager, mock_headless_snapshot_service):
    return AgentCoordinator(mock_client, mock_tts_manager, mock_headless_snapshot_service)

@pytest.mark.asyncio
async def test_handle_stop_experiment_enabled(coordinator, mock_client):
    session_id = "session-123"
    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"}
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.AGENT_STOP,
        session_id=session_id,
        data=payload
    )
    
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl"
    )
    
    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.config") as mock_config,
        patch("teleclaude.core.agent_coordinator.render_stop_turn") as mock_render,
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock) as mock_update_session,
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_summarize,
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract
    ):
        mock_get_session.return_value = session
        mock_config.is_experiment_enabled.side_effect = lambda name, agent: name == "ui_threaded_agent_stop_output"
        mock_render.return_value = "Summary message"
        mock_summarize.return_value = ("Title", "Summary")
        mock_extract.return_value = "last message"
        
        await coordinator.handle_stop(context)
        
        mock_client.send_message.assert_called_once_with(session, "Summary message", ephemeral=False)

@pytest.mark.asyncio
async def test_handle_stop_experiment_disabled(coordinator, mock_client):
    session_id = "session-123"
    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="macbook",
        raw={"agent_name": "gemini"}
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.AGENT_STOP,
        session_id=session_id,
        data=payload
    )
    
    session = Session(
        session_id=session_id,
        computer_name="macbook",
        tmux_session_name="tmux-123",
        title="Test Session",
        active_agent="gemini",
        native_log_file="/path/to/transcript.jsonl"
    )
    
    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock) as mock_get_session,
        patch("teleclaude.core.agent_coordinator.config") as mock_config,
        patch("teleclaude.core.agent_coordinator.render_stop_turn") as mock_render,
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message") as mock_extract
    ):
        mock_get_session.return_value = session
        mock_config.is_experiment_enabled.return_value = False
        mock_extract.return_value = "last message"
        
        await coordinator.handle_stop(context)
        
        mock_client.send_message.assert_not_called()
