"""Add durable Discord webhook send-intent tracking.

Restart must never blind-resend an unresolved webhook create, and must never
wedge a lane waiting on one — so an intent carries a bounded set of terminal
dispositions rather than an open pending state.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create the Discord send-intent table."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS discord_send_intents (
            intent_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            generation_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'omitted', 'replayed')),
            platform_message_id TEXT,
            replays_intent_id TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_discord_send_intents_session_gen
        ON discord_send_intents(session_id, generation_id);

        CREATE INDEX IF NOT EXISTS idx_discord_send_intents_status
        ON discord_send_intents(status);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
