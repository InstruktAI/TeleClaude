"""Characterization tests for teleclaude.core.command_handlers._message."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from teleclaude.core.command_handlers import _message
from teleclaude.core.conversation_messages import format_peer_message
from teleclaude.core.db import InboundQueueRow
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.inbound_queue import InboundQueueManager
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


def make_row(*, session_id: str, content: str, origin: str = "ui", payload_json: str | None = None) -> InboundQueueRow:
    """Build a typed inbound queue row for delivery tests."""
    return InboundQueueRow(
        id=1,
        session_id=session_id,
        origin=origin,
        message_type="text",
        content=content,
        payload_json=payload_json,
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
            origin_metadata={"user_id": "123"},
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
        assert forwarded.origin_metadata == {"user_id": "123"}

    @pytest.mark.unit
    async def test_transcribed_voice_skip_delete_when_message_id_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session(active_agent="codex")
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
        )
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
            message_id="",
            origin="discord",
            actor_id="actor-1",
            actor_name="Bob",
            actor_avatar_url="https://avatar.example/bob.png",
        )

        await _message.handle_voice(cmd, client, AsyncMock())

        client.delete_message.assert_not_awaited()

    @pytest.mark.unit
    async def test_transcribed_voice_logs_when_session_missing_for_cleanup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        session = make_session(active_agent="codex")
        db = SimpleNamespace(
            get_session=AsyncMock(side_effect=[session, None, session]),
            update_session=AsyncMock(),
        )
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

        with caplog.at_level("WARNING"):
            await _message.handle_voice(cmd, client, AsyncMock())

        client.delete_message.assert_not_awaited()
        assert any("Session sess-001 not found for voice delete" in record.message for record in caplog.records)


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
    async def test_inbound_delivery_writes_session_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Legacy inbound rows fill accepted metadata during delivery."""
        session = make_session(active_agent="claude")
        row = make_row(session_id=session.session_id, content="Please explain the latest failure.")
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        client = SimpleNamespace(break_threaded_turn=AsyncMock())
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        await _message.deliver_inbound(row, client, AsyncMock())

        update_kwargs = db.update_session.await_args_list[0].kwargs
        assert update_kwargs["last_message_sent"] == "Please explain the latest failure."
        assert update_kwargs["last_input_origin"] == row["origin"]
        assert "last_message_sent_at" in update_kwargs

    @pytest.mark.unit
    async def test_inbound_delivery_skips_metadata_write_when_acceptance_is_current(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        message_text = "Please explain the latest failure."
        session = make_session(active_agent="claude")
        session.last_message_sent = message_text
        session.last_message_sent_at = datetime.now(UTC)
        session.last_input_origin = "ui"
        row = make_row(session_id=session.session_id, content=message_text)
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        client = SimpleNamespace(break_threaded_turn=AsyncMock())
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        await _message.deliver_inbound(row, client, AsyncMock())

        db.update_session.assert_not_awaited()

    @pytest.mark.unit
    async def test_codex_message_starts_polling_without_synthetic_seed(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
            break_threaded_turn=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        start_polling = AsyncMock()

        await _message.deliver_inbound(row, client, start_polling)

        tmux_io.process_text.assert_awaited_once_with(
            session,
            "hello agent",
            working_dir="/tmp/project",
            active_agent="codex",
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
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        manager = SimpleNamespace(enqueue=AsyncMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "get_inbound_queue_manager", lambda: manager)

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text="ship it",
            origin="web",
            actor_id="actor-1",
            actor_name="Bob",
            source_message_id="msg-1",
            source_channel_id="chan-1",
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        manager.enqueue.assert_awaited_once_with(
            session_id=session.session_id,
            origin="web",
            content="ship it",
            payload_json=None,
            actor_id="actor-1",
            actor_name="Bob",
            actor_avatar_url=None,
            source_message_id="msg-1",
            source_channel_id="chan-1",
            post_insert_callback=ANY,
        )

    @pytest.mark.unit
    async def test_successful_enqueue_records_acceptance_before_queue_side_effects(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session()
        events: list[str] = []

        async def typing_callback(_session_id: str, _origin: str) -> None:
            events.append("typing")

        def ensure_worker(_session_id: str) -> None:
            events.append("worker")

        async def update_session(_session_id: str, **_fields: object) -> None:
            events.append("accepted")

        inbound_db = SimpleNamespace(enqueue_inbound=AsyncMock(return_value=12))
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(side_effect=update_session),
        )
        manager = InboundQueueManager(deliver_fn=AsyncMock(), typing_callback=typing_callback)
        manager._ensure_worker = ensure_worker

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "get_inbound_queue_manager", lambda: manager)
        monkeypatch.setattr("teleclaude.core.inbound_queue.db", inbound_db)

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text="ship it",
            origin="web",
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        assert events == ["accepted", "typing", "worker"]
        db.update_session.assert_awaited_once()
        update_kwargs = db.update_session.await_args.kwargs
        assert update_kwargs["last_message_sent"] == cmd.text
        assert update_kwargs["last_input_origin"] == cmd.origin
        assert "last_message_sent_at" in update_kwargs

    @pytest.mark.unit
    async def test_dedup_enqueue_skip_does_not_record_acceptance_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = make_session()
        inbound_db = SimpleNamespace(enqueue_inbound=AsyncMock(return_value=None))
        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_origin_metadata=AsyncMock(),
        )
        manager = InboundQueueManager(deliver_fn=AsyncMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "get_inbound_queue_manager", lambda: manager)
        monkeypatch.setattr("teleclaude.core.inbound_queue.db", inbound_db)

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text="ship it",
            origin="web",
            source_message_id="source-message",
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        db.update_session.assert_not_awaited()
        db.update_origin_metadata.assert_not_awaited()

    @pytest.mark.unit
    async def test_linked_short_reply_is_enqueued(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        manager = SimpleNamespace(enqueue=AsyncMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "get_inbound_queue_manager", lambda: manager)

        content = format_peer_message(
            sender_session_id="peer-001",
            sender_computer="remote",
            segments=[("assistant", datetime(2026, 5, 9, 10, 0, 0, tzinfo=UTC), "Thanks.")],
        )
        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text=content,
            origin="terminal",
            source_channel_id="link-001",
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        manager.enqueue.assert_awaited_once_with(
            session_id=session.session_id,
            origin="terminal",
            content=content,
            payload_json=None,
            actor_id=None,
            actor_name=None,
            actor_avatar_url=None,
            source_message_id=None,
            source_channel_id="link-001",
            post_insert_callback=ANY,
        )

    @pytest.mark.unit
    async def test_origin_metadata_is_encoded_into_queue_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        db = SimpleNamespace(get_session=AsyncMock(return_value=session))
        manager = SimpleNamespace(enqueue=AsyncMock())

        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "get_inbound_queue_manager", lambda: manager)

        cmd = ProcessMessageCommand(
            session_id=session.session_id,
            text="ship it",
            origin="terminal",
            origin_metadata={"email": "maurice@instrukt.ai"},
        )

        await _message.process_message(cmd, SimpleNamespace(), AsyncMock())

        manager.enqueue.assert_awaited_once_with(
            session_id=session.session_id,
            origin="terminal",
            content="ship it",
            payload_json='{"origin_metadata": {"email": "maurice@instrukt.ai"}}',
            actor_id=None,
            actor_name=None,
            actor_avatar_url=None,
            source_message_id=None,
            source_channel_id=None,
            post_insert_callback=ANY,
        )


class TestDeliverInboundReflectionBoundary:
    """Inbound delivery does not emit immediate reflection — projection handles it."""

    @pytest.mark.unit
    async def test_deliver_inbound_does_not_call_broadcast_user_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inbound reflection is projection-driven, not acceptance-driven.

        deliver_inbound sets operational metadata (last_message_sent_at, last_input_origin)
        but does NOT call broadcast_user_input — that is projection's responsibility.
        """
        session = make_session()
        row = make_row(session_id=session.session_id, content="hello", origin="telegram")
        client = AsyncMock()

        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        await _message.deliver_inbound(row, client, AsyncMock())

        client.broadcast_user_input.assert_not_awaited()

    @pytest.mark.unit
    async def test_deliver_inbound_persists_origin_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = make_session()
        row = make_row(
            session_id=session.session_id,
            content="hello",
            origin="terminal",
            payload_json='{"origin_metadata": {"email": "maurice@instrukt.ai"}}',
        )
        client = AsyncMock()

        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_origin_metadata=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        await _message.deliver_inbound(row, client, AsyncMock())

        db.update_origin_metadata.assert_awaited_once_with(
            session.session_id,
            "terminal",
            {"email": "maurice@instrukt.ai"},
        )

    @pytest.mark.unit
    async def test_deliver_inbound_does_not_write_last_projected_at(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Acceptance code must not advance the projection watermark."""
        session = make_session()
        row = make_row(session_id=session.session_id, content="hello", origin="telegram")
        client = AsyncMock()

        db = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            update_session=AsyncMock(),
            update_last_activity=AsyncMock(),
        )
        tmux_io = SimpleNamespace(
            process_text=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(_message, "db", db)
        monkeypatch.setattr(_message, "tmux_io", tmux_io)
        monkeypatch.setattr(_message, "_session_message_delivery_available", AsyncMock(return_value=True))
        monkeypatch.setattr(_message, "resolve_working_dir", MagicMock(return_value="/tmp/project"))

        await _message.deliver_inbound(row, client, AsyncMock())

        for call in db.update_session.await_args_list:
            assert "last_projected_at" not in call.kwargs, (
                "deliver_inbound must not write last_projected_at — projection owns the watermark"
            )
