"""Functional regressions for remote session activity delivery."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypedDict, cast
from unittest.mock import AsyncMock

import pytest

import teleclaude.adapters.ui.delivery_mixin as ui_delivery_mixin_mod
import teleclaude.adapters.ui_adapter as ui_adapter_mod
import teleclaude.core.adapter_client._channels as channels_mod
import teleclaude.core.adapter_client._output as output_mod
import teleclaude.core.agent_coordinator._coordinator as coordinator_mod
import teleclaude.core.command_handlers._message as message_mod
import teleclaude.core.polling_coordinator as polling_coordinator_mod
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.adapter_client import AdapterRuntime
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.db import Db, InboundQueueRow
from teleclaude.core.delivery import Destination
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    SessionStatusContext,
    TeleClaudeEvents,
    build_agent_payload,
)
from teleclaude.core.models import (
    MessageMetadata,
    Session,
    SessionOriginMetadata,
    SessionSnapshot,
)
from teleclaude.core.origins import InputOrigin
from teleclaude.transport.redis_transport._messaging import _MessagingMixin
from teleclaude.transport.redis_transport._request_response import _RequestResponseMixin
from tests.agent_runtime._fake_ui_adapter import NoOpChannelLifecycleMixin

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


class _DiscordInboundMetadata(TypedDict, total=False):
    thread_id: str


class _RedisMemory:
    def __init__(self) -> None:
        self.last_stream = ""
        self.last_data: dict[bytes, bytes] = {}

    async def xadd(self, stream: str, data: dict[bytes, bytes], **kwargs: object) -> bytes:
        del kwargs
        self.last_stream = stream
        self.last_data = dict(data)
        return b"1-0"


class _RedisTransportBoundary(_RequestResponseMixin, _MessagingMixin):
    def __init__(self) -> None:
        self.computer_name = "master"
        self.message_stream_maxlen = 100
        self.output_stream_maxlen = 100
        self.redis = _RedisMemory()

    async def _get_redis(self) -> Redis:
        return cast("Redis", self.redis)


class _TypingAdapter(NoOpChannelLifecycleMixin, UiAdapter):
    ADAPTER_KEY = "discord"

    def __init__(self) -> None:
        super().__init__(client=SimpleNamespace())
        self.typing_count = 0
        self.badge_count = 0
        self.seen_origin_metadata: SessionOriginMetadata = cast(SessionOriginMetadata, {})

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        del destination, text, metadata, multi_message
        return "message"

    def get_max_message_length(self) -> int:
        return 2000

    def get_action_throttle_interval_s(self, action_kind: str) -> float:
        del action_kind
        return 0.0

    async def send_typing_indicator(self, session: Session) -> None:
        self.seen_origin_metadata = session.origin_metadata
        self.typing_count += 1

    async def _send_session_badge(self, session: Session) -> None:
        del session
        self.badge_count += 1


class _RecordingAdapter(_TypingAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str, str]] = []
        self.message_count = 0

    async def send_message(
        self,
        destination: Destination,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        del destination, metadata, multi_message
        self.message_count += 1
        message_id = f"sent-{self.message_count}"
        self.events.append(("send", message_id, text))
        return message_id

    async def edit_message(
        self,
        destination: Destination,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        del destination, metadata
        self.events.append(("edit", message_id, text))
        return True


class _NoLocalSessionDb:
    async def get_session(self, session_id: str) -> None:
        del session_id
        return None


class _RemoteSessionCache:
    def __init__(self, snapshot: SessionSnapshot) -> None:
        self._snapshot = snapshot

    def get_sessions(self, computer: str | None = None) -> list[SessionSnapshot]:
        if computer is None or computer == self._snapshot.computer:
            return [self._snapshot]
        return []


def _patch_db(monkeypatch: pytest.MonkeyPatch, test_db: Db) -> None:
    monkeypatch.setattr(channels_mod, "db", test_db)
    monkeypatch.setattr(coordinator_mod, "db", test_db)
    monkeypatch.setattr(output_mod, "db", test_db)
    monkeypatch.setattr(message_mod, "db", test_db)
    monkeypatch.setattr(polling_coordinator_mod, "db", test_db)
    monkeypatch.setattr(ui_adapter_mod, "db", test_db)
    monkeypatch.setattr(ui_delivery_mixin_mod, "db", test_db)


def _inbound_row(*, session_id: str, content: str, origin_metadata: _DiscordInboundMetadata) -> InboundQueueRow:
    return InboundQueueRow(
        id=1,
        session_id=session_id,
        origin=InputOrigin.DISCORD.value,
        message_type="text",
        content=content,
        payload_json=json.dumps({"origin_metadata": origin_metadata}),
        actor_id=None,
        actor_name=None,
        actor_avatar_url=None,
        status="processing",
        created_at=datetime.now(UTC).isoformat(),
        attempt_count=0,
        next_retry_at=None,
        last_error=None,
        source_message_id=None,
        source_channel_id=None,
    )


async def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 1.0) -> None:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout_s)
    while datetime.now(UTC) < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def test_redis_remote_session_request_preserves_origin_metadata() -> None:
    origin_metadata = {
        "user_id": "123",
        "discord_user_id": "123",
        "platform": "discord",
        "thread_id": "456",
    }
    metadata = MessageMetadata(
        origin=InputOrigin.DISCORD.value,
        origin_metadata=origin_metadata,
        human_role="admin",
    )
    boundary = _RedisTransportBoundary()

    await boundary.send_request("remote", EVENT_NEW_SESSION, metadata)
    parsed = boundary._parse_redis_message(boundary.redis.last_data)

    assert parsed.origin_metadata == origin_metadata


async def test_active_output_status_pulses_typing_indicator() -> None:
    adapter = _TypingAdapter()
    session = Session(
        session_id="sess-activity",
        computer_name="remote",
        tmux_session_name="tc-sess-activity",
        title="remote activity",
        lifecycle_status="active",
    )

    await adapter.on_session_status(session, "active_output")

    assert adapter.typing_count == 1


async def test_remote_cached_session_status_routes_discord_typing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(output_mod, "db", _NoLocalSessionDb())
    runtime = AdapterRuntime()
    adapter = _TypingAdapter()
    runtime.adapters["discord"] = adapter

    origin_metadata = {"discord": {"thread_id": "456"}}
    session = Session(
        session_id="sess-remote",
        computer_name="peer",
        tmux_session_name="tc-sess-remote",
        title="remote activity",
        last_input_origin=InputOrigin.TERMINAL.value,
        origin_metadata=origin_metadata,
        lifecycle_status="active",
    )
    runtime.cache = _RemoteSessionCache(SessionSnapshot.from_db_session(session, computer="peer"))

    await runtime.dispatch_session_status("sess-remote", "active_output")

    assert adapter.typing_count == 1
    assert adapter.seen_origin_metadata == origin_metadata


async def test_input_acceptance_opens_turn_and_pulses_typing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    del cluster_event_bus
    test_db = Db(":memory:")
    await test_db.initialize()
    try:
        _patch_db(monkeypatch, test_db)
        guarded_inject = AsyncMock(return_value=True)
        monkeypatch.setattr(message_mod.tmux_bridge, "session_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(message_mod.tmux_io, "inject_user_turn", guarded_inject)
        monkeypatch.setattr(message_mod.tmux_io, "process_text", AsyncMock(return_value=False))
        start_polling = AsyncMock()

        await test_db.create_session(
            computer_name="local",
            tmux_session_name="tc-sess-input",
            last_input_origin=InputOrigin.TERMINAL.value,
            title="input",
            session_id="sess-input",
            project_path=str(tmp_path),
            active_agent="codex",
            emit_session_started=False,
        )
        await test_db.update_origin_metadata(
            "sess-input",
            InputOrigin.DISCORD.value,
            {"output_message_id": "old-message", "char_offset": 42},
        )

        runtime = AdapterRuntime()
        adapter = _TypingAdapter()
        runtime.adapters[InputOrigin.DISCORD.value] = adapter

        await message_mod.deliver_inbound(
            _inbound_row(
                session_id="sess-input",
                content="new input",
                origin_metadata={"thread_id": "thread-1"},
            ),
            runtime,
            start_polling,
        )

        await _wait_until(lambda: adapter.typing_count == 1)
        fresh = await test_db.get_session("sess-input")
        assert fresh is not None
        discord_section = fresh.get_origin_section(InputOrigin.DISCORD.value)
        assert fresh.last_input_origin == InputOrigin.DISCORD.value
        assert "output_message_id" not in discord_section
        assert discord_section["char_offset"] == 0
        assert discord_section["turn_open_pending"] is True
        assert adapter.typing_count == 1
        assert adapter.badge_count == 1
        guarded_inject.assert_awaited_once()
        message_mod.tmux_io.process_text.assert_not_awaited()
        start_polling.assert_awaited_once_with("sess-input", "tc-sess-input")
    finally:
        await test_db.close()


async def test_ui_input_acceptance_and_late_hook_emit_single_accepted_badge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    del cluster_event_bus
    test_db = Db(":memory:")
    await test_db.initialize()
    try:
        _patch_db(monkeypatch, test_db)
        monkeypatch.setattr(message_mod.tmux_bridge, "session_exists", AsyncMock(return_value=True))
        monkeypatch.setattr(message_mod.tmux_io, "process_text", AsyncMock(return_value=True))
        monkeypatch.setattr(polling_coordinator_mod, "schedule_session_projection", AsyncMock(return_value=None))
        start_polling = AsyncMock()
        accepted_events: list[SessionStatusContext] = []

        async def _record_status(_event: str, context: SessionStatusContext) -> None:
            if context.session_id == "sess-single-badge" and context.status == "accepted":
                accepted_events.append(context)

        event_bus.subscribe(TeleClaudeEvents.SESSION_STATUS, _record_status)

        await test_db.create_session(
            computer_name="local",
            tmux_session_name="tc-sess-single-badge",
            last_input_origin=InputOrigin.TERMINAL.value,
            title="input",
            session_id="sess-single-badge",
            project_path=str(tmp_path),
            emit_session_started=False,
        )

        runtime = AdapterRuntime()
        adapter = _TypingAdapter()
        runtime.adapters[InputOrigin.DISCORD.value] = adapter

        await message_mod.deliver_inbound(
            _inbound_row(
                session_id="sess-single-badge",
                content="new input",
                origin_metadata={"thread_id": "thread-1"},
            ),
            runtime,
            start_polling,
        )
        await _wait_until(lambda: adapter.badge_count == 1 and len(accepted_events) == 1)

        coordinator = AgentCoordinator(
            client=runtime,
            tts_manager=SimpleNamespace(speak=AsyncMock()),
        )
        payload = build_agent_payload(AgentHookEvents.USER_PROMPT_SUBMIT, {"prompt": "new input"})
        await coordinator.handle_user_prompt_submit(
            AgentEventContext(
                session_id="sess-single-badge",
                data=payload,
                event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
            )
        )
        await asyncio.sleep(0)

        fresh = await test_db.get_session("sess-single-badge")
        assert fresh is not None
        assert fresh.last_input_origin == InputOrigin.DISCORD.value
        assert adapter.badge_count == 1
        assert len(accepted_events) == 1
    finally:
        await test_db.close()


async def test_pending_input_turn_reconciles_without_splitting_new_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cluster_event_bus: None,
) -> None:
    del cluster_event_bus
    test_db = Db(":memory:")
    await test_db.initialize()
    try:
        _patch_db(monkeypatch, test_db)
        previous_turn = datetime(2026, 6, 8, 8, 0, tzinfo=UTC)
        accepted_turn = previous_turn + timedelta(minutes=1)
        latest_boundary = previous_turn

        def _latest_boundary(_transcript_path: str, _agent_name: object) -> datetime:
            return latest_boundary

        monkeypatch.setattr(ui_adapter_mod, "extract_last_turn_boundary_timestamp", _latest_boundary)

        await test_db.create_session(
            computer_name="local",
            tmux_session_name="tc-sess-output",
            last_input_origin=InputOrigin.DISCORD.value,
            title="output",
            session_id="sess-output",
            project_path=str(tmp_path),
            native_log_file=str(tmp_path / "transcript.jsonl"),
            active_agent="codex",
            emit_session_started=False,
        )
        await test_db.update_origin_metadata(
            "sess-output",
            InputOrigin.DISCORD.value,
            {
                "thread_id": "thread-1",
                "output_message_id": "old-message",
                "char_offset": 0,
                "turn_anchor_ts": previous_turn.isoformat(),
            },
        )

        runtime = AdapterRuntime()
        adapter = _RecordingAdapter()
        runtime.adapters[InputOrigin.DISCORD.value] = adapter

        session = await test_db.get_session("sess-output")
        assert session is not None
        await runtime.send_output_update(session, "old output", 0.0, 0.0)
        assert ("edit", "old-message", "old output") in adapter.events

        session = await test_db.get_session("sess-output")
        assert session is not None
        await runtime.start_input_turn(session)

        session = await test_db.get_session("sess-output")
        assert session is not None
        await runtime.send_output_update(session, "new output", 0.0, 0.0)
        new_message_id = next(
            message_id for event, message_id, text in adapter.events if event == "send" and text == "new output"
        )

        latest_boundary = accepted_turn
        session = await test_db.get_session("sess-output")
        assert session is not None
        await runtime.send_output_update(session, "new output continued", 0.0, 0.0)

        assert ("edit", new_message_id, "new output continued") in adapter.events
        assert ("edit", "old-message", "new output") not in adapter.events
        assert ("send", new_message_id, "new output continued") not in adapter.events

        fresh = await test_db.get_session("sess-output")
        assert fresh is not None
        discord_section = fresh.get_origin_section(InputOrigin.DISCORD.value)
        assert discord_section["output_message_id"] == new_message_id
        assert discord_section["turn_anchor_ts"] == accepted_turn.isoformat()
        assert "turn_open_pending" not in discord_section
    finally:
        await test_db.close()
