"""Add notification_outbox table for durable role-based notifications."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create notification_outbox table and indexes."""
    cursor = await db.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name='notification_outbox'
        """
    )
    exists = await cursor.fetchone()
    if not exists:
        await db.execute(
            """
            CREATE TABLE notification_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                recipient_email TEXT NOT NULL,
                content TEXT NOT NULL,
                file_path TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                attempt_count INTEGER DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                locked_at TEXT
            )
            """
        )

    index_cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notification_outbox_status'"
    )
    if not await index_cursor.fetchone():
        await db.execute("CREATE INDEX idx_notification_outbox_status ON notification_outbox(status)")

    index_cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notification_outbox_next_attempt_at'"
    )
    if not await index_cursor.fetchone():
        await db.execute("CREATE INDEX idx_notification_outbox_next_attempt_at ON notification_outbox(next_attempt_at)")

    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop notification_outbox table and indexes."""
    await db.execute("DROP INDEX IF EXISTS idx_notification_outbox_next_attempt_at")
    await db.execute("DROP INDEX IF EXISTS idx_notification_outbox_status")
    await db.execute("DROP TABLE IF EXISTS notification_outbox")
    await db.commit()
