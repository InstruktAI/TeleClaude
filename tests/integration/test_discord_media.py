"""Integration tests for Discord file and image attachment handling."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.adapters.discord_adapter import DiscordAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import Db
from teleclaude.core.models import DiscordAdapterMetadata, Session, SessionAdapterMetadata
from teleclaude.core.origins import InputOrigin


class FakeDiscordIntents:
    """Minimal discord.Intents replacement for tests."""

    def __init__(self) -> None:
        self.guilds = False
        self.messages = False
        self.message_content = False

    @classmethod
    def default(cls) -> "FakeDiscordIntents":
        return cls()


class FakeDiscordClient:
    """Minimal discord.Client replacement for tests."""

    def __init__(self, *, intents: FakeDiscordIntents) -> None:
        self.intents = intents
        self.user = SimpleNamespace(id=999, name="teleclaude")
        self.started_token: str | None = None
        self.closed = False

    def event(self, coro):
        setattr(self, coro.__name__, coro)
        return coro

    async def start(self, token: str) -> None:
        self.started_token = token
        on_ready = getattr(self, "on_ready", None)
        if on_ready is not None:
            await on_ready()

    async def close(self) -> None:
        self.closed = True


class FakeDiscordModule:
    """Minimal discord module replacement for tests."""

    Intents = FakeDiscordIntents
    Client = FakeDiscordClient


@pytest.fixture
async def session_manager(tmp_path: Path):
    db_path = tmp_path / "discord-media-test.db"
    manager = Db(str(db_path))
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()
        db_path.unlink(missing_ok=True)


@pytest.fixture
def mock_client() -> AdapterClient:
    """Mock adapter client."""
    client = MagicMock(spec=AdapterClient)
    client.pre_handle_command = AsyncMock()
    client.send_message = AsyncMock()
    client.delete_message = AsyncMock()
    client.broadcast_user_input = AsyncMock()
    client.break_threaded_turn = AsyncMock()
    return client


@pytest.fixture
async def discord_session(session_manager: Db, tmp_path: Path) -> Session:
    """Create a test Discord session."""
    session = await session_manager.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-discord",
        last_input_origin=InputOrigin.DISCORD.value,
        title="Discord Media Test",
        adapter_metadata=SessionAdapterMetadata(
            discord=DiscordAdapterMetadata(
                user_id="123456",
                thread_id=789,
            )
        ),
        project_path=str(tmp_path),
    )
    return session


def create_fake_attachment(
    filename: str,
    content_type: str,
    save_fn: AsyncMock | None = None,
) -> object:
    """Create a fake Discord attachment."""
    attachment = SimpleNamespace(
        filename=filename,
        content_type=content_type,
        save=save_fn or AsyncMock(),
    )
    return attachment


def create_fake_message(
    *,
    content: str = "",
    attachments: list[object] | None = None,
    author_id: str = "123456",
    message_id: int = 1001,
    guild_id: int | None = None,
    channel_id: int = 789,
) -> object:
    """Create a fake Discord message."""
    message = SimpleNamespace(
        id=message_id,
        content=content,
        attachments=attachments or [],
        author=SimpleNamespace(id=author_id),
        guild=SimpleNamespace(id=guild_id) if guild_id else None,
        channel=SimpleNamespace(
            id=channel_id,
            parent_id=None,
        ),
    )
    return message


@pytest.mark.integration
async def test_image_only_message(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """Image-only message should create session and dispatch handle_file."""
    save_fn = AsyncMock()
    attachment = create_fake_attachment("screenshot.png", "image/png", save_fn)
    message = create_fake_message(content="", attachments=[attachment])

    mock_handle_file = AsyncMock()
    mock_process_message = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_file = mock_handle_file
        mock_cmd_service.return_value.process_message = mock_process_message

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        await adapter._handle_on_message(message)

    # Verify file was downloaded
    save_fn.assert_awaited_once()
    saved_path = save_fn.await_args[0][0]
    assert "photos" in str(saved_path)
    assert "screenshot.png" in str(saved_path)

    # Verify handle_file was called
    mock_handle_file.assert_awaited_once()
    cmd = mock_handle_file.await_args[0][0]
    assert cmd.session_id == discord_session.session_id
    assert cmd.filename == "screenshot.png"
    assert "photos" in cmd.file_path

    # Verify process_message was NOT called (no text)
    mock_process_message.assert_not_awaited()


@pytest.mark.integration
async def test_file_only_message(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """File-only message (PDF) should create session and dispatch handle_file."""
    save_fn = AsyncMock()
    attachment = create_fake_attachment("document.pdf", "application/pdf", save_fn)
    message = create_fake_message(content="", attachments=[attachment])

    mock_handle_file = AsyncMock()
    mock_process_message = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_file = mock_handle_file
        mock_cmd_service.return_value.process_message = mock_process_message

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        await adapter._handle_on_message(message)

    # Verify file was downloaded
    save_fn.assert_awaited_once()
    saved_path = save_fn.await_args[0][0]
    assert "files" in str(saved_path)
    assert "document.pdf" in str(saved_path)

    # Verify handle_file was called
    mock_handle_file.assert_awaited_once()
    cmd = mock_handle_file.await_args[0][0]
    assert cmd.session_id == discord_session.session_id
    assert cmd.filename == "document.pdf"
    assert "files" in cmd.file_path

    # Verify process_message was NOT called (no text)
    mock_process_message.assert_not_awaited()


@pytest.mark.integration
async def test_text_plus_image(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """Text + image message should call both handle_file and process_message."""
    save_fn = AsyncMock()
    attachment = create_fake_attachment("diagram.png", "image/png", save_fn)
    message = create_fake_message(content="Check this out", attachments=[attachment])

    mock_handle_file = AsyncMock()
    mock_dispatch_command = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_file = mock_handle_file

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        adapter._dispatch_command = mock_dispatch_command
        await adapter._handle_on_message(message)

    # Verify handle_file was called with caption
    mock_handle_file.assert_awaited_once()
    cmd = mock_handle_file.await_args[0][0]
    assert cmd.caption == "Check this out"

    # Verify process_message was called
    mock_dispatch_command.assert_awaited_once()
    call_args = mock_dispatch_command.await_args[0]
    assert call_args[3] == "process_message"


@pytest.mark.integration
async def test_multiple_attachments(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """Multiple attachments should all be processed."""
    save_fn1 = AsyncMock()
    save_fn2 = AsyncMock()
    save_fn3 = AsyncMock()

    attachments = [
        create_fake_attachment("image1.png", "image/png", save_fn1),
        create_fake_attachment("image2.jpg", "image/jpeg", save_fn2),
        create_fake_attachment("data.csv", "text/csv", save_fn3),
    ]
    message = create_fake_message(content="Multiple files", attachments=attachments)

    mock_handle_file = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_file = mock_handle_file

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        await adapter._handle_on_message(message)

    # Verify all three files were downloaded
    save_fn1.assert_awaited_once()
    save_fn2.assert_awaited_once()
    save_fn3.assert_awaited_once()

    # Verify handle_file was called 3 times
    assert mock_handle_file.await_count == 3

    # Verify only first attachment gets caption
    first_call = mock_handle_file.await_args_list[0][0][0]
    assert first_call.caption == "Multiple files"

    second_call = mock_handle_file.await_args_list[1][0][0]
    assert second_call.caption is None


@pytest.mark.integration
async def test_download_failure_continues(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """Download failure for one attachment should not prevent processing others."""
    save_fn1 = AsyncMock(side_effect=Exception("Network error"))
    save_fn2 = AsyncMock()

    attachments = [
        create_fake_attachment("bad.png", "image/png", save_fn1),
        create_fake_attachment("good.png", "image/png", save_fn2),
    ]
    message = create_fake_message(content="", attachments=attachments)

    mock_handle_file = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_file = mock_handle_file

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        await adapter._handle_on_message(message)

    # Verify first download was attempted
    save_fn1.assert_awaited_once()

    # Verify second download succeeded
    save_fn2.assert_awaited_once()

    # Verify handle_file was called once (for the successful attachment)
    assert mock_handle_file.await_count == 1
    cmd = mock_handle_file.await_args[0][0]
    assert cmd.filename == "good.png"


@pytest.mark.integration
async def test_audio_attachment_still_uses_voice_path(
    session_manager: Db,
    discord_session: Session,
    mock_client: AdapterClient,
    tmp_path: Path,
) -> None:
    """Audio attachment should still be handled by existing voice path (regression check)."""
    save_fn = AsyncMock()
    attachment = create_fake_attachment("voice.ogg", "audio/ogg", save_fn)
    message = create_fake_message(content="", attachments=[attachment])

    mock_handle_voice = AsyncMock()
    mock_handle_file = AsyncMock()

    with (
        patch("teleclaude.adapters.discord_adapter.db", session_manager),
        patch("teleclaude.adapters.discord_adapter.get_command_service") as mock_cmd_service,
        patch("teleclaude.adapters.discord_adapter.importlib.import_module", return_value=FakeDiscordModule),
        patch("teleclaude.adapters.discord_adapter.config") as mock_config,
    ):
        mock_config.discord.token = "test-token"
        mock_config.discord.guild_id = None
        mock_config.discord.help_desk_channel_id = 789
        mock_cmd_service.return_value.handle_voice = mock_handle_voice
        mock_cmd_service.return_value.handle_file = mock_handle_file

        adapter = DiscordAdapter(
            client=mock_client,
            task_registry=MagicMock(),
        )
        await adapter._handle_on_message(message)

    # Verify voice handler was called
    mock_handle_voice.assert_awaited_once()

    # Verify file handler was NOT called
    mock_handle_file.assert_not_awaited()
