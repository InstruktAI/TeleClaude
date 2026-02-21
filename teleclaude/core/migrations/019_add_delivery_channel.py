"""Migration: Add delivery_channel column to notification_outbox."""

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add delivery_channel column to notification_outbox table."""
    try:
        await db.execute("ALTER TABLE notification_outbox ADD COLUMN delivery_channel TEXT NOT NULL DEFAULT 'telegram'")
    except aiosqlite.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            return
        raise
