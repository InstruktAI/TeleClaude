from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.constants import (
    VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS,
    VOICE_TRANSCRIPTION_STATE_FAILED,
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
)
from teleclaude.core import voice_message_handler, voice_recovery
from teleclaude.core.events import VoiceEventContext
from teleclaude.core.models import Session
from teleclaude.types.commands import HandleVoiceCommand

pytestmark = pytest.mark.asyncio


def _session() -> Session:
    return Session(
        session_id="session-1",
        computer_name="machine",
        tmux_session_name="tmux-session",
        title="Voice",
    )


def _row(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": 9,
        "session_id": "session-1",
        "audio_path": "/tmp/teleclaude_voice/voice.ogg",
        "origin": "discord",
        "notice_message_id": "notice-1",
        "thread_id": None,
        "actor_id": "actor-1",
        "actor_name": "Actor",
        "actor_avatar_url": None,
        "duration": 3.0,
        "language": "en",
        "attempts": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_recovery_resubmits_existing_notice_when_audio_is_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"audio")
    row = _row(audio_path=str(audio_path))
    db = SimpleNamespace(
        list_recoverable_voice_transcriptions=AsyncMock(return_value=[row]),
        increment_voice_transcription_attempts=AsyncMock(return_value=True),
        get_voice_transcription=AsyncMock(return_value=_row(audio_path=str(audio_path), attempts=1)),
    )
    command_service = SimpleNamespace(handle_voice=AsyncMock())

    monkeypatch.setattr(voice_recovery, "db", db)

    processed = await voice_recovery.recover_voice_transcriptions(
        client=SimpleNamespace(), command_service=command_service
    )

    assert processed == 1
    command = command_service.handle_voice.await_args.args[0]
    assert isinstance(command, HandleVoiceCommand)
    assert command.voice_transcription_id == row.id
    assert command.notice_message_id == row.notice_message_id


async def test_recovery_pass_drives_existing_notice_to_terminal_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"audio")
    final_text = "recovered words"
    row = _row(audio_path=str(audio_path), attempts=0)
    session = _session()
    edits: list[tuple[str, bool]] = []
    sends: list[bool] = []

    async def increment_attempts(_row_id: int) -> bool:
        row.attempts += 1
        return True

    async def update_state(_row_id: int, state: str, *, last_error: str | None = None) -> bool:
        row.state = state
        row.last_error = last_error
        return True

    async def send_message(_session_id: str, message: str, _metadata: object) -> str | None:
        sends.append(bool(message))
        return "unexpected"

    async def edit_message(_session_id: str, message_id: str, message: str, _metadata: object) -> bool:
        edits.append((message_id, message == final_text))
        return True

    async def transcribe(_path: str, *, language: str | None = None) -> tuple[str | None, str | None]:
        del language
        return final_text, None

    async def handle_voice_command(cmd: HandleVoiceCommand) -> None:
        await voice_message_handler.handle_voice(
            session_id=cmd.session_id,
            audio_path=cmd.file_path,
            context=VoiceEventContext(
                session_id=cmd.session_id,
                file_path=cmd.file_path,
                origin=cmd.origin,
                voice_transcription_id=cmd.voice_transcription_id,
                notice_message_id=cmd.notice_message_id,
            ),
            send_message=send_message,
            edit_message=edit_message,
        )

    db = SimpleNamespace(
        list_recoverable_voice_transcriptions=AsyncMock(return_value=[row]),
        increment_voice_transcription_attempts=AsyncMock(side_effect=increment_attempts),
        get_voice_transcription=AsyncMock(return_value=row),
        get_session=AsyncMock(return_value=session),
        update_voice_transcription_state=AsyncMock(side_effect=update_state),
    )
    command_service = SimpleNamespace(handle_voice=AsyncMock(side_effect=handle_voice_command))

    monkeypatch.setattr(voice_recovery, "db", db)
    monkeypatch.setattr(voice_message_handler, "db", db)
    monkeypatch.setattr(voice_message_handler.tmux_bridge, "is_process_running", AsyncMock(return_value=True))
    monkeypatch.setattr(voice_message_handler, "transcribe_voice_with_retry", transcribe)

    processed = await voice_recovery.recover_voice_transcriptions(
        client=SimpleNamespace(), command_service=command_service
    )

    assert processed == 1
    assert row.state == VOICE_TRANSCRIPTION_STATE_SUCCEEDED
    assert row.attempts == 1
    assert edits == [(row.notice_message_id, False), (row.notice_message_id, True)]
    assert sends == []
    assert not audio_path.exists()


async def test_recovery_marks_missing_audio_failed_and_edits_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _row(audio_path="/tmp/teleclaude_voice/missing.ogg")
    session = _session()
    logger = MagicMock()
    db = SimpleNamespace(
        list_recoverable_voice_transcriptions=AsyncMock(return_value=[row]),
        increment_voice_transcription_attempts=AsyncMock(return_value=True),
        get_voice_transcription=AsyncMock(return_value=_row(audio_path=row.audio_path, attempts=1)),
        get_session=AsyncMock(return_value=session),
        update_session=AsyncMock(),
        update_voice_transcription_state=AsyncMock(return_value=True),
    )
    client = SimpleNamespace(edit_message=AsyncMock(return_value=True), send_message=AsyncMock(return_value=None))

    monkeypatch.setattr(voice_recovery, "db", db)
    monkeypatch.setattr(voice_recovery, "logger", logger)

    processed = await voice_recovery.recover_voice_transcriptions(
        client=client,
        command_service=SimpleNamespace(handle_voice=AsyncMock()),
    )

    assert processed == 1
    assert logger.info.call_args.args[1] == 1
    db.update_voice_transcription_state.assert_awaited_once()
    assert db.update_voice_transcription_state.await_args.args[:2] == (row.id, VOICE_TRANSCRIPTION_STATE_FAILED)
    client.edit_message.assert_awaited_once()
    client.send_message.assert_not_awaited()


async def test_recovery_stops_retrying_after_attempt_cap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"audio")
    row = _row(audio_path=str(audio_path), attempts=VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS)
    session = _session()
    db = SimpleNamespace(
        list_recoverable_voice_transcriptions=AsyncMock(return_value=[row]),
        increment_voice_transcription_attempts=AsyncMock(return_value=True),
        get_voice_transcription=AsyncMock(
            return_value=_row(audio_path=str(audio_path), attempts=VOICE_TRANSCRIPTION_RECOVERY_MAX_ATTEMPTS + 1)
        ),
        get_session=AsyncMock(return_value=session),
        update_session=AsyncMock(),
        update_voice_transcription_state=AsyncMock(return_value=True),
    )
    client = SimpleNamespace(edit_message=AsyncMock(return_value=True), send_message=AsyncMock(return_value=None))
    command_service = SimpleNamespace(handle_voice=AsyncMock())

    monkeypatch.setattr(voice_recovery, "db", db)

    processed = await voice_recovery.recover_voice_transcriptions(client=client, command_service=command_service)

    assert processed == 1
    command_service.handle_voice.assert_not_awaited()
    db.update_voice_transcription_state.assert_awaited_once()


async def test_recovery_continues_after_one_row_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_audio = tmp_path / "first.ogg"
    second_audio = tmp_path / "second.ogg"
    first_audio.write_bytes(b"first")
    second_audio.write_bytes(b"second")
    first = _row(id=11, audio_path=str(first_audio))
    second = _row(id=12, audio_path=str(second_audio))
    refreshed_by_id = {
        first.id: _row(id=first.id, audio_path=str(first_audio), attempts=1),
        second.id: _row(id=second.id, audio_path=str(second_audio), attempts=1),
    }
    row_error = RuntimeError("downstream failed")
    commands: list[int | None] = []
    logger = MagicMock()

    async def get_voice_transcription(row_id: int) -> SimpleNamespace:
        return refreshed_by_id[row_id]

    async def handle_voice(command: HandleVoiceCommand) -> None:
        commands.append(command.voice_transcription_id)
        if command.voice_transcription_id == first.id:
            raise row_error

    db = SimpleNamespace(
        list_recoverable_voice_transcriptions=AsyncMock(return_value=[first, second]),
        increment_voice_transcription_attempts=AsyncMock(return_value=True),
        get_voice_transcription=AsyncMock(side_effect=get_voice_transcription),
    )
    command_service = SimpleNamespace(handle_voice=AsyncMock(side_effect=handle_voice))

    monkeypatch.setattr(voice_recovery, "db", db)
    monkeypatch.setattr(voice_recovery, "logger", logger)

    processed = await voice_recovery.recover_voice_transcriptions(
        client=SimpleNamespace(), command_service=command_service
    )

    assert processed == 1
    assert commands == [first.id, second.id]
    logger.exception.assert_called_once()
    assert logger.exception.call_args.args[1:] == (first.id, row_error)
