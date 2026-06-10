"""Functional regressions for Discord launcher routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

import pytest

import teleclaude.adapters.discord.infra as infra_mod
import teleclaude.adapters.discord.input_handlers as input_handlers_mod
from teleclaude.adapters.discord.infra import InfrastructureMixin
from teleclaude.adapters.discord.input_handlers import InputHandlersMixin
from teleclaude.adapters.discord.session_launcher import SessionLauncherView
from teleclaude.core.agents import AgentName
from teleclaude.core.models import Session
from teleclaude.types.commands import CreateSessionCommand

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


@dataclass(frozen=True, slots=True)
class _ThreadChannel:
    id: int
    parent_id: int | None
    is_forum: bool = False


@dataclass(frozen=True, slots=True)
class _Message:
    channel: object | None


@dataclass(frozen=True, slots=True)
class _CreateThreadResult:
    thread: object
    message: object


@dataclass(frozen=True, slots=True)
class _User:
    id: int


class _DiscordException(Exception):
    def __init__(self, *, status: int | None = None) -> None:
        self.status = status
        super().__init__()


class _DiscordModule:
    DiscordException = _DiscordException


class _Response:
    async def defer(self, *, ephemeral: bool) -> None:
        self.ephemeral = ephemeral


class _Followup:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def send(self, message: object, *, ephemeral: bool) -> None:
        self.messages.append((message, ephemeral))


class _Interaction:
    def __init__(self, *, channel_id: int, message: _Message) -> None:
        self.channel = None
        self.channel_id = channel_id
        self.message = message
        self.user = _User(id=7)
        self.response = _Response()
        self.followup = _Followup()


class _CommandService:
    def __init__(self) -> None:
        self.commands: list[CreateSessionCommand] = []

    async def create_session(self, command: CreateSessionCommand) -> dict[str, str]:
        self.commands.append(command)
        return {"session_id": "session-from-launcher"}


class _LaunchRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, int | None]] = []

    async def __call__(self, interaction: object, agent_name: str, launcher_forum_id: int | None) -> None:
        self.calls.append((interaction, agent_name, launcher_forum_id))


class _Db:
    async def get_session(self, session_id: str) -> None:
        return None


class _SettingsDb:
    def __init__(self, settings: dict[str, str] | None = None) -> None:
        self.settings = dict(settings or {})

    async def get_system_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_system_setting(self, key: str, value: str) -> None:
        self.settings[key] = value


class _Client:
    def __init__(self) -> None:
        self.registered_views: list[tuple[object, int | None]] = []

    def add_view(self, view: object, *, message_id: int | None = None) -> None:
        self.registered_views.append((view, message_id))


class _LauncherMessage:
    def __init__(self, message_id: int, *, edit_error: Exception | None = None) -> None:
        self.id = message_id
        self.edit_error = edit_error
        self.edits: list[object] = []
        self.pinned = False

    async def edit(self, *, content: str, view: object) -> None:
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append((content, view))

    async def pin(self) -> None:
        self.pinned = True


class _LauncherThread:
    def __init__(
        self,
        thread_id: int,
        *,
        parent_id: int | None,
        message: _LauncherMessage | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.id = thread_id
        self.parent_id = parent_id
        self.message = message
        self.fetch_error = fetch_error
        self.fetched_message_ids: list[int] = []
        self.pinned = False

    async def fetch_message(self, message_id: int) -> _LauncherMessage:
        self.fetched_message_ids.append(message_id)
        if self.fetch_error is not None:
            raise self.fetch_error
        if self.message is None:
            raise _DiscordException(status=404)
        return self.message

    async def edit(self, *, pinned: bool) -> None:
        self.pinned = pinned


class _ForumChannel:
    is_forum = True

    def __init__(self, forum_id: int) -> None:
        self.id = forum_id
        self.created_threads: list[_LauncherThread] = []
        self.created_messages: list[_LauncherMessage] = []
        self.created_views: list[object] = []

    async def create_thread(self, *, name: str, content: str, view: object) -> _CreateThreadResult:
        del name, content
        thread = _LauncherThread(1000 + len(self.created_threads), parent_id=self.id)
        message = _LauncherMessage(2000 + len(self.created_messages))
        self.created_threads.append(thread)
        self.created_messages.append(message)
        self.created_views.append(view)
        return _CreateThreadResult(thread=thread, message=message)


class _LauncherHarness(InputHandlersMixin, InfrastructureMixin):
    def __init__(self, *, forum_id: int, project_path: str) -> None:
        self._forum_project_map = {forum_id: project_path}
        self._client = object()

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        return int(text) if text.isdigit() else None

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        return bool(getattr(channel, "is_forum", False))

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        del label
        return cast(Callable[..., Awaitable[object]], fn)

    async def _get_channel(self, channel_id: int) -> None:
        return None

    async def ensure_channel(self, session: Session) -> Session:
        return session


class _LauncherProvisioningHarness(InfrastructureMixin):
    def __init__(
        self,
        *,
        forum: _ForumChannel,
        channels: dict[int, object] | None = None,
        client: _Client | None = None,
    ) -> None:
        self._client = client or _Client()
        self._discord = _DiscordModule()
        self._forum_project_map = {}
        self._project_forum_map = {}
        self._channels = {forum.id: forum, **(channels or {})}
        self._multi_agent_value = True
        self._launcher_registration_view = None

    @staticmethod
    def _parse_optional_int(value: object) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        return int(text) if text.isdigit() else None

    @staticmethod
    def _is_forum_channel(channel: object) -> bool:
        return bool(getattr(channel, "is_forum", False))

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        del label
        return cast(Callable[..., Awaitable[object]], fn)

    def _get_enabled_agents(self) -> list[str]:
        return [AgentName.CODEX.value, AgentName.GEMINI.value]

    @property
    def _multi_agent(self) -> bool:
        return self._multi_agent_value

    async def _get_channel(self, channel_id: int) -> object | None:
        return self._channels.get(channel_id)

    async def _handle_launcher_click(
        self,
        interaction: object,
        agent_name: str,
        launcher_forum_id: int | None = None,
    ) -> None:
        del interaction, agent_name, launcher_forum_id


def _launcher_settings(
    forum_id: int,
    *,
    thread_id: int,
    message_id: int,
) -> dict[str, str]:
    setting_prefix = f"discord_launcher:{forum_id}"
    return {
        f"{setting_prefix}:thread_id": str(thread_id),
        f"{setting_prefix}:message_id": str(message_id),
        setting_prefix: str(message_id),
    }


async def test_launcher_view_passes_forum_context_to_callback() -> None:
    forum_id = 11
    interaction = object()
    recorder = _LaunchRecorder()
    view = SessionLauncherView(
        enabled_agents=[AgentName.CODEX.value],
        on_launch=recorder,
        launcher_forum_id=forum_id,
    )
    callback = cast(Callable[[object], Awaitable[None]], view.children[0].callback)

    await callback(interaction)

    assert recorder.calls == [(interaction, AgentName.CODEX.value, forum_id)]


async def test_launcher_click_resolves_project_from_component_message_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    launcher_thread_id = 22
    project_path = "/workspace/project"
    service = _CommandService()
    harness = _LauncherHarness(forum_id=forum_id, project_path=project_path)
    thread_channel = _ThreadChannel(id=launcher_thread_id, parent_id=forum_id)
    interaction = _Interaction(channel_id=launcher_thread_id, message=_Message(channel=thread_channel))

    monkeypatch.setattr(input_handlers_mod, "get_command_service", lambda: service)
    monkeypatch.setattr(input_handlers_mod, "db", _Db())

    await harness.handle_launcher_click(interaction, AgentName.CODEX.value)

    assert len(service.commands) == 1
    command = service.commands[0]
    assert command.project_path == project_path
    assert command.launch_intent is not None
    assert command.launch_intent.agent == AgentName.CODEX.value


async def test_launcher_click_uses_supplied_launcher_forum_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    launcher_thread_id = 22
    project_path = "/workspace/project"
    service = _CommandService()
    harness = _LauncherHarness(forum_id=forum_id, project_path=project_path)
    interaction = _Interaction(channel_id=launcher_thread_id, message=_Message(channel=None))

    monkeypatch.setattr(input_handlers_mod, "get_command_service", lambda: service)
    monkeypatch.setattr(input_handlers_mod, "db", _Db())

    await harness.handle_launcher_click(
        interaction,
        AgentName.GEMINI.value,
        launcher_forum_id=forum_id,
    )

    assert len(service.commands) == 1
    command = service.commands[0]
    assert command.project_path == project_path
    assert command.launch_intent is not None
    assert command.launch_intent.agent == AgentName.GEMINI.value


async def test_stale_launcher_thread_record_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stale_thread_id = 22
    stale_message_id = 33
    forum = _ForumChannel(forum_id)
    client = _Client()
    settings_db = _SettingsDb(_launcher_settings(forum_id, thread_id=stale_thread_id, message_id=stale_message_id))
    harness = _LauncherProvisioningHarness(forum=forum, client=client)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert len(forum.created_threads) == 1
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(forum.created_threads[0].id)
    assert settings_db.settings[f"discord_launcher:{forum_id}:message_id"] == str(forum.created_messages[0].id)
    assert client.registered_views[-1][1] == forum.created_messages[0].id


async def test_wrong_parent_launcher_thread_record_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stored_thread_id = 22
    stored_message_id = 33
    forum = _ForumChannel(forum_id)
    wrong_parent_thread = _LauncherThread(
        stored_thread_id,
        parent_id=99,
        message=_LauncherMessage(stored_message_id),
    )
    settings_db = _SettingsDb(_launcher_settings(forum_id, thread_id=stored_thread_id, message_id=stored_message_id))
    harness = _LauncherProvisioningHarness(forum=forum, channels={stored_thread_id: wrong_parent_thread})

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert len(forum.created_threads) == 1
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(forum.created_threads[0].id)
    assert settings_db.settings[f"discord_launcher:{forum_id}:message_id"] == str(forum.created_messages[0].id)


async def test_deleted_launcher_message_record_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stored_thread_id = 22
    stored_message_id = 33
    forum = _ForumChannel(forum_id)
    launcher_thread = _LauncherThread(
        stored_thread_id,
        parent_id=forum_id,
        fetch_error=_DiscordException(status=404),
    )
    settings_db = _SettingsDb(_launcher_settings(forum_id, thread_id=stored_thread_id, message_id=stored_message_id))
    harness = _LauncherProvisioningHarness(forum=forum, channels={stored_thread_id: launcher_thread})

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert len(forum.created_threads) == 1
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(forum.created_threads[0].id)
    assert settings_db.settings[f"discord_launcher:{forum_id}:message_id"] == str(forum.created_messages[0].id)


async def test_transient_launcher_update_failure_preserves_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stored_thread_id = 22
    stored_message_id = 33
    forum = _ForumChannel(forum_id)
    launcher_message = _LauncherMessage(stored_message_id, edit_error=TimeoutError())
    launcher_thread = _LauncherThread(stored_thread_id, parent_id=forum_id, message=launcher_message)
    initial_settings = _launcher_settings(forum_id, thread_id=stored_thread_id, message_id=stored_message_id)
    settings_db = _SettingsDb(initial_settings)
    harness = _LauncherProvisioningHarness(forum=forum, channels={stored_thread_id: launcher_thread})

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert settings_db.settings == initial_settings
