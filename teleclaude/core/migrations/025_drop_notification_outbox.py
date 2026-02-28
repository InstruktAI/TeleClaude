"""Drop legacy notification_outbox table — replaced by teleclaude_events EventDB."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Drop the notification_outbox table."""
    await db.execute("DROP TABLE IF EXISTS notification_outbox")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Recreate notification_outbox for rollback (structure only, data is lost)."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            content TEXT NOT NULL,
            file_path TEXT,
            delivery_channel TEXT NOT NULL DEFAULT 'telegram',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT '',
            next_attempt_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            delivered_at TEXT,
            locked_at TEXT
        )
        """
    )
    await db.commit()
