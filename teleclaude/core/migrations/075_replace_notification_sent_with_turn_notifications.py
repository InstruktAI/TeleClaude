"""Replace the per-turn notification boolean with recorded notification outcomes."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Migrate the owned sessions state forward without retaining the old flag."""
    async with db.execute("SELECT name FROM pragma_table_info('sessions')") as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if "notification_sent" not in columns:
        return
    await db.execute("ALTER TABLE sessions ADD COLUMN turn_notifications_sent TEXT NOT NULL DEFAULT ''")
    await db.execute("UPDATE sessions SET turn_notifications_sent = 'terminal_turn_end' WHERE notification_sent = 1")
    await db.execute("ALTER TABLE sessions DROP COLUMN notification_sent")
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
