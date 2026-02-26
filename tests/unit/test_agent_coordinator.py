from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE
from teleclaude.core.agent_coordinator import (
    AgentCoordinator,
    _is_checkpoint_prompt,
    _is_codex_synthetic_prompt_event,
    _resolve_hook_actor_name,
)
from teleclaude.core.agents import AgentName
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentOutputPayload,
    AgentStopPayload,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import ProcessMessageCommand


def test_resolve_hook_actor_name_prefers_session_metadata_name():
    session = Session(
        session_id="sess-meta-name",
        computer_name="local",
        tmux_session_name="tmux-meta-name",
        title="Test Session",
        session_metadata={"actor_name": "Alice"},
    )

    assert _resolve_hook_actor_name(session) == "Alice"


def test_resolve_hook_actor_name_uses_identity_resolver_for_telegram(monkeypatch):
    class _Resolver:
        def resolve(self, origin: str, channel_metadata: Mapping[str, str]):  # type: ignore[override]
            if origin != InputOrigin.TELEGRAM.value:
                return None
            if str(channel_metadata.get("user_id")) != "12345":
                return None
            return type("Identity", (), {"person_name": "Morriz"})()

    monkeypatch.setattr("teleclaude.core.agent_coordinator.get_identity_resolver", lambda: _Resolver())

    session = Session(
        session_id="sess-meta-id",
        computer_name="local",
        tmux_session_name="tmux-meta-id",
        title="Test Session",
        last_input_origin=InputOrigin.TELEGRAM.value,
    )
    session.get_metadata().get_ui().get_telegram().user_id = 12345

    assert _resolve_hook_actor_name(session) == "Morriz"


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
    client.send_threaded_output = AsyncMock(return_value="msg-123")
    client.break_threaded_turn = AsyncMock()
    client.broadcast_user_input = AsyncMock()
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
        patch("teleclaude.core.agent_coordinator.render_agent_output") as mock_render,
        patch("teleclaude.core.agent_coordinator.get_assistant_messages_since") as mock_get_messages,
        patch("teleclaude.core.agent_coordinator.count_renderable_assistant_blocks") as mock_count_blocks,
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
        mock_summarize.return_value = ("Title", "Summary")
        mock_extract.return_value = "last message"

        await coordinator.handle_agent_stop(context)

        mock_client.send_threaded_output.assert_called_once()
        call_args = mock_client.send_threaded_output.call_args
        assert call_args[0][0] is session
        assert call_args[0][1] == "Summary message"
        assert call_args[1]["multi_message"] is True
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


@pytest.mark.asyncio
async def test_user_prompt_submit_skips_truncated_codex_checkpoint(coordinator):
    session = Session(
        session_id="sess-1",
        computer_name="macbook",
        tmux_session_name="tmux-1",
        title="Untitled",
        active_agent="codex",
    )
    payload = UserPromptSubmitPayload(
        prompt=CHECKPOINT_MESSAGE[:70],
        session_id="sess-1",
        raw={"synthetic": True, "source": "codex_output_polling"},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-1",
        data=payload,
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()

        await coordinator.handle_user_prompt_submit(context)

        mock_db.set_notification_flag.assert_not_called()
        mock_db.update_session.assert_not_called()


def test_checkpoint_prompt_requires_canonical_prefix():
    assert _is_checkpoint_prompt("Context-aware checkpoint\n\nNo code changes detected.") is False


def test_checkpoint_prompt_detects_canonical_prefix():
    assert _is_checkpoint_prompt("[TeleClaude Checkpoint] - Context-aware checkpoint") is True


def test_codex_synthetic_prompt_detection_accepts_mapping_payload():
    payload = MappingProxyType({"synthetic": True, "source": "codex_output_polling"})
    assert _is_codex_synthetic_prompt_event(payload) is True


@pytest.mark.asyncio
async def test_user_prompt_submit_persists_non_checkpoint_codex_synthetic_prompt(coordinator):
    session = Session(
        session_id="sess-1",
        computer_name="macbook",
        tmux_session_name="tmux-1",
        title="Untitled",
        active_agent="codex",
    )
    payload = UserPromptSubmitPayload(
        prompt="Please investigate the output highlight regression",
        session_id="sess-1",
        raw={"synthetic": True, "source": "codex_output_polling"},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-1",
        data=payload,
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        with patch.object(coordinator, "_emit_activity_event") as mock_emit:
            with patch(
                "teleclaude.core.agent_coordinator.summarize_user_input_title", new_callable=AsyncMock
            ) as mock_summarize:
                mock_summarize.return_value = "Output regression follow-up"
                await coordinator.handle_user_prompt_submit(context)
            mock_emit.assert_called_once_with("sess-1", AgentHookEvents.USER_PROMPT_SUBMIT)

        mock_db.set_notification_flag.assert_called_once_with("sess-1", False)
        assert mock_db.update_session.await_count >= 1


@pytest.mark.asyncio
async def test_user_prompt_submit_broadcasts_hook_input_for_non_headless_sessions(coordinator, mock_client):
    session = Session(
        session_id="sess-1",
        computer_name="macbook",
        tmux_session_name="tmux-1",
        title="Active test",
        active_agent="claude",
        lifecycle_status="active",
    )
    payload = UserPromptSubmitPayload(prompt="please continue", session_id="sess-1")
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-1",
        data=payload,
    )

    mock_client.broadcast_user_input = AsyncMock()
    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        with patch.object(coordinator, "_emit_activity_event") as mock_emit:
            await coordinator.handle_user_prompt_submit(context)
            mock_emit.assert_called_once_with("sess-1", AgentHookEvents.USER_PROMPT_SUBMIT)

    mock_client.broadcast_user_input.assert_awaited_once()
    broadcast_call = mock_client.broadcast_user_input.await_args
    assert broadcast_call.args == (session, "please continue", InputOrigin.TERMINAL.value)
    assert isinstance(broadcast_call.kwargs.get("actor_id"), str)
    assert broadcast_call.kwargs["actor_id"].endswith(":sess-1")
    assert isinstance(broadcast_call.kwargs.get("actor_name"), str)
    assert broadcast_call.kwargs["actor_name"]


@pytest.mark.asyncio
async def test_user_prompt_submit_skips_duplicate_reflection_for_recent_routed_input(coordinator, mock_client):
    session = Session(
        session_id="sess-dup-1",
        computer_name="macbook",
        tmux_session_name="tmux-dup-1",
        title="Active test",
        active_agent="claude",
        lifecycle_status="active",
        last_input_origin=InputOrigin.API.value,
        last_message_sent="please continue",
        last_message_sent_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    payload = UserPromptSubmitPayload(prompt="please continue", session_id="sess-dup-1")
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-dup-1",
        data=payload,
    )

    mock_client.broadcast_user_input = AsyncMock()
    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        await coordinator.handle_user_prompt_submit(context)

    mock_client.broadcast_user_input.assert_not_awaited()
    for call in mock_db.update_session.await_args_list:
        assert "last_message_sent" not in call.kwargs


@pytest.mark.asyncio
async def test_user_prompt_submit_broadcasts_hook_input_for_headless_sessions(coordinator, mock_client):
    session = Session(
        session_id="sess-2",
        computer_name="macbook",
        tmux_session_name="tmux-2",
        title="Headless test",
        active_agent="claude",
        lifecycle_status="headless",
    )
    payload = UserPromptSubmitPayload(prompt="please continue", session_id="sess-2")
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-2",
        data=payload,
    )

    mock_client.broadcast_user_input = AsyncMock()
    process_message = AsyncMock()
    command_service = MagicMock()
    command_service.process_message = process_message

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.command_registry.get_command_service", return_value=command_service),
        patch.object(coordinator, "_emit_activity_event") as mock_emit,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        await coordinator.handle_user_prompt_submit(context)
        mock_emit.assert_called_once_with("sess-2", AgentHookEvents.USER_PROMPT_SUBMIT)

    # In headless mode, coordinator delegates reflection to process_message path.
    mock_client.broadcast_user_input.assert_not_awaited()
    process_message.assert_awaited_once()
    command = process_message.await_args.args[0]
    assert isinstance(command, ProcessMessageCommand)
    assert command.session_id == "sess-2"
    assert command.text == "please continue"
    assert command.origin == InputOrigin.TERMINAL.value
    assert isinstance(command.actor_id, str)
    assert command.actor_id.endswith(":sess-2")
    assert isinstance(command.actor_name, str)
    assert command.actor_name


@pytest.mark.asyncio
async def test_user_prompt_submit_ignores_tiny_codex_synthetic_prompt(coordinator):
    session = Session(
        session_id="sess-1",
        computer_name="macbook",
        tmux_session_name="tmux-1",
        title="Untitled",
        active_agent="codex",
    )
    payload = UserPromptSubmitPayload(
        prompt="r",
        session_id="sess-1",
        raw={"synthetic": True, "source": "codex_output_polling"},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-1",
        data=payload,
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        with patch.object(coordinator, "_emit_activity_event") as mock_emit:
            await coordinator.handle_user_prompt_submit(context)

        mock_db.set_notification_flag.assert_not_called()
        mock_db.update_session.assert_not_called()
        mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_user_prompt_submit_skips_title_summary_for_pasted_content_placeholder(coordinator):
    session = Session(
        session_id="sess-3",
        computer_name="macbook",
        tmux_session_name="tmux-3",
        title="Untitled",
        active_agent="codex",
    )
    payload = UserPromptSubmitPayload(
        prompt="[Pasted Content 5074 chars]",
        session_id="sess-3",
        raw={"synthetic": True, "source": "codex_output_polling"},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-3",
        data=payload,
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        with patch(
            "teleclaude.core.agent_coordinator.summarize_user_input_title", new_callable=AsyncMock
        ) as mock_summarize:
            await coordinator.handle_user_prompt_submit(context)

        mock_summarize.assert_not_awaited()
        mock_db.set_notification_flag.assert_called_once_with("sess-3", False)
        assert mock_db.update_session.await_count >= 1


@pytest.mark.asyncio
async def test_user_prompt_submit_emits_user_prompt_activity_for_non_synthetic_event(coordinator):
    session = Session(
        session_id="sess-2",
        computer_name="macbook",
        tmux_session_name="tmux-2",
        title="Untitled",
        active_agent="claude",
    )
    payload = UserPromptSubmitPayload(
        prompt="please continue",
        session_id="sess-2",
        raw={},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-2",
        data=payload,
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        with patch.object(coordinator, "_emit_activity_event") as mock_emit:
            await coordinator.handle_user_prompt_submit(context)

        mock_emit.assert_called_once_with("sess-2", AgentHookEvents.USER_PROMPT_SUBMIT)


@pytest.mark.asyncio
async def test_handle_agent_stop_codex_uses_transcript_timestamp_for_last_message_sent_at(coordinator):
    session_id = "sess-1"
    ts = datetime(2026, 2, 10, 3, 0, 0, tzinfo=timezone.utc)
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=("user prompt", ts))),
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()),
        patch.object(coordinator, "_maybe_send_headless_snapshot", new=AsyncMock()),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock()),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock()),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()

        await coordinator.handle_agent_stop(context)

        first_kwargs = mock_db.update_session.await_args_list[0].kwargs
        assert first_kwargs["last_message_sent"] == "user prompt"
        assert first_kwargs["last_message_sent_at"] == ts.isoformat()


@pytest.mark.asyncio
async def test_handle_agent_stop_codex_does_not_clobber_last_message_sent_at_without_timestamp(coordinator):
    session_id = "sess-1"
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=("user prompt", None))),
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()),
        patch.object(coordinator, "_maybe_send_headless_snapshot", new=AsyncMock()),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock()),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock()),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()

        await coordinator.handle_agent_stop(context)

        first_kwargs = mock_db.update_session.await_args_list[0].kwargs
        assert first_kwargs["last_message_sent"] == "user prompt"
        assert "last_message_sent_at" not in first_kwargs


@pytest.mark.asyncio
async def test_handle_agent_stop_codex_skips_backfill_when_submit_already_recorded_this_turn(coordinator):
    session_id = "sess-1"
    now = datetime(2026, 2, 13, 19, 31, 27, tzinfo=timezone.utc)
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
        last_message_sent="test, say hi",
        last_message_sent_at=now,
        last_output_at=now - timedelta(seconds=2),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=("test, say hi", now))),
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()),
        patch.object(coordinator, "_maybe_send_headless_snapshot", new=AsyncMock()),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock()),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock()),
        patch.object(coordinator, "_emit_activity_event") as mock_emit,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()

        await coordinator.handle_agent_stop(context)

        emitted_types = [call.args[1] for call in mock_emit.call_args_list]
        assert AgentHookEvents.USER_PROMPT_SUBMIT not in emitted_types
        assert AgentHookEvents.AGENT_STOP in emitted_types
        coordinator.client.broadcast_user_input.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_agent_stop_codex_backfill_reflects_user_input_to_adapters(coordinator):
    session_id = "sess-backfill"
    now = datetime(2026, 2, 13, 19, 31, 27, tzinfo=timezone.utc)
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
        lifecycle_status="active",
        last_message_sent="older prompt",
        last_message_sent_at=now - timedelta(minutes=5),
        last_output_at=now - timedelta(seconds=5),
    )

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=("new prompt", now))),
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()),
        patch.object(coordinator, "_maybe_send_headless_snapshot", new=AsyncMock()),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock()),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock()),
        patch.object(coordinator, "_emit_activity_event"),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()

        await coordinator.handle_agent_stop(context)

        coordinator.client.broadcast_user_input.assert_awaited_once()
        broadcast_call = coordinator.client.broadcast_user_input.await_args
        assert broadcast_call.args == (session, "new prompt", InputOrigin.TERMINAL.value)
        assert isinstance(broadcast_call.kwargs.get("actor_name"), str)
        assert broadcast_call.kwargs["actor_name"] == "operator"
        assert isinstance(broadcast_call.kwargs.get("actor_id"), str)
        assert broadcast_call.kwargs["actor_id"].endswith(f":{session_id}")


@pytest.mark.asyncio
async def test_handle_agent_stop_skips_whitespace_only_agent_output(coordinator):
    session_id = "sess-empty-output"
    payload = AgentStopPayload(
        session_id="native-1",
        transcript_path="/tmp/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "codex"},
    )
    context = AgentEventContext(event_type=AgentHookEvents.AGENT_STOP, session_id=session_id, data=payload)
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Test",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
    )

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch.object(coordinator, "_extract_user_input_for_codex", new=AsyncMock(return_value=None)),
        patch.object(coordinator, "_extract_agent_output", new=AsyncMock(return_value=" \n\t ")),
        patch.object(coordinator, "_summarize_output", new=AsyncMock(return_value="should-not-run")) as mock_sum,
        patch.object(coordinator, "_maybe_send_incremental_output", new=AsyncMock()),
        patch.object(coordinator, "_notify_session_listener", new=AsyncMock()),
        patch.object(coordinator, "_forward_stop_to_initiator", new=AsyncMock()),
        patch.object(coordinator, "_maybe_inject_checkpoint", new=AsyncMock()),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()

        await coordinator.handle_agent_stop(context)

        mock_sum.assert_not_awaited()
        coordinator.tts_manager.speak.assert_not_awaited()

        # Verify update_session was called but without feedback fields (whitespace-only output)
        assert not any("last_output_raw" in c.kwargs for c in mock_db.update_session.await_args_list)


@pytest.mark.asyncio
async def test_codex_checkpoint_injection_prefers_session_project_path(coordinator):
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-inject-1",
        computer_name="local",
        tmux_session_name="tmux-1",
        title="Inject",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
        project_path="/tmp/project-from-session",
        last_message_sent_at=now - timedelta(seconds=60),
    )

    with (
        patch(
            "teleclaude.core.agent_coordinator.inject_checkpoint_if_needed", new=AsyncMock(return_value=True)
        ) as mock_inject,
    ):
        await coordinator._maybe_inject_checkpoint(session.session_id, session)

        mock_inject.assert_awaited_once_with(
            session.session_id,
            route="codex_tmux",
            include_elapsed_since_turn_start=True,
            default_agent=AgentName.CLAUDE,
        )


@pytest.mark.asyncio
async def test_codex_checkpoint_injection_falls_back_to_transcript_workdir(coordinator):
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-inject-2",
        computer_name="local",
        tmux_session_name="tmux-2",
        title="Inject",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
        project_path=None,
        last_message_sent_at=now - timedelta(seconds=60),
    )

    with (
        patch(
            "teleclaude.core.agent_coordinator.inject_checkpoint_if_needed", new=AsyncMock(return_value=True)
        ) as mock_inject,
    ):
        await coordinator._maybe_inject_checkpoint(session.session_id, session)

        mock_inject.assert_awaited_once_with(
            session.session_id,
            route="codex_tmux",
            include_elapsed_since_turn_start=True,
            default_agent=AgentName.CLAUDE,
        )


@pytest.mark.asyncio
async def test_codex_checkpoint_injection_skips_when_no_payload(coordinator):
    now = datetime.now(timezone.utc)
    session = Session(
        session_id="sess-inject-3",
        computer_name="local",
        tmux_session_name="tmux-3",
        title="Inject",
        active_agent="codex",
        native_log_file="/tmp/transcript.jsonl",
        project_path="/tmp/project",
        last_message_sent_at=now - timedelta(seconds=60),
    )

    with (
        patch(
            "teleclaude.core.agent_coordinator.inject_checkpoint_if_needed", new=AsyncMock(return_value=False)
        ) as mock_inject,
    ):
        await coordinator._maybe_inject_checkpoint(session.session_id, session)

        mock_inject.assert_awaited_once_with(
            session.session_id,
            route="codex_tmux",
            include_elapsed_since_turn_start=True,
            default_agent=AgentName.CLAUDE,
        )


# ---------------------------------------------------------------------------
# Status emission and stall detection (I3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_user_prompt_submit_emits_accepted_status(coordinator):
    """handle_user_prompt_submit emits 'accepted' status and schedules stall detection."""
    session = Session(
        session_id="sess-status-1",
        computer_name="local",
        tmux_session_name="tmux-status-1",
        title="Status test",
        active_agent="claude",
        lifecycle_status="active",
    )
    payload = UserPromptSubmitPayload(prompt="Hello agent", session_id="sess-status-1")
    context = AgentEventContext(
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        session_id="sess-status-1",
        data=payload,
    )

    emitted: list[tuple[str, object]] = []

    def capture_emit(event: str, ctx: object) -> None:
        emitted.append((event, ctx))

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_bus,
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=False),
        patch("teleclaude.core.agent_coordinator.summarize_user_input_title", new_callable=AsyncMock),
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.set_notification_flag = AsyncMock()
        mock_db.update_session = AsyncMock()
        mock_bus.emit.side_effect = capture_emit

        await coordinator.handle_user_prompt_submit(context)

    status_events = [ctx for event, ctx in emitted if event == TeleClaudeEvents.SESSION_STATUS]
    assert len(status_events) == 1
    assert status_events[0].status == "accepted"  # type: ignore[union-attr]
    assert status_events[0].reason == "user_prompt_accepted"  # type: ignore[union-attr]

    # Stall task must be scheduled
    assert "sess-status-1" in coordinator._stall_tasks
    coordinator._cancel_stall_task("sess-status-1")


@pytest.mark.asyncio
async def test_handle_tool_use_emits_active_output_and_cancels_stall(coordinator):
    """handle_tool_use emits 'active_output' and cancels any pending stall task."""
    session_id = "sess-status-2"
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-status-2",
        title="Tool use test",
        active_agent="claude",
    )
    payload = AgentOutputPayload(session_id=session_id, raw={"tool": "bash", "input": {}})
    context = AgentEventContext(
        event_type=AgentHookEvents.TOOL_USE,
        session_id=session_id,
        data=payload,
    )

    # Pre-plant a stall task to verify it gets cancelled
    import asyncio

    dummy_task = asyncio.create_task(asyncio.sleep(999))
    coordinator._stall_tasks[session_id] = dummy_task

    emitted: list[tuple[str, object]] = []

    with (
        patch("teleclaude.core.agent_coordinator.db") as mock_db,
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_bus,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        mock_bus.emit.side_effect = lambda event, ctx: emitted.append((event, ctx))

        await coordinator.handle_tool_use(context)

    # Yield control so the cancelled task can process its CancelledError
    import asyncio as _asyncio

    await _asyncio.sleep(0)

    assert dummy_task.cancelled()
    assert session_id not in coordinator._stall_tasks

    status_events = [ctx for event, ctx in emitted if event == TeleClaudeEvents.SESSION_STATUS]
    assert any(ctx.status == "active_output" for ctx in status_events)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_handle_agent_stop_emits_completed_and_cancels_stall(coordinator, mock_client):
    """handle_agent_stop emits 'completed' status and cancels any pending stall task."""
    session_id = "sess-status-3"
    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/path/to/transcript.jsonl",
        source_computer="local",
        raw={"agent_name": "claude"},
    )
    context = AgentEventContext(
        event_type=AgentHookEvents.AGENT_STOP,
        session_id=session_id,
        data=payload,
    )
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name="tmux-status-3",
        title="Stop test",
        active_agent="claude",
        native_log_file="/path/to/transcript.jsonl",
    )

    import asyncio

    dummy_task = asyncio.create_task(asyncio.sleep(999))
    coordinator._stall_tasks[session_id] = dummy_task

    emitted: list[tuple[str, object]] = []

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new_callable=AsyncMock, return_value=session),
        patch("teleclaude.core.agent_coordinator.db.update_session", new_callable=AsyncMock),
        patch("teleclaude.core.agent_coordinator.is_threaded_output_enabled", return_value=False),
        patch(
            "teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock, return_value=("T", "S")
        ),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="msg"),
        patch("teleclaude.core.agent_coordinator.event_bus") as mock_bus,
    ):
        mock_bus.emit.side_effect = lambda event, ctx: emitted.append((event, ctx))

        await coordinator.handle_agent_stop(context)

    # Yield control so the cancelled task can process its CancelledError
    import asyncio as _asyncio

    await _asyncio.sleep(0)

    assert dummy_task.cancelled()
    assert session_id not in coordinator._stall_tasks

    status_events = [ctx for event, ctx in emitted if event == TeleClaudeEvents.SESSION_STATUS]
    assert any(ctx.status == "completed" for ctx in status_events)  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_stall_detection_transitions_to_awaiting_then_stalled(coordinator):
    """_schedule_stall_detection transitions accepted → awaiting_output → stalled on timeout."""
    import asyncio

    session_id = "sess-stall-1"
    emitted: list[tuple[str, object]] = []

    with patch("teleclaude.core.agent_coordinator.event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda event, ctx: emitted.append((event, ctx))

        with (
            patch("teleclaude.core.agent_coordinator.AWAITING_OUTPUT_THRESHOLD_SECONDS", 0.01),
            patch("teleclaude.core.agent_coordinator.STALL_THRESHOLD_SECONDS", 0.02),
        ):
            coordinator._schedule_stall_detection(session_id, last_activity_at="2026-01-01T00:00:00+00:00")
            await asyncio.sleep(0.05)

    statuses = [ctx.status for event, ctx in emitted if event == TeleClaudeEvents.SESSION_STATUS]  # type: ignore[union-attr]
    assert "awaiting_output" in statuses
    assert "stalled" in statuses
    assert statuses.index("awaiting_output") < statuses.index("stalled")


@pytest.mark.asyncio
async def test_stall_cancellation_prevents_stale_transitions(coordinator):
    """Cancelling the stall task before timeout prevents awaiting_output and stalled events."""
    import asyncio

    session_id = "sess-stall-2"
    emitted: list[tuple[str, object]] = []

    with patch("teleclaude.core.agent_coordinator.event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda event, ctx: emitted.append((event, ctx))

        with (
            patch("teleclaude.core.agent_coordinator.AWAITING_OUTPUT_THRESHOLD_SECONDS", 0.05),
            patch("teleclaude.core.agent_coordinator.STALL_THRESHOLD_SECONDS", 0.10),
        ):
            coordinator._schedule_stall_detection(session_id, last_activity_at="2026-01-01T00:00:00+00:00")
            await asyncio.sleep(0.01)
            coordinator._cancel_stall_task(session_id)
            await asyncio.sleep(0.15)

    statuses = [ctx.status for event, ctx in emitted if event == TeleClaudeEvents.SESSION_STATUS]  # type: ignore[union-attr]
    assert "awaiting_output" not in statuses
    assert "stalled" not in statuses
