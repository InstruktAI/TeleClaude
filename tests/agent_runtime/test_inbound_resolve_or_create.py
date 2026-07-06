"""Functional tests for the shared `core/inbound` resolve-or-create seam.

Drives the Telegram private path and the Discord guild path through their real
adapter-handler entry points, proving the seam's explicit `is_new` return
replaces the delivery-skip role the removed Discord `:509` `initializing`-guard
once played: a just-created session's bundled first message is not delivered a
second time, and a subsequent message to an existing session is. The Discord DM
path's equivalent is_new-gate coverage lives in
`tests/integration/test_discord_dm_personal_assistant_routing.py`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import cast

import pytest

from teleclaude.adapters.discord import gateway_handlers as gateway_handlers_mod
from teleclaude.adapters.discord import input_handlers as input_handlers_mod
from teleclaude.adapters.discord.gateway_handlers import GatewayHandlersMixin
from teleclaude.adapters.discord.input_handlers import InputHandlersMixin
from teleclaude.adapters.telegram import private_handlers
from teleclaude.adapters.telegram.private_handlers import PrivateHandlersMixin
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import DiscordAdapterMetadata, MessageMetadata, Session
from teleclaude.types.commands import (
    CreateSessionCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    ProcessMessageCommand,
)

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_FIRST_MESSAGE_TEXT = "hello"
_SECOND_MESSAGE_TEXT = "again"
_MEMBER_ROLE = "member"
_ATTACHMENT_FILENAME = "notes.txt"


# =========================================================================
# Telegram private path
# =========================================================================


@dataclass
class _FakeTelegramDb:
    sessions: dict[str, Session] = field(default_factory=dict)

    async def list_sessions(self, last_input_origin: str | None = None, include_closed: bool = False) -> list[Session]:
        del last_input_origin, include_closed
        return list(self.sessions.values())

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)


class _TelegramCommandService:
    def __init__(self, db: _FakeTelegramDb) -> None:
        self._db = db
        self.create_calls: list[CreateSessionCommand] = []
        self.process_calls: list[ProcessMessageCommand] = []

    async def create_session(self, command: CreateSessionCommand) -> dict[str, str]:
        self.create_calls.append(command)
        session_id = f"tg-session-{len(self.create_calls)}"
        origin_section = dict(command.origin_metadata or {})
        session = Session(
            session_id=session_id,
            computer_name="local",
            tmux_session_name=session_id,
            title="Personal assistant",
            origin_metadata={"telegram": origin_section},
        )
        self._db.sessions[session_id] = session
        return {"session_id": session_id}

    async def process_message(self, command: ProcessMessageCommand) -> None:
        self.process_calls.append(command)


class _StaticIdentityResolver:
    def __init__(self, identity: IdentityContext) -> None:
        self._identity = identity

    def resolve(self, origin: str, origin_metadata: object) -> IdentityContext:
        del origin, origin_metadata
        return self._identity


class _TelegramInboundHarness(PrivateHandlersMixin):
    @staticmethod
    def _metadata(**kwargs: object) -> MessageMetadata:
        return MessageMetadata(**kwargs)

    async def _dispatch_command(
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # guard: loose-dict - command payload echoed to the fake dispatcher
        handler: object,
    ) -> object:
        del session, message_id, metadata, command_name, payload
        if not callable(handler):
            raise AssertionError("dispatch handler must be callable")
        return await handler()


def _telegram_update(user_id: int, text: str, message_id: int) -> object:
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_message=SimpleNamespace(message_id=message_id, text=text),
    )


async def test_telegram_private_first_message_bundles_second_dispatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    fake_db = _FakeTelegramDb()
    service = _TelegramCommandService(fake_db)
    identity = IdentityContext(person_name="Riley", person_slug="riley", person_role=_MEMBER_ROLE)

    monkeypatch.setattr(private_handlers, "db", fake_db)
    monkeypatch.setattr(private_handlers, "get_command_service", lambda: service)
    monkeypatch.setattr(
        private_handlers.identity_module, "get_identity_resolver", lambda: _StaticIdentityResolver(identity)
    )
    monkeypatch.setattr(private_handlers.invite_module, "scaffold_personal_workspace", lambda _slug, _name: tmp_path)
    monkeypatch.setattr(private_handlers.agents_module, "get_default_agent", lambda: "claude")

    harness = _TelegramInboundHarness()
    user_id = 555

    await harness._handle_private_text(_telegram_update(user_id, _FIRST_MESSAGE_TEXT, 100), SimpleNamespace())

    # First message bundles into the launch intent — no separate process_message delivery.
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input == _FIRST_MESSAGE_TEXT
    assert len(service.process_calls) == 0

    await harness._handle_private_text(_telegram_update(user_id, _SECOND_MESSAGE_TEXT, 101), SimpleNamespace())

    # The existing session is reused — no second create — and this message is dispatched.
    assert len(service.create_calls) == 1
    assert len(service.process_calls) == 1
    assert service.process_calls[0].text == _SECOND_MESSAGE_TEXT


# =========================================================================
# Discord guild path
# =========================================================================


@dataclass
class _FakeDiscordDb:
    sessions: dict[str, Session] = field(default_factory=dict)

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def get_sessions_by_origin_metadata(
        self,
        adapter_type: str,
        metadata_key: str,
        metadata_value: object,
        include_closed: bool = False,
    ) -> list[Session]:
        del include_closed
        return [
            session
            for session in self.sessions.values()
            if session.get_origin_section(adapter_type).get(metadata_key) == metadata_value
        ]

    async def update_origin_metadata(
        self,
        session_id: str,
        platform: str,
        section_updates: dict[str, object],  # guard: loose-dict - Per-platform JSON section
    ) -> None:
        session = self.sessions[session_id]
        section = dict(session.get_origin_section(platform))
        section.update(section_updates)
        origin_metadata = dict(session.origin_metadata)
        origin_metadata[platform] = section
        self.sessions[session_id] = replace(session, origin_metadata=origin_metadata)

    async def update_session(self, session_id: str, **fields: object) -> None:
        session = self.sessions[session_id]
        self.sessions[session_id] = replace(session, **fields)


class _DiscordCommandService:
    def __init__(self, db: _FakeDiscordDb) -> None:
        self._db = db
        self.create_calls: list[CreateSessionCommand] = []
        self.process_calls: list[ProcessMessageCommand] = []
        self.voice_calls: list[HandleVoiceCommand] = []
        self.file_calls: list[HandleFileCommand] = []

    async def create_session(self, command: CreateSessionCommand) -> dict[str, str]:
        self.create_calls.append(command)
        session_id = f"discord-guild-session-{len(self.create_calls)}"
        origin_section = dict(command.origin_metadata or {})
        session = Session(
            session_id=session_id,
            computer_name="local",
            tmux_session_name=session_id,
            title="Project thread",
            origin_metadata={"discord": origin_section},
        )
        self._db.sessions[session_id] = session
        return {"session_id": session_id}

    async def process_message(self, command: ProcessMessageCommand) -> None:
        self.process_calls.append(command)

    async def handle_voice(self, command: HandleVoiceCommand) -> None:
        self.voice_calls.append(command)

    async def handle_file(self, command: HandleFileCommand) -> None:
        self.file_calls.append(command)


class _FakeTaskRegistry:
    def __init__(self) -> None:
        self.spawned: list[asyncio.Task[object]] = []

    def spawn(self, coro: Awaitable[object], *, name: str) -> asyncio.Task[object]:
        del name
        task = asyncio.ensure_future(coro)
        self.spawned.append(task)
        return task


class _DiscordGuildHarness(GatewayHandlersMixin, InputHandlersMixin):
    def __init__(self, *, project_path: str) -> None:
        self._client = object()
        self._discord = object()
        self._guild_id: int | None = None
        self._escalation_channel_id: int | None = None
        self._help_desk_channel_id: int | None = None
        self._team_channel_map: dict[int, str] = {}
        self._project_forum_map: dict[str, int] = {}
        self._all_sessions_channel_id: int | None = None
        self._project_path = project_path
        self.task_registry = _FakeTaskRegistry()

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        return int(text) if text.lstrip("-").isdigit() else None

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        if not callable(fn):
            raise AssertionError(f"{label} is not callable")
        return cast("Callable[..., Awaitable[object]]", fn)

    @staticmethod
    def _is_customer_session(session: Session) -> bool:
        del session
        return False

    async def _forward_to_relay_thread(self, session: object, text: str, message: object) -> None:
        del session, text, message
        raise AssertionError("relay diversion should not trigger in this test")

    def _resolve_forum_context(self, message: object) -> tuple[str, str | None]:
        del message
        return "project", self._project_path

    def _resolve_project_from_forum(self, forum_id: int) -> str | None:
        del forum_id
        return self._project_path

    @staticmethod
    def _discord_actor_name(author: object, user_id: str) -> str:
        del author
        return f"discord:{user_id}"

    @staticmethod
    def _discord_actor_avatar_url(author: object) -> str | None:
        del author
        return None

    @staticmethod
    def _metadata(**kwargs: object) -> MessageMetadata:
        return MessageMetadata(**kwargs)

    async def _dispatch_command(
        self,
        session: Session,
        message_id: str | None,
        metadata: MessageMetadata,
        command_name: str,
        payload: dict[str, object],  # guard: loose-dict - command payload echoed to the fake dispatcher
        handler: object,
    ) -> object:
        del session, message_id, metadata, command_name, payload
        if not callable(handler):
            raise AssertionError("dispatch handler must be callable")
        return await handler()


@dataclass(frozen=True, slots=True)
class _GuildAuthor:
    id: int
    bot: bool = False


class _GuildChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id


@dataclass(frozen=True, slots=True)
class _GuildRef:
    id: int


@dataclass(frozen=True, slots=True)
class _GuildMessage:
    author: _GuildAuthor
    channel: _GuildChannel
    guild: _GuildRef
    content: str
    id: int = 1


def _install_discord_fakes(
    monkeypatch: pytest.MonkeyPatch, *, identity: IdentityContext
) -> tuple[_FakeDiscordDb, _DiscordCommandService]:
    fake_db = _FakeDiscordDb()
    service = _DiscordCommandService(fake_db)
    for mod in (gateway_handlers_mod, input_handlers_mod):
        monkeypatch.setattr(mod, "db", fake_db)
        monkeypatch.setattr(mod, "get_command_service", lambda: service)
        monkeypatch.setattr(mod, "get_identity_resolver", lambda: _StaticIdentityResolver(identity))
    monkeypatch.setattr(input_handlers_mod, "get_default_agent", lambda: "claude")
    return fake_db, service


async def test_discord_guild_message_reuses_existing_session_and_backfills_human_role(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name="Alex", person_slug="alex", person_role=_MEMBER_ROLE)
    fake_db, service = _install_discord_fakes(monkeypatch, identity=identity)

    user_id = "222"
    channel_id = 4242
    existing_session = Session(
        session_id="existing-thread-session",
        computer_name="local",
        tmux_session_name="existing-thread-session",
        title="Project thread",
        origin_metadata={"discord": {"user_id": user_id, "channel_id": channel_id, "guild_id": None}},
    )
    fake_db.sessions[existing_session.session_id] = existing_session

    harness = _DiscordGuildHarness(project_path=str(tmp_path))
    message = _GuildMessage(
        author=_GuildAuthor(id=int(user_id)),
        channel=_GuildChannel(channel_id),
        guild=_GuildRef(id=42),
        content=_SECOND_MESSAGE_TEXT,
    )

    await harness._handle_on_message(message)

    assert len(service.create_calls) == 0
    assert len(service.process_calls) == 1
    assert service.process_calls[0].session_id == existing_session.session_id

    resolved = fake_db.sessions[existing_session.session_id]
    assert resolved.human_role == _MEMBER_ROLE
    discord_meta = DiscordAdapterMetadata.from_dict(resolved.get_origin_section("discord"))
    assert discord_meta.guild_id == 42


async def test_discord_guild_message_creates_session_and_skips_bundled_delivery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name="Alex", person_slug="alex", person_role=_MEMBER_ROLE)
    _fake_db, service = _install_discord_fakes(monkeypatch, identity=identity)

    harness = _DiscordGuildHarness(project_path=str(tmp_path))
    message = _GuildMessage(
        author=_GuildAuthor(id=333),
        channel=_GuildChannel(9999),
        guild=_GuildRef(id=42),
        content=_FIRST_MESSAGE_TEXT,
    )

    await harness._handle_on_message(message)

    # A newly created session bundles the first message into the launch intent —
    # no separate process_message delivery.
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input == _FIRST_MESSAGE_TEXT
    assert len(service.process_calls) == 0


# =========================================================================
# Discord attachment paths (voice / file) — no-first-message resolve-or-create
# =========================================================================


@dataclass(frozen=True, slots=True)
class _VoiceAttachment:
    filename: str
    duration: float | None
    content_type: str = "audio/ogg"

    async def save(self, path: object) -> None:
        del path


@dataclass(frozen=True, slots=True)
class _FileAttachment:
    filename: str
    content_type: str = "application/octet-stream"

    async def save(self, path: object) -> None:
        del path


async def test_discord_voice_attachment_resolves_session_and_dispatches_handle_voice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name="Alex", person_slug="alex", person_role=_MEMBER_ROLE)
    fake_db, service = _install_discord_fakes(monkeypatch, identity=identity)

    harness = _DiscordGuildHarness(project_path=str(tmp_path))
    message = _GuildMessage(
        author=_GuildAuthor(id=444),
        channel=_GuildChannel(7777),
        guild=_GuildRef(id=42),
        content="",
    )
    attachment = _VoiceAttachment(filename="voice.ogg", duration=3.5)

    await harness._handle_voice_attachment(message, attachment)
    await asyncio.gather(*harness.task_registry.spawned)

    # No first message — the seam creates a plain AGENT-intent session (no bundling).
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input is None
    assert len(service.voice_calls) == 1
    created_session_id = next(iter(fake_db.sessions))
    assert service.voice_calls[0].session_id == created_session_id


async def test_discord_file_attachment_resolves_session_and_dispatches_handle_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name="Alex", person_slug="alex", person_role=_MEMBER_ROLE)
    fake_db, service = _install_discord_fakes(monkeypatch, identity=identity)
    monkeypatch.setattr(input_handlers_mod, "get_session_output_dir", lambda _session_id: tmp_path)

    harness = _DiscordGuildHarness(project_path=str(tmp_path))
    message = _GuildMessage(
        author=_GuildAuthor(id=555),
        channel=_GuildChannel(8888),
        guild=_GuildRef(id=42),
        content="",
    )
    attachment = _FileAttachment(filename=_ATTACHMENT_FILENAME)

    await harness._handle_file_attachments(message, [attachment])

    # No first message — the seam creates a plain AGENT-intent session (no bundling).
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input is None
    assert len(service.file_calls) == 1
    created_session_id = next(iter(fake_db.sessions))
    assert service.file_calls[0].session_id == created_session_id
    assert service.file_calls[0].filename == _ATTACHMENT_FILENAME
