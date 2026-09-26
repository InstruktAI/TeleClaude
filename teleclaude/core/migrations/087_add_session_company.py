"""Record the company a session operates the business of on every session row."""

from __future__ import annotations

import aiosqlite

_ADD_COMPANY_COLUMN_SQL = "ALTER TABLE sessions ADD COLUMN company TEXT"


async def up(db: aiosqlite.Connection) -> None:
    """Add the nullable company column. Every existing session correctly has no company."""
    await db.execute(_ADD_COMPANY_COLUMN_SQL)
    await db.commit()
