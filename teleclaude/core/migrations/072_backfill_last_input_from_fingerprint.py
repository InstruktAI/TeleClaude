"""Backfill sessions.last_input for rows predating write-time resolution."""

from __future__ import annotations

import aiosqlite

from teleclaude.core.injected_text import TranscriptEntryKind, classify_transcript_text

_SELECT_UNFILLED_FINGERPRINTS = (
    "SELECT session_id, last_message_sent FROM sessions "
    "WHERE last_input IS NULL AND last_message_sent IS NOT NULL AND TRIM(last_message_sent) <> ''"
)
_RESTORE_VISIBLE_INPUT = "UPDATE sessions SET last_input = ? WHERE session_id = ?"


async def up(db: aiosqlite.Connection) -> None:
    """Give pre-existing sessions their input line back, best-effort.

    The visible span is resolved at acceptance from the full turn, so rows
    accepted before that write existed hold only the truncated fingerprint.
    The body of a truncated envelope cannot be recovered, but the whole-entry
    control classification keys on the opening and survives truncation: a
    platform-control turn stays empty, anything else shows the stored text
    as-is — what the session row displayed before the visible-span work.
    Each next accepted turn replaces this with the cleanly resolved span.
    """
    rows = await db.execute_fetchall(_SELECT_UNFILLED_FINGERPRINTS)
    for session_id, fingerprint in rows:
        if classify_transcript_text(str(fingerprint)).kind is TranscriptEntryKind.PLATFORM_CONTROL:
            continue
        await db.execute(_RESTORE_VISIBLE_INPUT, (str(fingerprint), session_id))
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Best-effort backfill — nothing to restore."""
