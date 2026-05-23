from __future__ import annotations

import importlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from teleclaude.constants import (
    VOICE_TRANSCRIPTION_STATE_FAILED,
    VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    VOICE_TRANSCRIPTION_STATE_PENDING,
    VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
)
from teleclaude.core.db import Db
from teleclaude.core.origins import InputOrigin

pytestmark = pytest.mark.asyncio

add_voice_transcriptions = importlib.import_module("teleclaude.core.migrations.047_add_voice_transcriptions")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Db]:
    db = Db(str(tmp_path / "teleclaude.db"))
    await db.initialize()
    try:
        yield db
    finally:
        await db.close()


async def _create_transcription(
    db: Db,
    *,
    session_id: str = "session-1",
    audio_path: str = "/tmp/teleclaude_voice/voice-1.ogg",
    origin: str = InputOrigin.DISCORD.value,
):
    return await db.create_voice_transcription(
        session_id=session_id,
        audio_path=audio_path,
        origin=origin,
    )


async def test_create_voice_transcription_persists_pending_state(database: Db) -> None:
    audio_path = "/tmp/teleclaude_voice/voice-1.ogg"

    created = await _create_transcription(database, audio_path=audio_path)
    stored = await database.get_voice_transcription(created.id or 0)

    assert stored is not None
    assert stored.audio_path == audio_path
    assert stored.state == VOICE_TRANSCRIPTION_STATE_PENDING
    assert stored.attempts == 0
    assert stored.notice_message_id is None


async def test_notice_message_id_update_persists(database: Db) -> None:
    created = await _create_transcription(database)
    notice_message_id = "notice-1"

    updated = await database.set_voice_transcription_notice_message_id(created.id or 0, notice_message_id)
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.notice_message_id == notice_message_id


async def test_state_update_records_in_progress(database: Db) -> None:
    created = await _create_transcription(database)

    updated = await database.update_voice_transcription_state(
        created.id or 0,
        VOICE_TRANSCRIPTION_STATE_IN_PROGRESS,
    )
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.state == VOICE_TRANSCRIPTION_STATE_IN_PROGRESS


async def test_state_update_records_terminal_failure_reason(database: Db) -> None:
    created = await _create_transcription(database)
    failure_reason = "backend unavailable"

    updated = await database.update_voice_transcription_state(
        created.id or 0,
        VOICE_TRANSCRIPTION_STATE_FAILED,
        last_error=failure_reason,
    )
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.state == VOICE_TRANSCRIPTION_STATE_FAILED
    assert stored.last_error == failure_reason


async def test_state_update_records_interrupted(database: Db) -> None:
    created = await _create_transcription(database)

    updated = await database.update_voice_transcription_state(
        created.id or 0,
        VOICE_TRANSCRIPTION_STATE_INTERRUPTED,
    )
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.state == VOICE_TRANSCRIPTION_STATE_INTERRUPTED


async def test_state_update_records_success(database: Db) -> None:
    created = await _create_transcription(database)

    updated = await database.update_voice_transcription_state(
        created.id or 0,
        VOICE_TRANSCRIPTION_STATE_SUCCEEDED,
    )
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.state == VOICE_TRANSCRIPTION_STATE_SUCCEEDED


async def test_list_recoverable_voice_transcriptions_excludes_terminal_rows(database: Db) -> None:
    pending = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-pending.ogg")
    in_progress = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-progress.ogg")
    interrupted = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-interrupted.ogg")
    succeeded = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-succeeded.ogg")
    failed = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-failed.ogg")
    await database.update_voice_transcription_state(in_progress.id or 0, VOICE_TRANSCRIPTION_STATE_IN_PROGRESS)
    await database.update_voice_transcription_state(interrupted.id or 0, VOICE_TRANSCRIPTION_STATE_INTERRUPTED)
    await database.update_voice_transcription_state(succeeded.id or 0, VOICE_TRANSCRIPTION_STATE_SUCCEEDED)
    await database.update_voice_transcription_state(failed.id or 0, VOICE_TRANSCRIPTION_STATE_FAILED)

    recoverable = await database.list_recoverable_voice_transcriptions()

    assert [row.id for row in recoverable] == [pending.id, in_progress.id, interrupted.id]


async def test_increment_voice_transcription_attempts_persists(database: Db) -> None:
    created = await _create_transcription(database)

    updated = await database.increment_voice_transcription_attempts(created.id or 0)
    stored = await database.get_voice_transcription(created.id or 0)

    assert updated is True
    assert stored is not None
    assert stored.attempts == 1


async def test_list_live_voice_transcription_audio_paths_returns_recoverable_rows(database: Db) -> None:
    pending = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-pending.ogg")
    in_progress = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-progress.ogg")
    interrupted = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-interrupted.ogg")
    succeeded = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-succeeded.ogg")
    failed = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-failed.ogg")
    await database.update_voice_transcription_state(in_progress.id or 0, VOICE_TRANSCRIPTION_STATE_IN_PROGRESS)
    await database.update_voice_transcription_state(interrupted.id or 0, VOICE_TRANSCRIPTION_STATE_INTERRUPTED)
    await database.update_voice_transcription_state(succeeded.id or 0, VOICE_TRANSCRIPTION_STATE_SUCCEEDED)
    await database.update_voice_transcription_state(failed.id or 0, VOICE_TRANSCRIPTION_STATE_FAILED)

    live_paths = await database.list_live_voice_transcription_audio_paths()

    assert live_paths == {
        pending.audio_path,
        in_progress.audio_path,
        interrupted.audio_path,
    }


async def test_cleanup_terminal_voice_transcriptions_prunes_only_terminal_rows(database: Db) -> None:
    pending = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-pending.ogg")
    succeeded = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-succeeded.ogg")
    failed = await _create_transcription(database, audio_path="/tmp/teleclaude_voice/voice-failed.ogg")
    await database.update_voice_transcription_state(succeeded.id or 0, VOICE_TRANSCRIPTION_STATE_SUCCEEDED)
    await database.update_voice_transcription_state(failed.id or 0, VOICE_TRANSCRIPTION_STATE_FAILED)

    deleted = await database.cleanup_terminal_voice_transcriptions((datetime.now(UTC) + timedelta(days=1)).isoformat())

    assert deleted == 2
    assert await database.get_voice_transcription(pending.id or 0) is not None
    assert await database.get_voice_transcription(succeeded.id or 0) is None
    assert await database.get_voice_transcription(failed.id or 0) is None


async def test_add_voice_transcriptions_migration_is_idempotent() -> None:
    db = await aiosqlite.connect(":memory:")
    try:
        await add_voice_transcriptions.up(db)
        await add_voice_transcriptions.up(db)

        async with db.execute(
            f"SELECT name FROM pragma_table_info('{add_voice_transcriptions.VOICE_TRANSCRIPTIONS_TABLE}')"
        ) as cursor:
            rows = await cursor.fetchall()

        assert {str(row[0]) for row in rows} == set(add_voice_transcriptions.VOICE_TRANSCRIPTION_COLUMNS)
    finally:
        await db.close()
