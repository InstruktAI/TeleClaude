"""Add durable voice transcription recovery rows."""

from __future__ import annotations

import aiosqlite

VOICE_TRANSCRIPTIONS_TABLE = "voice_transcriptions"
VOICE_TRANSCRIPTION_COLUMNS = (
    "id",
    "session_id",
    "audio_path",
    "origin",
    "notice_message_id",
    "thread_id",
    "actor_id",
    "actor_name",
    "actor_avatar_url",
    "duration",
    "language",
    "state",
    "attempts",
    "last_error",
    "created_at",
    "updated_at",
)


async def up(db: aiosqlite.Connection) -> None:
    """Create the durable voice transcription table and recovery indexes."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS voice_transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            audio_path TEXT NOT NULL,
            origin TEXT NOT NULL,
            notice_message_id TEXT,
            thread_id TEXT,
            actor_id TEXT,
            actor_name TEXT,
            actor_avatar_url TEXT,
            duration REAL,
            language TEXT,
            state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'in_progress', 'succeeded', 'failed', 'interrupted')),
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_state_id
        ON voice_transcriptions(state, id);

        CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_session
        ON voice_transcriptions(session_id);

        CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_audio_path
        ON voice_transcriptions(audio_path);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
