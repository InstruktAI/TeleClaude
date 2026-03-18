"""Add principal column to sessions table for inherited agent identity."""
# pylint: disable=invalid-name  # Migration filenames are versioned on purpose.


from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Add principal column to persist inherited agent identity across session lineage."""
    await db.execute("ALTER TABLE sessions ADD COLUMN principal TEXT")
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """No-op — SQLite < 3.35.0 does not support DROP COLUMN."""
