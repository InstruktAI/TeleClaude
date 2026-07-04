"""Functional regressions for Discord launcher routing and reconciliation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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

BOT_USER_ID = 999


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
    def __init__(self, *, status: int | None = None, code: int | None = None) -> None:
        self.status = status
        self.code = code
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
    def __init__(self, *, bot_user_id: int = BOT_USER_ID) -> None:
        self.registered_views: list[tuple[object, int | None]] = []
        self.user = _User(id=bot_user_id)

    def add_view(self, view: object, *, message_id: int | None = None) -> None:
        self.registered_views.append((view, message_id))


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


# =============================================================================
# Launcher reconciliation (`_post_or_update_launcher`)
# =============================================================================


@dataclass(frozen=True, slots=True)
class _Button:
    custom_id: str


@dataclass(frozen=True, slots=True)
class _ActionRow:
    children: list[object]


@dataclass(frozen=True, slots=True)
class _ThreadFlags:
    pinned: bool = False


class _LauncherMessage:
    def __init__(
        self,
        message_id: int,
        *,
        author_id: int = BOT_USER_ID,
        marker: str | None = "launch:codex",
        edit_error: Exception | None = None,
    ) -> None:
        self.id = message_id
        self.author = _User(id=author_id)
        self.components = [_ActionRow(children=[_Button(custom_id=marker)])] if marker else []
        self.edit_error = edit_error
        self.edits: list[tuple[str, object]] = []
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
        message: _LauncherMessage | None,
        fetch_error: Exception | None = None,
        delete_error: Exception | None = None,
        pinned: bool = False,
    ) -> None:
        self.id = thread_id
        self.message = message
        self.fetch_error = fetch_error
        self.delete_error = delete_error
        self.flags = _ThreadFlags(pinned=pinned)
        self.deleted = False
        self.pin_edits: list[bool] = []

    async def fetch_message(self, message_id: int) -> _LauncherMessage:
        if self.fetch_error is not None:
            raise self.fetch_error
        assert message_id == self.id
        if self.message is None:
            raise _DiscordException(status=404)
        return self.message

    async def delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True

    async def edit(self, *, pinned: bool) -> None:
        self.pin_edits.append(pinned)
        self.flags = _ThreadFlags(pinned=pinned)


class _ForumChannel:
    is_forum = True

    def __init__(
        self,
        forum_id: int,
        *,
        threads: list[_LauncherThread] | None = None,
        archived: list[_LauncherThread] | None = None,
        archived_error: Exception | None = None,
    ) -> None:
        self.id = forum_id
        self.threads = list(threads or [])
        self._archived = list(archived or [])
        self._archived_error = archived_error
        self.created_threads: list[_LauncherThread] = []
        self.created_messages: list[_LauncherMessage] = []
        self.created_views: list[object] = []

    def archived_threads(self, *, limit: int) -> AsyncIterator[object]:
        del limit
        return self._iter_archived()

    async def _iter_archived(self) -> AsyncIterator[object]:
        if self._archived_error is not None:
            raise self._archived_error
        for thread in self._archived:
            yield thread

    async def create_thread(self, *, name: str, content: str, view: object) -> _CreateThreadResult:
        del name, content
        thread_id = 1000 + len(self.created_threads)
        message = _LauncherMessage(2000 + len(self.created_messages))
        thread = _LauncherThread(thread_id, message=message)
        self.created_threads.append(thread)
        self.created_messages.append(message)
        self.created_views.append(view)
        return _CreateThreadResult(thread=thread, message=message)


class _LauncherProvisioningHarness(InfrastructureMixin):
    def __init__(
        self,
        *,
        forum: _ForumChannel,
        client: _Client | None = None,
        help_desk_channel_id: int | None = None,
        is_master: bool = True,
    ) -> None:
        self._client = client or _Client()
        self._discord = _DiscordModule()
        self._forum_project_map = {}
        self._project_forum_map = {}
        self._channels = {forum.id: forum}
        self._multi_agent_value = True
        self._launcher_registration_view = None
        self._help_desk_channel_id = help_desk_channel_id
        infra_mod.config.computer.is_master = is_master

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


def _launcher_settings(forum_id: int, *, thread_id: int, message_id: int) -> dict[str, str]:
    setting_prefix = f"discord_launcher:{forum_id}"
    return {
        f"{setting_prefix}:thread_id": str(thread_id),
        f"{setting_prefix}:message_id": str(message_id),
        setting_prefix: str(message_id),
    }


async def test_converges_multiple_launchers_to_one_survivor_and_leaves_session_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stale_launcher = _LauncherThread(21, message=_LauncherMessage(31))
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32), pinned=True)
    session_thread = _LauncherThread(23, message=_LauncherMessage(33, marker=None))
    forum = _ForumChannel(forum_id, threads=[stale_launcher, live_launcher, session_thread])
    settings_db = _SettingsDb()
    client = _Client()
    harness = _LauncherProvisioningHarness(forum=forum, client=client)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert stale_launcher.deleted is True
    assert live_launcher.deleted is False
    assert session_thread.deleted is False
    assert live_launcher.flags.pinned is True
    assert not forum.created_threads
    live_message = live_launcher.message
    assert live_message is not None
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(live_launcher.id)
    assert settings_db.settings[f"discord_launcher:{forum_id}:message_id"] == str(live_message.id)
    assert client.registered_views[-1][1] == live_message.id


async def test_adopts_existing_launcher_when_record_is_stale_or_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32))
    forum = _ForumChannel(forum_id, threads=[live_launcher])
    settings_db = _SettingsDb(_launcher_settings(forum_id, thread_id=999, message_id=999))
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert live_launcher.deleted is False
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(live_launcher.id)


async def test_never_deletes_non_launcher_bot_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    forum_id = 11
    non_launcher_bot_thread = _LauncherThread(22, message=_LauncherMessage(32, marker=None))
    forum = _ForumChannel(forum_id, threads=[non_launcher_bot_thread])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert non_launcher_bot_thread.deleted is False
    assert len(forum.created_threads) == 1


async def test_creates_and_pins_launcher_when_none_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    forum_id = 11
    forum = _ForumChannel(forum_id, threads=[])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert len(forum.created_threads) == 1
    created_thread = forum.created_threads[0]
    assert created_thread.pin_edits == [True]
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(created_thread.id)


async def test_leaves_survivor_unpinned_when_human_pinned_thread_holds_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32))
    forum = _ForumChannel(forum_id, threads=[live_launcher])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    async def _reject_pin(*, pinned: bool) -> None:
        del pinned
        raise _DiscordException(code=30047)

    monkeypatch.setattr(live_launcher, "edit", _reject_pin)
    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert live_launcher.flags.pinned is False
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(live_launcher.id)


async def test_skips_shared_help_desk_forum_on_non_master_computer(monkeypatch: pytest.MonkeyPatch) -> None:
    forum_id = 11
    forum = _ForumChannel(forum_id, threads=[])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum, help_desk_channel_id=forum_id, is_master=False)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert settings_db.settings == {}


async def test_second_run_is_idempotent_no_creates_no_deletes(monkeypatch: pytest.MonkeyPatch) -> None:
    forum_id = 11
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32))
    forum = _ForumChannel(forum_id, threads=[live_launcher])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)
    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert live_launcher.deleted is False


async def test_inconclusive_starter_message_fetch_skips_forum_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    unresolvable_thread = _LauncherThread(22, message=None, fetch_error=TimeoutError())
    forum = _ForumChannel(forum_id, threads=[unresolvable_thread])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert unresolvable_thread.deleted is False
    assert settings_db.settings == {}


async def test_archived_thread_fetch_failure_skips_forum_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    forum_id = 11
    forum = _ForumChannel(forum_id, threads=[], archived_error=TimeoutError())
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert settings_db.settings == {}


async def test_stale_launcher_delete_failure_is_logged_and_reconciliation_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    stale_launcher = _LauncherThread(21, message=_LauncherMessage(31), delete_error=TimeoutError())
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32), pinned=True)
    forum = _ForumChannel(forum_id, threads=[stale_launcher, live_launcher])
    settings_db = _SettingsDb()
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert stale_launcher.deleted is False
    assert settings_db.settings[f"discord_launcher:{forum_id}:thread_id"] == str(live_launcher.id)


async def test_survivor_edit_failure_is_logged_and_preserves_prior_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forum_id = 11
    live_launcher = _LauncherThread(22, message=_LauncherMessage(32, edit_error=TimeoutError()))
    forum = _ForumChannel(forum_id, threads=[live_launcher])
    initial_settings = _launcher_settings(forum_id, thread_id=22, message_id=32)
    settings_db = _SettingsDb(initial_settings)
    harness = _LauncherProvisioningHarness(forum=forum)

    monkeypatch.setattr(infra_mod, "db", settings_db)

    await harness._post_or_update_launcher(forum_id)

    assert not forum.created_threads
    assert settings_db.settings == initial_settings
