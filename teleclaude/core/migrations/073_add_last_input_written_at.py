"""Add last_input_written_at, the acceptance time coupled to last_input."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Couple the visible span to its own acceptance time.

    The fingerprint clock (``last_message_sent_at``) advances on every
    accepted turn including control turns, so a retained span needs its own
    timestamp. Rows holding a span get the fingerprint clock as the initial
    value — exact for rows whose span came from their latest turn, and the
    nearest available time for backfilled ones.
    """
    await db.execute("ALTER TABLE sessions ADD COLUMN last_input_written_at TEXT")
    await db.execute(
        "UPDATE sessions SET last_input_written_at = last_message_sent_at "
        "WHERE last_input IS NOT NULL AND TRIM(last_input) <> ''"
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
