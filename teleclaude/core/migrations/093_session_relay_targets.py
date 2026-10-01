"""Add the escalation relay's per-admin targets and its recorded exchange to sessions."""

from __future__ import annotations

import aiosqlite

_COLUMN_LOOKUP_SQL = "SELECT 1 FROM pragma_table_info('sessions') WHERE name = ?"

_RELAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("relay_targets", "ALTER TABLE sessions ADD COLUMN relay_targets TEXT NOT NULL DEFAULT '[]'"),
    ("relay_exchange", "ALTER TABLE sessions ADD COLUMN relay_exchange TEXT NOT NULL DEFAULT '[]'"),
)


async def up(db: aiosqlite.Connection) -> None:
    """Add each relay column that is not there yet."""
    for column, add_sql in _RELAY_COLUMNS:
        result = await db.execute(_COLUMN_LOOKUP_SQL, (column,))
        if await result.fetchone() is None:
            await db.execute(add_sql)
    await db.commit()
