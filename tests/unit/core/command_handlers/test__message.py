"""Characterization tests for teleclaude.core.command_handlers._message."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core.command_handlers import _message
from teleclaude.core.db import InboundQueueRow
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.models import CleanupTrigger, MessageMetadata, Session
from teleclaude.types.commands import HandleFileCommand, HandleVoiceCommand, ProcessMessageCommand


def make_session(
    *,
    session_id: str = "sess-001",
    lifecycle_status: str = "active",
    tmux_session_name: str = "tc-sess-001",
    project_path: str | None = "/tmp/project",
    subdir: str | None = None,
    active_agent: str | None = "claude",
) -> Session:
    """Build a concrete session for message-handler tests."""
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=tmux_session_name,
        title="Session",
        lifecycle_status=lifecycle_status,
        project_path=project_path,
        subdir=subdir,
        active_agent=active_agent,
    )


def make_row(*, session_id: str, content: str, origin: str = "ui") -> InboundQueueRow:
    """Build a typed inbound queue row for delivery tests."""
    return InboundQueueRow(
        id=1,
        session_id=session_id,
        origin=origin,
        message_type="text",
        content=content,
        payload_json=None,
        actor_id="actor-1",
        actor_name="Bob",
        actor_avatar_url="https://avatar.example/bob.png",
        status="queued",
        created_at="2025-01-01T00:00:00Z",
        attempt_count=0,
        next_retry_at=None,
        last_error=None,
        source_message_id=None,
        source_channel_id=None,
    )


class TestSessionMessageDeliveryAvailable:
    @pytest.mark.unit
    async def test_headless_session_is_available_without_tmux_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tmux_bridge = SimpleNamespace(session_exists=AsyncMock(return_value=False))
        monkeypatch.setattr(_message, "tmux_bridge", tmux_bridge)

        result = await _message._session_message_delivery_available(
            make_session(lifecycle_status="headless", tmux_session_name="")
        )

        assert result is True
        tmux_bridge.session_exists.assert_not_awaited()


class TestHandleVoice:
    @pytest.mark.unit
    async def test_transcribed_voice_is_forwarded_as_process_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent="codex")
        db = SimpleNamespace(get_session=AsyncMock(return_value=session), update_session=AsyncMock())
        client = SimpleNamespace(
            pre_handle_command=AsyncMock(),
            send_message=AsyncMock(return_value="feedback-1"),
            delete_message=AsyncMock(),
            break_threaded_turn=AsyncMock(),
        )
        voice_message_handler = SimpleNamespace(handle_voice=AsyncMock(return_value="hello there"))
        process_message = AsyncMock()

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "voice_message_handler", voice_message_handler)
        monkeypatch.setattr(_message, "process_message", process_message)

        cmd = HandleVoiceCommand(
            session_id=session.session_id,
            file_path="/tmp/voice.wav",
            message_id="voice-msg-1",
            origin="discord",
            actor_id="actor-1",
            actor_name="Bob",
            actor_avatar_url="https://avatar.example/bob.png",
        )

        await _message.handle_voice(cmd, client, AsyncMock())

        db.update_session.assert_awaited_once_with(session.session_id, last_input_origin="discord")
        client.delete_message.assert_awaited_once_with(session, "voice-msg-1")
        client.break_threaded_turn.assert_awaited_once_with(session)
        forwarded = process_message.await_args.args[0]
        assert isinstance(forwarded, ProcessMessageCommand)
        assert forwarded.text == "hello there"
        assert forwarded.origin == "discord"
        assert forwarded.actor_id == "actor-1"


class TestHandleFile:
    @pytest.mark.unit
    async def test_file_handler_notice_uses_next_notice_cleanup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        client = SimpleNamespace(send_message=AsyncMock(return_value="notice-1"))

        async def fake_handle_file_upload(
            *,
            session_id: str,
            file_path: str,
            filename: str,
            context: object,
            send_message: Callable[[str, str, MessageMetadata], Awaitable[str | None]],
        ) -> None:
            assert session_id == "sess-001"
            assert file_path == "/tmp/test.txt"
            assert filename == "test.txt"
            assert context is not None
            send_notice = send_message
            await send_notice(session_id, "uploaded", MessageMetadata())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "handle_file_upload", fake_handle_file_upload)

        cmd = HandleFileCommand(
            session_id=session.session_id,
            file_path="/tmp/test.txt",
            filename="test.txt",
            caption="demo",
            file_size=12,
        )

        await _message.handle_file(cmd, client)

        send_call = client.send_message.await_args
        assert send_call.args[:2] == (session, "uploaded")
        assert send_call.kwargs["cleanup_trigger"] == CleanupTrigger.NEXT_NOTICE


class TestWaitForSessionReady:
    @pytest.mark.unit
    async def test_wait_returns_refreshed_session_after_initializing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        initializing = make_session(lifecycle_status="initializing")
        ready = make_session(lifecycle_status="active")
        db = SimpleNamespace(get_session=AsyncMock(side_effect=[initializing, ready]))
        sleep = AsyncMock()

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message.asyncio, "sleep", sleep)

        result = await _message._wait_for_session_ready(initializing.session_id)

        assert result is ready
        sleep.assert_awaited_once_with(_message.STARTUP_GATE_POLL_INTERVAL_S)


class TestDeliverInbound:
    @pytest.mark.unit
    async def test_system_message_skips_tmux_injection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session(active_agent="claude")
        row = make_row(session_id=session.session_id, content=f"{TELECLAUDE_SYSTEM_PREFIX} Internal status")
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        client = SimpleNamespace(
            broadcast_user_input=AsyncMock(),
            break_threaded_turn=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
            wrap_bracketed_paste=MagicMock(return_value="<wrapped>"),
        )

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "is_threaded_output_enabled", lambda _agent: False)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))

        start_polling = AsyncMock()

        await _message.deliver_inbound(row, client, start_polling)

        tmux_io.process_text.assert_not_awaited()
        client.broadcast_user_input.assert_awaited_once()
        db.update_last_activity.assert_not_awaited()
        start_polling.assert_not_awaited()

    @pytest.mark.unit
    async def test_codex_message_seeds_prompt_and_starts_polling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Use headless lifecycle so _session_message_delivery_available returns True
        # without needing a separate patch (keeps mock count at 5).
        session = make_session(active_agent="codex", lifecycle_status="headless")
        row = make_row(session_id=session.session_id, content="hello agent")
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        client = SimpleNamespace(
            broadcast_user_input=AsyncMock(),
            break_threaded_turn=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
            wrap_bracketed_paste=MagicMock(return_value="<wrapped>"),
        )
        polling_coordinator = SimpleNamespace(seed_codex_prompt_from_message=MagicMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))
        monkeypatch.setattr(_message, "is_threaded_output_enabled", lambda _agent: False)
        monkeypatch.setattr(_message, "polling_coordinator", polling_coordinator)

        start_polling = AsyncMock()

        await _message.deliver_inbound(row, client, start_polling)

        tmux_io.process_text.assert_awaited_once_with(
            session,
            "<wrapped>",
            working_dir="/tmp/project",
            active_agent="codex",
        )
        polling_coordinator.seed_codex_prompt_from_message.assert_called_once_with(
            session.session_id,
            "hello agent",
        )
        db.update_last_activity.assert_awaited_once_with(session.session_id)
        start_polling.assert_awaited_once_with(session.session_id, session.tmux_session_name)

    @pytest.mark.unit
    async def test_closed_session_is_rejected_before_delivery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        session.closed_at = datetime.now(UTC)
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))

        monkeypatch.setattr(_message, "db", db)

        with pytest.raises(SessionMessageRejectedError):
            await _message.deliver_inbound(
                make_row(session_id=session.session_id, content="hello"),
                SimpleNamespace(),
                AsyncMock(),
            )


class TestProcessMessage:
    @pytest.mark.unit
    async def test_available_session_is_enqueued(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import teleclaude.core.inbound_queue as inbound_queue_module

        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        manager = SimpleNamespace(enqueue=AsyncMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(inbound_queue_module, "get_inbound_queue_manager", lambda: manager)

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text="ship it",
            origin="api",
            actor_id="actor-1",
            actor_name="Bob",
            source_message_id="msg-1",
            source_channel_id="chan-1",
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        manager.enqueue.assert_awaited_once_with(
            session_id=session.session_id,
            origin="api",
            content="ship it",
            actor_id="actor-1",
            actor_name="Bob",
            actor_avatar_url=None,
            source_message_id="msg-1",
            source_channel_id="chan-1",
        )
