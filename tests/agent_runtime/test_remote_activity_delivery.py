"""Functional regressions for remote session activity delivery."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

import teleclaude.core.adapter_client._output as output_mod
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.constants import EVENT_NEW_SESSION
from teleclaude.core.adapter_client import AdapterRuntime
from teleclaude.core.models import ChannelMetadata, MessageMetadata, PeerInfo, Session, SessionSnapshot
from teleclaude.core.origins import InputOrigin
from teleclaude.transport.redis_transport._messaging import _MessagingMixin
from teleclaude.transport.redis_transport._request_response import _RequestResponseMixin

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


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


class _TypingAdapter(UiAdapter):
    ADAPTER_KEY = "discord"

    def __init__(self) -> None:
        super().__init__(client=SimpleNamespace())
        self.typing_count = 0
        self.seen_origin_metadata: dict[str, object] = {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def create_channel(self, session: Session, title: str, metadata: ChannelMetadata) -> str:
        del session, title, metadata
        return "channel"

    async def update_channel_title(self, session: Session) -> bool:
        del session
        return True

    async def close_channel(self, session: Session) -> bool:
        del session
        return True

    async def reopen_channel(self, session: Session) -> bool:
        del session
        return True

    async def delete_channel(self, session: Session) -> bool:
        del session
        return True

    async def send_message(
        self,
        session: Session,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
        multi_message: bool = False,
    ) -> str:
        del session, text, metadata, multi_message
        return "message"

    async def edit_message(
        self,
        session: Session,
        message_id: str,
        text: str,
        *,
        metadata: MessageMetadata | None = None,
    ) -> bool:
        del session, message_id, text, metadata
        return True

    async def delete_message(self, session: Session, message_id: str) -> bool:
        del session, message_id
        return True

    async def send_file(
        self,
        session: Session,
        file_path: str,
        *,
        caption: str | None = None,
        metadata: MessageMetadata | None = None,
    ) -> str:
        del session, file_path, caption, metadata
        return "file"

    async def discover_peers(self) -> list[PeerInfo]:
        return []

    async def poll_output_stream(self, session: Session, timeout: float = 300.0) -> AsyncIterator[str]:
        del session, timeout
        if self.typing_count < 0:
            yield ""

    def get_max_message_length(self) -> int:
        return 2000

    def get_ai_session_poll_interval(self) -> float:
        return 1.0

    def get_action_throttle_interval_s(self, action_kind: str) -> float:
        del action_kind
        return 0.0

    async def send_typing_indicator(self, session: Session) -> None:
        self.seen_origin_metadata = session.origin_metadata
        self.typing_count += 1


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
