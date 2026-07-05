"""Functional bindings for output polling and delivery scenarios."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast

import pytest

import teleclaude.core.adapter_client._output as output_mod
import teleclaude.core.tmux_bridge._pane as tmux_pane_mod
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord.message_ops import MessageOperationsMixin
from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config as app_config
from teleclaude.core import voice_message_handler
from teleclaude.core.adapter_client import AdapterRuntime
from teleclaude.core.agents import AgentName
from teleclaude.core.db import Db
from teleclaude.core.delivery import Destination
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import JsonDict, MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.output_poller import OutputChanged, OutputPoller
from teleclaude.utils.transcript import extract_last_user_message_with_timestamp
from tests.agent_runtime._fake_ui_adapter import NoOpChannelLifecycleMixin

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
        destination: Destination,
    ) -> object:
        del destination
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


class _DiscordUiBoundary(NoOpChannelLifecycleMixin, _DiscordMessageBoundary, UiAdapter):
    def __init__(self, destination: _DiscordChannel) -> None:
        UiAdapter.__init__(self, client=SimpleNamespace())
        _DiscordMessageBoundary.__init__(self, destination)

    def get_max_message_length(self) -> int:
        return self.max_message_size


def _session() -> Session:
    return Session(
        session_id="session-output-delivery",
        computer_name="local",
        tmux_session_name="tmux-output-delivery",
        title="Output delivery",
        last_input_origin=InputOrigin.TERMINAL.value,
    )


def _destination() -> Destination:
    """The Destination the seam resolves _session() to for Discord delivery."""
    return Destination(platform=InputOrigin.DISCORD.value, session_id=_session().session_id)


def _reflection_metadata() -> MessageMetadata:
    return MessageMetadata(
        parse_mode=None,
        reflection_actor_id="user-1",
        reflection_actor_name="Morriz",
        reflection_actor_avatar_url="https://example.test/avatar.png",
        reflection_origin=InputOrigin.TERMINAL.value,
    )


def _write_claude_transcript(path: Path, entries: Sequence[JsonDict]) -> None:
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")


def _command_message_text(*, additional_context: str | None = None) -> str:
    args = "suppress-command-body-in-projection"
    if additional_context is not None:
        args = f"{args}\n\nADDITIONAL CONTEXT:\n{additional_context}"
    return f"""<command-message>
<command-name>/next-build</command-name>
<command-args>{args}</command-args>
# Build

This procedure body must stay out of projected user text.
</command-message>"""


def _projected_last_user_message(transcript_path: Path) -> str:
    projected = extract_last_user_message_with_timestamp(str(transcript_path), AgentName.CLAUDE)
    assert projected is not None
    text, _timestamp = projected
    return text


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD1")
async def test_command_body_expansion_with_additional_context_projects_title_plus_section(
    tmp_path: Path,
    snapshot: object,
) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "message": {
                    "role": "user",
                    "content": _command_message_text(
                        additional_context="Keep this deployment scoped to transcript projection."
                    ),
                },
            },
        ],
    )

    assert _projected_last_user_message(transcript_path) == snapshot


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD2")
async def test_command_body_expansion_without_additional_context_projects_title_only(
    tmp_path: Path,
    snapshot: object,
) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "message": {
                    "role": "user",
                    "content": _command_message_text(),
                },
            },
        ],
    )

    assert _projected_last_user_message(transcript_path) == snapshot


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD3")
async def test_non_command_user_turn_projects_unchanged(tmp_path: Path, snapshot: object) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    _write_claude_transcript(
        transcript_path,
        [
            {
                "timestamp": "2026-01-01T00:00:01+00:00",
                "message": {
                    "role": "user",
                    "content": "Please inspect the current projection output.",
                },
            },
        ],
    )

    assert _projected_last_user_message(transcript_path) == snapshot


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD4")
async def test_discord_admin_reflection_preserves_user_attribution_for_text_input(snapshot: object) -> None:
    webhook = _DiscordWebhook()
    channel = _DiscordChannel(webhook)
    adapter = _DiscordMessageBoundary(channel)

    message_id = await adapter.send_message(_destination(), "hello from user", metadata=_reflection_metadata())

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
        await adapter.send_message(_destination(), "hello from user", metadata=_reflection_metadata())

    assert channel.bot_sends == []
    normal_channel = _DiscordChannel()
    normal_adapter = _DiscordMessageBoundary(normal_channel)

    message_id = await normal_adapter.send_message(
        _destination(),
        "hello from agent",
        metadata=MessageMetadata(parse_mode=None),
    )

    assert message_id
    assert len(normal_channel.bot_sends) == 1


class _VoiceIdentityResolver:
    registered_people_count = 1
    is_multi_user = False

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
    await db.create_session(
        computer_name="local",
        tmux_session_name="voice-session",
        last_input_origin=InputOrigin.DISCORD.value,
        title="unresolved voice session",
        session_id="session-voice-unresolved",
        emit_session_started=False,
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

    transcriptions = iter(["resolved transcription", "anonymous transcription", "unresolved transcription"])

    async def transcribe_voice_with_retry(
        audio_file_path: str,
        language: str | None = None,
    ) -> tuple[str | None, str | None]:
        del audio_file_path, language
        return next(transcriptions), None

    monkeypatch.setattr(voice_message_handler, "db", db)
    monkeypatch.setattr(output_mod, "db", db)
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
    unresolved_audio = tmp_path / "unresolved.ogg"
    unresolved_audio.write_bytes(b"audio")

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
        await voice_message_handler.handle_voice(
            session_id="session-voice-unresolved",
            audio_path=str(unresolved_audio),
            context=VoiceEventContext(
                session_id="session-voice-unresolved",
                file_path=str(unresolved_audio),
                origin=InputOrigin.DISCORD.value,
                notice_message_id="notice-unresolved",
            ),
            send_message=send_message,
            edit_message=edit_message,
            delete_message=delete_message,
        )

        assert len(sent_messages) == 2
        assert len(edited_messages) == 3

        route_webhook = _DiscordWebhook()
        route_channel = _DiscordChannel(route_webhook)
        runtime = AdapterRuntime()
        runtime.register_adapter(InputOrigin.DISCORD.value, _DiscordUiBoundary(route_channel))

        async def ensure_ui_channels(
            session: Session,
            include_adapters: set[str] | None = None,
        ) -> Session:
            del include_adapters
            return session

        monkeypatch.setattr(runtime, "ensure_ui_channels", ensure_ui_channels)
        session = await db.get_session("session-voice")
        assert session is not None
        route_message_ids = [
            await runtime.send_message(session, message, metadata=metadata) for message, metadata in sent_messages
        ]
    finally:
        await db.close()

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
        "routed_message_ids": route_message_ids,
        "route_bot_send_count": len(route_channel.bot_sends),
        "route_webhook_sends": route_webhook.sends,
        "deleted_messages": deleted_messages,
    } == snapshot


_TMUX_UNAVAILABLE_TEST_PANE_TEXT = "hello world"


class _FakeTmuxProcess:
    """Minimal stand-in for asyncio.subprocess.Process, as consumed by communicate_with_timeout."""

    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self.pid = 4242
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, input_data: bytes | None = None) -> tuple[bytes, bytes]:
        del input_data
        return self._stdout, self._stderr


@pytest.mark.spec("project/spec/feature/agent_runtime/output-polling-and-delivery", "UC-OPD7")
async def test_transient_tmux_binary_unavailability_skips_tick_and_resumes_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_config.polling, "output_cadence_s", 0.05)

    fail_ticks = 2
    call_count = 0

    async def fake_create_subprocess_exec(*cmd: object, **kwargs: object) -> _FakeTmuxProcess:
        del cmd, kwargs
        nonlocal call_count
        call_count += 1
        if call_count <= fail_ticks:
            return _FakeTmuxProcess(127, b"", b"exec: tmux: No such file or directory\n")
        stdout = f"{_TMUX_UNAVAILABLE_TEST_PANE_TEXT}\n{tmux_pane_mod._SNAPSHOT_MARKER}\n0\n".encode()
        return _FakeTmuxProcess(0, stdout, b"")

    monkeypatch.setattr(tmux_pane_mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    poller = OutputPoller()
    events = poller.poll("session-tmux-unavailable", "tmux-unavailable-session")
    try:
        first_event = await asyncio.wait_for(events.__anext__(), timeout=5.0)
    finally:
        await events.aclose()

    assert isinstance(first_event, OutputChanged)
    assert first_event.output.strip()
    assert call_count == fail_ticks + 1


async def _async_true(*args: object, **kwargs: object) -> bool:
    del args, kwargs
    return True
