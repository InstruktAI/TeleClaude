from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.discord.input_handlers import InputHandlersMixin, _SessionCreationContext
from teleclaude.core.models import DiscordAdapterMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import HandleVoiceCommand

pytestmark = pytest.mark.unit


class ThreadChannel:
    def __init__(self, channel_id: str, parent_id: str | None) -> None:
        self.id = channel_id
        self.parent_id = parent_id
        self.parent = None if parent_id is None else SimpleNamespace(id=parent_id)


class PlainChannel:
    def __init__(self, channel_id: str) -> None:
        self.id = channel_id
        self.parent_id = None
        self.parent = None


class DummyInputHandlers(InputHandlersMixin):
    def __init__(self) -> None:
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )


class DummyRoutingHandlers(InputHandlersMixin):
    def __init__(self) -> None:
        self._client = object()
        self._parse_optional_int = lambda value: (
            int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
        )

    async def _get_channel(self, _channel_id: int) -> object | None:
        return None


class RecordingTaskRegistry:
    def __init__(self) -> None:
        self.spawned: list[tuple[Coroutine[object, object, object], str | None]] = []

    def spawn(self, coro: Coroutine[object, object, object], name: str | None = None) -> None:
        self.spawned.append((coro, name))
        coro.close()


class DummyVoiceHandlers(InputHandlersMixin):
    def __init__(self) -> None:
        self.task_registry = RecordingTaskRegistry()
        self._discord = SimpleNamespace()

    async def _resolve_or_create_session(self, _message: object, *, first_message: str | None = None) -> Session | None:
        del first_message
        return Session(session_id="sess-voice", computer_name="machine", tmux_session_name="tmux-voice", title="Voice")

    @staticmethod
    def _require_async_callable(fn: object, *, label: str) -> Callable[..., Awaitable[object]]:
        del label
        return cast("Callable[..., Awaitable[object]]", fn)

    @staticmethod
    def _discord_actor_name(_author: object, user_id: str) -> str:
        return user_id

    @staticmethod
    def _discord_actor_avatar_url(_author: object) -> str | None:
        return None


class _Metadata(TypedDict):
    user_id: str


def test_extract_audio_attachment_returns_first_audio_content_type() -> None:
    adapter = DummyInputHandlers()
    message = SimpleNamespace(
        attachments=[
            SimpleNamespace(filename="voice.mp3", content_type="audio/mpeg"),
            SimpleNamespace(filename="note.wav", content_type="audio/wav"),
        ]
    )

    attachment = adapter._extract_audio_attachment(message)

    assert attachment.filename == "voice.mp3"  # pyright: ignore[reportAttributeAccessIssue]


def test_extract_file_attachments_excludes_audio_but_keeps_unknown_content_types() -> None:
    adapter = DummyInputHandlers()
    message = SimpleNamespace(
        attachments=[
            SimpleNamespace(filename="voice.mp3", content_type="audio/mpeg"),
            SimpleNamespace(filename="report.txt", content_type="text/plain"),
            SimpleNamespace(filename="image.png", content_type=None),
        ]
    )

    attachments = adapter._extract_file_attachments(message)

    assert [attachment.filename for attachment in attachments] == ["report.txt", "image.png"]  # pyright: ignore[reportAttributeAccessIssue]


def test_is_thread_channel_uses_class_name_contains_thread() -> None:
    adapter = DummyInputHandlers()

    assert adapter._is_thread_channel(ThreadChannel("500", "100")) is True
    assert adapter._is_thread_channel(PlainChannel("600")) is False


def test_extract_channel_ids_uses_parent_for_threads_and_self_for_plain_channels() -> None:
    adapter = DummyInputHandlers()

    assert adapter._extract_channel_ids(SimpleNamespace(channel=ThreadChannel("500", "100"))) == (100, 500)
    assert adapter._extract_channel_ids(SimpleNamespace(channel=ThreadChannel("700", None))) == (700, 700)
    assert adapter._extract_channel_ids(SimpleNamespace(channel=PlainChannel("600"))) == (600, None)


@pytest.mark.asyncio
async def test_handle_voice_attachment_spawns_registry_task_without_awaiting_transcription() -> None:
    adapter = DummyVoiceHandlers()
    message_id = "12345"
    recorded_commands: list[HandleVoiceCommand] = []

    def handle_voice(cmd: HandleVoiceCommand) -> Coroutine[object, object, None]:
        recorded_commands.append(cmd)

        async def _blocked() -> None:
            await AsyncMock()()

        return _blocked()

    attachment = SimpleNamespace(filename="voice.ogg", save=AsyncMock())
    message = SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id="900"),
    )
    command_service = SimpleNamespace(handle_voice=handle_voice)

    with patch("teleclaude.adapters.discord.input_handlers.get_command_service", return_value=command_service):
        await adapter._handle_voice_attachment(message, attachment)

    assert len(adapter.task_registry.spawned) == 1
    assert adapter.task_registry.spawned[0][1] == f"voice-{message_id}"
    assert len(recorded_commands) == 1
    assert recorded_commands[0].origin == InputOrigin.DISCORD.value
    assert recorded_commands[0].message_id == message_id


def test_resolve_team_session_target_uses_discord_identity_and_scaffolded_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Identity:
        person_role = "member"
        person_name = "Alice"

    class Resolver:
        def resolve(self, origin: str, metadata: _Metadata) -> Identity:
            assert origin == "discord"
            assert metadata["user_id"] == "900"
            return Identity()

    def fake_scaffold(person_name: str) -> Path:
        assert person_name == "Alice"
        return Path("/tmp/alice-workspace")

    monkeypatch.setattr(
        "teleclaude.adapters.discord.input_handlers.get_identity_resolver",
        lambda: Resolver(),
    )
    monkeypatch.setattr("teleclaude.adapters.discord.input_handlers.scaffold_personal_workspace", fake_scaffold)

    adapter = DummyInputHandlers()
    message = SimpleNamespace(author=SimpleNamespace(id="900"))
    path, human_role = adapter._resolve_session_creation_target(
        message,
        _SessionCreationContext(forum_type="team", project_path="/tmp/legacy-folder"),
    )

    assert path == "/tmp/alice-workspace"
    assert human_role == "member"


@pytest.mark.asyncio
async def test_handle_launcher_click_provisions_discord_channel_after_session_creation() -> None:
    class LauncherHandlers(InputHandlersMixin):
        def __init__(self) -> None:
            self._parse_optional_int = lambda value: (
                int(str(value).strip()) if value is not None and str(value).strip().isdigit() else None
            )
            self.ensure_channel = AsyncMock(side_effect=lambda s: s)

        async def _resolve_interaction_forum_id(self, _interaction: object) -> int | None:
            return 42

        def _resolve_project_from_forum(self, _forum_id: int) -> str | None:
            return "/tmp/project"

        def _async_callable(self, fn, *, label):
            del label
            return fn

    adapter = LauncherHandlers()
    session = Session(
        session_id="sess-launcher",
        computer_name="machine",
        tmux_session_name="tmux-launcher",
        title="launcher",
    )
    interaction = SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id="999"),
    )

    command_service = SimpleNamespace(create_session=AsyncMock(return_value={"session_id": "sess-launcher"}))

    with (
        patch("teleclaude.adapters.discord.input_handlers.get_command_service", return_value=command_service),
        patch("teleclaude.adapters.discord.input_handlers.db") as mock_db,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        await adapter._handle_launcher_click(interaction, "claude")

    adapter.ensure_channel.assert_awaited_once_with(session)
    mock_db.get_session.assert_awaited_once_with("sess-launcher")
    interaction.followup.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_destination_channel_clears_stale_discord_metadata_with_explicit_none_keys() -> None:
    adapter = DummyRoutingHandlers()
    session = Session(
        session_id="sess-discord-stale",
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Session",
        origin_metadata={
            "discord": DiscordAdapterMetadata(
                channel_id=100,
                thread_id=200,
                output_message_id="out-1",
                thread_topper_message_id="top-1",
            ).to_dict()
        },
    )

    with patch("teleclaude.adapters.discord.input_handlers.db") as mock_db:
        mock_db.update_origin_metadata = AsyncMock()

        with pytest.raises(AdapterError, match="metadata cleared"):
            await adapter._resolve_destination_channel(session)

    update_call = mock_db.update_origin_metadata.await_args
    assert update_call is not None
    section = update_call.args[2]
    assert section["thread_id"] is None
    assert section["channel_id"] is None
    assert section["output_message_id"] is None
    assert section["thread_topper_message_id"] is None
