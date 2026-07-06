"""Functional bindings for Discord DM personal-assistant routing.

Binds the three use cases of
``project/spec/feature/integration/discord-dm-personal-assistant-routing`` to the
current DM handling in ``teleclaude.adapters.discord.gateway_handlers`` (inbound
session scoping/binding) and ``teleclaude.adapters.discord.channel_ops`` (outbound
delivery).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest

import teleclaude.adapters.discord.gateway_handlers as gateway_handlers_mod
from teleclaude.adapters.discord.channel_ops import ChannelOperationsMixin
from teleclaude.adapters.discord.gateway_handlers import GatewayHandlersMixin
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import ChannelMetadata, DiscordAdapterMetadata, MessageMetadata, Session
from teleclaude.types.commands import CreateSessionCommand, ProcessMessageCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/integration/discord-dm-personal-assistant-routing"

_BOUND_USER_ID = "111"
_BOUND_PERSON_SLUG = "alex"
_BOUND_PERSON_NAME = "Alex"
_FIRST_MESSAGE_TEXT = "hello"
_SECOND_MESSAGE_TEXT = "again"


@dataclass
class _FakeDb:
    sessions: dict[str, Session] = field(default_factory=dict)

    async def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    async def list_sessions(self, last_input_origin: str | None = None, include_closed: bool = False) -> list[Session]:
        del last_input_origin, include_closed
        return list(self.sessions.values())

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


class _CommandService:
    def __init__(self, db: _FakeDb) -> None:
        self._db = db
        self.create_calls: list[CreateSessionCommand] = []
        self.process_calls: list[ProcessMessageCommand] = []

    async def create_session(self, command: CreateSessionCommand) -> dict[str, str]:
        self.create_calls.append(command)
        session_id = f"session-{len(self.create_calls)}"
        origin_section = dict(command.origin_metadata or {})
        session = Session(
            session_id=session_id,
            computer_name="local",
            tmux_session_name=session_id,
            title="Personal assistant",
            origin_metadata={"discord": origin_section},
        )
        self._db.sessions[session_id] = session
        return {"session_id": session_id}

    async def process_message(self, command: ProcessMessageCommand) -> None:
        self.process_calls.append(command)


class _IdentityResolver:
    def __init__(self, identity: IdentityContext) -> None:
        self._identity = identity

    def resolve(self, origin: str, origin_metadata: object) -> IdentityContext:
        del origin, origin_metadata
        return self._identity


@dataclass(frozen=True, slots=True)
class _Author:
    id: int


class _Channel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass(frozen=True, slots=True)
class _Message:
    author: _Author
    channel: _Channel
    content: str
    id: int = 1


class _DmHandlingHarness(GatewayHandlersMixin):
    """Minimal host for the DM inbound-routing methods under test."""

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        return int(text) if text.lstrip("-").isdigit() else None

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


def _existing_guild_session(session_id: str, *, user_id: str, guild_id: int, channel_id: int) -> Session:
    """A session already bound to a guild channel (project forum thread) for the same user."""
    return Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=session_id,
        title="Project thread",
        origin_metadata={
            "discord": {
                "user_id": user_id,
                "guild_id": guild_id,
                "channel_id": channel_id,
                "thread_id": channel_id + 1,
            }
        },
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch, *, identity: IdentityContext, workspace_path: object
) -> tuple[_FakeDb, _CommandService]:
    fake_db = _FakeDb()
    service = _CommandService(fake_db)
    monkeypatch.setattr(gateway_handlers_mod, "db", fake_db)
    monkeypatch.setattr(gateway_handlers_mod, "get_command_service", lambda: service)
    monkeypatch.setattr(gateway_handlers_mod, "get_identity_resolver", lambda: _IdentityResolver(identity))
    monkeypatch.setattr(gateway_handlers_mod, "scaffold_personal_workspace", lambda _slug, _name: workspace_path)
    monkeypatch.setattr(gateway_handlers_mod, "get_default_agent", lambda: "claude")
    return fake_db, service


@pytest.mark.spec(_SPEC, "UC-DM-SCOPED-RESOLUTION")
async def test_dm_resolves_to_dm_scoped_session_not_guild_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name=_BOUND_PERSON_NAME, person_slug=_BOUND_PERSON_SLUG, person_role="member")
    fake_db, service = _install_fakes(monkeypatch, identity=identity, workspace_path=tmp_path)

    guild_session = _existing_guild_session("guild-session", user_id=_BOUND_USER_ID, guild_id=777, channel_id=555)
    fake_db.sessions[guild_session.session_id] = guild_session

    harness = _DmHandlingHarness()
    dm_channel = _Channel(999)
    message = _Message(author=_Author(id=int(_BOUND_USER_ID)), channel=dm_channel, content=_FIRST_MESSAGE_TEXT)

    await harness._handle_discord_dm(message)

    # A newly created session bundles the first message into the launch intent
    # (agent_then_message) rather than a separate process_message delivery.
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input == _FIRST_MESSAGE_TEXT
    assert len(service.process_calls) == 0

    resolved_session_id = next(sid for sid in fake_db.sessions if sid != guild_session.session_id)
    resolved_session = fake_db.sessions[resolved_session_id]
    discord_meta = DiscordAdapterMetadata.from_dict(resolved_session.get_origin_section("discord"))
    assert discord_meta.channel_id == 999
    assert discord_meta.guild_id is None


@pytest.mark.spec(_SPEC, "UC-DM-SESSION-CREATE-AND-REUSE")
async def test_first_dm_creates_bound_session_second_dm_reuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    identity = IdentityContext(person_name=_BOUND_PERSON_NAME, person_slug=_BOUND_PERSON_SLUG, person_role="member")
    fake_db, service = _install_fakes(monkeypatch, identity=identity, workspace_path=tmp_path)

    harness = _DmHandlingHarness()
    dm_channel = _Channel(999)

    first_message = _Message(author=_Author(id=int(_BOUND_USER_ID)), channel=dm_channel, content=_FIRST_MESSAGE_TEXT)
    await harness._handle_discord_dm(first_message)

    # The first message bundles into the launch intent (agent_then_message) —
    # no separate process_message delivery for the just-created session.
    assert len(service.create_calls) == 1
    assert service.create_calls[0].initial_input == _FIRST_MESSAGE_TEXT
    assert len(service.process_calls) == 0
    first_session_id = next(iter(fake_db.sessions))
    created_session = fake_db.sessions[first_session_id]
    discord_meta = DiscordAdapterMetadata.from_dict(created_session.get_origin_section("discord"))
    assert discord_meta.channel_id == 999
    assert discord_meta.guild_id is None

    second_message = _Message(author=_Author(id=int(_BOUND_USER_ID)), channel=dm_channel, content=_SECOND_MESSAGE_TEXT)
    await harness._handle_discord_dm(second_message)

    # The existing session is reused — no second create — and this message
    # (not bundled) is delivered via process_message.
    assert len(service.create_calls) == 1
    assert len(service.process_calls) == 1
    assert service.process_calls[0].session_id == first_session_id
    assert service.process_calls[0].text == _SECOND_MESSAGE_TEXT


class _ChannelDeliveryHarness(ChannelOperationsMixin):
    """Minimal host for create_channel with a catch-all forum configured.

    ``_all_sessions_channel_id`` mirrors a real deployment (a catch-all forum is
    configured) so the test proves the DM session is never routed there.
    """

    def __init__(self) -> None:
        self._client = object()
        self._team_channel_map: dict[int, str] = {}
        self._help_desk_channel_id: int | None = None
        self._all_sessions_channel_id: int | None = 42
        self._project_forum_map: dict[str, int] = {}
        self.get_channel_calls: list[int] = []

    async def _get_channel(self, channel_id: int) -> object | None:
        self.get_channel_calls.append(channel_id)
        raise AssertionError("DM session must not resolve a forum channel")


@pytest.mark.spec(_SPEC, "UC-DM-REPLY-DELIVERY")
async def test_dm_session_output_delivers_to_dm_channel_not_a_forum() -> None:
    dm_channel_id = 999
    session = Session(
        session_id="dm-session",
        computer_name="local",
        tmux_session_name="dm-session",
        title="Personal assistant",
        origin_metadata={
            "discord": {
                "user_id": _BOUND_USER_ID,
                "channel_id": dm_channel_id,
            }
        },
    )
    harness = _ChannelDeliveryHarness()

    destination = await harness.create_channel(session, "title", ChannelMetadata())

    assert destination == str(dm_channel_id)
    assert harness.get_channel_calls == []
