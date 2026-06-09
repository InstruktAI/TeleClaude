"""Functional bindings for output polling and delivery scenarios."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast

import pytest

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord.message_ops import MessageOperationsMixin
from teleclaude.core import voice_message_handler
from teleclaude.core.db import Db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


class _WebhookSend(TypedDict, total=False):
    content: str
    username: str
    wait: bool
    avatar_url: str


class _DiscordChannel:
    def __init__(self, webhook: _DiscordWebhook | None = None, *, create_fails: bool = False) -> None:
        self.id = 123
        self.bot_sends: list[str] = []
        self.created_webhook = webhook
        self.create_fails = create_fails

    async def send(self, text: str) -> object:
        self.bot_sends.append(text)
        return SimpleNamespace(id=f"bot-{len(self.bot_sends)}")

    async def webhooks(self) -> list[object]:
        return []

    async def create_webhook(self, *, name: str) -> object:
        if self.create_fails:
            raise TimeoutError("webhook create failed")
        if self.created_webhook is None:
            self.created_webhook = _DiscordWebhook()
        self.created_webhook.name = name
        return self.created_webhook


class _DiscordWebhook:
    def __init__(self, *, send_fails: bool = False) -> None:
        self.name = "TeleClaude Reflections"
        self.send_fails = send_fails
        self.sends: list[_WebhookSend] = []

    async def send(self, **kwargs: object) -> object:
        if self.send_fails:
            raise TimeoutError("webhook send failed")
        payload: _WebhookSend = {
            "content": str(kwargs["content"]),
            "username": str(kwargs["username"]),
            "wait": bool(kwargs["wait"]),
        }
        avatar_url = kwargs.get("avatar_url")
        if avatar_url is not None:
            payload["avatar_url"] = str(avatar_url)
        self.sends.append(payload)
        return SimpleNamespace(id=f"webhook-{len(self.sends)}")


class _DiscordMessageBoundary(MessageOperationsMixin):
    def __init__(self, destination: _DiscordChannel) -> None:
        self.destination = destination
        self.max_message_size = 2000
        self._TRUNCATION_SUFFIX = "..."
        self.ADAPTER_KEY = InputOrigin.DISCORD.value
        self._reflection_webhook_cache: dict[int, object] = {}
        self._discord = SimpleNamespace()

    async def _resolve_destination_channel(
        self,
        session: Session,
        metadata: MessageMetadata | None = None,
    ) -> object:
        del session, metadata
        return self.destination

    @staticmethod
    def _is_thread_channel(channel: object) -> bool:
        return bool(getattr(channel, "is_thread", False))

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AdapterError(f"{label} is not callable")
        return cast(Callable[..., Awaitable[object]], fn)

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        return int(str(value))


def _session() -> Session:
    return Session(
        session_id="session-output-delivery",
        computer_name="local",
        tmux_session_name="tmux-output-delivery",
        title="Output delivery",
        last_input_origin=InputOrigin.TERMINAL.value,
    )


def _reflection_metadata() -> MessageMetadata:
    return MessageMetadata(
        parse_mode=None,
        reflection_actor_id="user-1",
        reflection_actor_name="Morriz",
        reflection_actor_avatar_url="https://example.test/avatar.png",
        reflection_origin=InputOrigin.TERMINAL.value,
    )


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD4")
async def test_discord_admin_reflection_preserves_user_attribution_for_text_input(snapshot: object) -> None:
    webhook = _DiscordWebhook()
    channel = _DiscordChannel(webhook)
    adapter = _DiscordMessageBoundary(channel)

    message_id = await adapter.send_message(_session(), "hello from user", metadata=_reflection_metadata())

    assert {
        "message_id": message_id,
        "bot_send_count": len(channel.bot_sends),
        "webhook_sends": webhook.sends,
    } == snapshot


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD5")
async def test_discord_reflection_webhook_failure_never_posts_user_text_as_the_bot() -> None:
    channel = _DiscordChannel(create_fails=True)
    adapter = _DiscordMessageBoundary(channel)

    with pytest.raises(AdapterError):
        await adapter.send_message(_session(), "hello from user", metadata=_reflection_metadata())

    assert channel.bot_sends == []


async def test_discord_non_reflection_output_still_uses_normal_send(snapshot: object) -> None:
    channel = _DiscordChannel()
    adapter = _DiscordMessageBoundary(channel)

    message_id = await adapter.send_message(_session(), "hello from agent", metadata=MessageMetadata(parse_mode=None))

    assert {
        "message_id": message_id,
        "bot_sends": channel.bot_sends,
    } == snapshot


class _VoiceIdentityResolver:
    registered_people_count = 1

    @staticmethod
    def resolve(origin: str, origin_metadata: Mapping[str, object]) -> IdentityContext:
        if origin == InputOrigin.DISCORD.value and origin_metadata.get("user_id") == "discord-user-2":
            return IdentityContext(
                person_name="Morriz",
                platform=InputOrigin.DISCORD.value,
                platform_user_id="discord-user-2",
            )
        return IdentityContext()


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD6")
async def test_discord_user_transcription_displays_use_user_attribution_or_do_not_render(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    snapshot: object,
) -> None:
    db = Db(":memory:")
    await db.initialize()
    await db.create_session(
        computer_name="local",
        tmux_session_name="voice-session",
        last_input_origin=InputOrigin.DISCORD.value,
        title="voice session",
        session_id="session-voice",
        emit_session_started=False,
    )
    await db.update_origin_metadata(
        "session-voice",
        InputOrigin.DISCORD.value,
        {"user_id": "discord-user-2"},
    )

    sent_messages: list[tuple[str, MessageMetadata]] = []
    edited_messages: list[tuple[str, MessageMetadata]] = []
    deleted_messages: list[str] = []

    async def send_message(_session_id: str, message: str, metadata: MessageMetadata) -> str | None:
        sent_messages.append((message, metadata))
        return f"sent-{len(sent_messages)}"

    async def edit_message(
        _session_id: str,
        message_id: str,
        message: str,
        metadata: MessageMetadata,
    ) -> bool:
        edited_messages.append((message, metadata))
        return True

    async def delete_message(_session_id: str, message_id: str) -> None:
        deleted_messages.append(message_id)

    transcriptions = iter(["resolved transcription", "anonymous transcription"])

    async def transcribe_voice_with_retry(
        audio_file_path: str,
        language: str | None = None,
    ) -> tuple[str | None, str | None]:
        del audio_file_path, language
        return next(transcriptions), None

    monkeypatch.setattr(voice_message_handler, "db", db)
    monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", _async_true)
    monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe_voice_with_retry)
    monkeypatch.setattr(
        voice_message_handler,
        "get_identity_resolver",
        lambda: _VoiceIdentityResolver(),
        raising=False,
    )

    actor_audio = tmp_path / "actor.ogg"
    actor_audio.write_bytes(b"audio")
    anonymous_audio = tmp_path / "anonymous.ogg"
    anonymous_audio.write_bytes(b"audio")

    try:
        await voice_message_handler.handle_voice(
            session_id="session-voice",
            audio_path=str(actor_audio),
            context=VoiceEventContext(
                session_id="session-voice",
                file_path=str(actor_audio),
                origin=InputOrigin.DISCORD.value,
                actor_id="discord-user-1",
                actor_name="Morriz",
                actor_avatar_url="https://example.test/avatar.png",
                notice_message_id="notice-actor",
            ),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
        )
        await voice_message_handler.handle_voice(
            session_id="session-voice",
            audio_path=str(anonymous_audio),
            context=VoiceEventContext(
                session_id="session-voice",
                file_path=str(anonymous_audio),
                origin=InputOrigin.DISCORD.value,
                notice_message_id="notice-anonymous",
            ),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
        )
    finally:
        await db.close()

    assert all(message not in {"resolved transcription", "anonymous transcription"} for message, _ in edited_messages)
    assert {
        "sent_messages": [
            {
                "message": message,
                "reflection_origin": metadata.reflection_origin,
                "reflection_actor_name": metadata.reflection_actor_name,
                "reflection_actor_avatar_url": metadata.reflection_actor_avatar_url,
            }
            for message, metadata in sent_messages
        ],
        "deleted_messages": deleted_messages,
    } == snapshot


async def _async_true(*args: object, **kwargs: object) -> bool:
    del args, kwargs
    return True
