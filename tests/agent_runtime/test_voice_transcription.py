"""Functional tests for voice transcription timeout behavior."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from teleclaude.constants import VOICE_TRANSCRIPTION_STATE_FAILED
from teleclaude.core import voice_message_handler
from teleclaude.core.db import Db
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.stt.backends import mlx_parakeet
from teleclaude.stt.backends.mlx_parakeet import MLXParakeetBackend

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


async def test_parakeet_model_load_cannot_block_transcription_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"audio")

    class BlockingModel:
        def generate(self, _audio_file_path: str) -> object:
            return SimpleNamespace(text="late transcript")

    def blocking_load(_model_ref: str) -> BlockingModel:
        time.sleep(0.08)
        return BlockingModel()

    backend = MLXParakeetBackend()
    backend._cli_bin = None
    monkeypatch.setattr(mlx_parakeet, "load_stt_model", blocking_load)
    monkeypatch.setattr(mlx_parakeet, "_mlx_audio_import_attempted", True)
    monkeypatch.setattr(mlx_parakeet, "mlx_audio_import_error", None)
    monkeypatch.setattr(voice_message_handler, "BACKENDS", {"parakeet": backend})
    monkeypatch.setattr(voice_message_handler, "VOICE_TRANSCRIPTION_TIMEOUT_S", 0.01)

    text, error = await voice_message_handler.transcribe_voice_with_retry(str(audio_file), max_retries=0)

    assert text is None
    assert error


async def test_voice_handler_marks_timeout_failed_and_resolves_notice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"audio")
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
    sent_notices: list[tuple[str, MessageMetadata]] = []
    edited_notices: list[tuple[str, str, MessageMetadata]] = []
    notice_message_id = "notice-1"

    class BlockingModel:
        def generate(self, _audio_file_path: str) -> object:
            return SimpleNamespace(text="late transcript")

    def blocking_load(_model_ref: str) -> BlockingModel:
        time.sleep(0.08)
        return BlockingModel()

    async def send_message(_session_id: str, message: str, metadata: MessageMetadata) -> str | None:
        sent_notices.append((message, metadata))
        return notice_message_id

    async def edit_message(
        _session_id: str,
        message_id: str,
        message: str,
        metadata: MessageMetadata,
    ) -> bool:
        edited_notices.append((message_id, message, metadata))
        return True

    backend = MLXParakeetBackend()
    backend._cli_bin = None
    monkeypatch.setattr(mlx_parakeet, "load_stt_model", blocking_load)
    monkeypatch.setattr(mlx_parakeet, "_mlx_audio_import_attempted", True)
    monkeypatch.setattr(mlx_parakeet, "mlx_audio_import_error", None)
    monkeypatch.setattr(voice_message_handler, "db", db)
    monkeypatch.setattr(voice_message_handler, "BACKENDS", {"parakeet": backend})
    monkeypatch.setattr(voice_message_handler, "VOICE_TRANSCRIPTION_TIMEOUT_S", 0.01)
    monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))

    row = None
    try:
        result = await voice_message_handler.handle_voice(
            session_id="session-voice",
            audio_path=str(audio_file),
            context=VoiceEventContext(
                session_id="session-voice",
                file_path=str(audio_file),
                origin=InputOrigin.DISCORD.value,
            ),
            send_message=send_message,
            edit_message=edit_message,
        )
        row = await db.get_voice_transcription(1)
    finally:
        await db.close()

    assert result is None
    assert row is not None
    assert row.state == VOICE_TRANSCRIPTION_STATE_FAILED
    assert row.last_error
    assert len(sent_notices) == 1
    assert sent_notices[0][0]
    assert len(edited_notices) == 1
    assert edited_notices[0][0] == notice_message_id
    assert edited_notices[0][1]
    assert not edited_notices[0][2].is_transcription
