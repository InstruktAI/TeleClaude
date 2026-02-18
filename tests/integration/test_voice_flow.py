"""Integration tests for voice transcription flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import Db
from teleclaude.core.models import SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import HandleVoiceCommand


@pytest.fixture
async def session_manager(tmp_path: Path):
    db_path = tmp_path / "voice-test.db"
    manager = Db(str(db_path))
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()
        db_path.unlink(missing_ok=True)


@pytest.mark.integration
async def test_voice_transcription_executes_command(session_manager: Db) -> None:
    """Voice transcription should forward to process_message and start polling."""
    from teleclaude.core import command_handlers

    session = await session_manager.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-voice",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Voice Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        project_path="/tmp",
    )

    client = MagicMock()
    client.pre_handle_command = AsyncMock()
    client.send_message = AsyncMock()
    client.delete_message = AsyncMock()
    client.broadcast_user_input = AsyncMock()
    client.break_threaded_turn = AsyncMock()

    start_polling = AsyncMock()

    with (
        patch("teleclaude.core.command_handlers.db", session_manager),
        patch(
            "teleclaude.core.command_handlers.voice_message_handler.handle_voice", new=AsyncMock(return_value="say hi")
        ),
        patch(
            "teleclaude.core.command_handlers.tmux_io.process_text", new=AsyncMock(return_value=True)
        ) as mock_process,
    ):
        cmd = HandleVoiceCommand(
            session_id=session.session_id,
            file_path="/tmp/voice.ogg",
            origin=InputOrigin.TELEGRAM.value,
        )
        await command_handlers.handle_voice(cmd, client, start_polling)

    assert mock_process.await_count == 1
    sent_text = mock_process.await_args.kwargs.get("text") if mock_process.await_args else None
    if isinstance(sent_text, str):
        assert "say hi" in sent_text
    start_polling.assert_awaited_once()


@pytest.mark.integration
async def test_voice_transcription_none_skips_execution(session_manager: Db) -> None:
    """If transcription fails, no tmux command should be sent."""
    from teleclaude.core import command_handlers

    session = await session_manager.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-voice",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Voice Test",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        project_path="/tmp",
    )

    client = MagicMock()
    client.pre_handle_command = AsyncMock()
    client.send_message = AsyncMock()
    client.delete_message = AsyncMock()
    client.broadcast_user_input = AsyncMock()

    start_polling = AsyncMock()

    with (
        patch("teleclaude.core.command_handlers.db", session_manager),
        patch("teleclaude.core.command_handlers.voice_message_handler.handle_voice", new=AsyncMock(return_value=None)),
        patch(
            "teleclaude.core.command_handlers.tmux_io.process_text", new=AsyncMock(return_value=True)
        ) as mock_process,
    ):
        cmd = HandleVoiceCommand(
            session_id=session.session_id,
            file_path="/tmp/voice.ogg",
            origin=InputOrigin.TELEGRAM.value,
        )
        await command_handlers.handle_voice(cmd, client, start_polling)

    assert mock_process.await_count == 0
    start_polling.assert_not_awaited()
