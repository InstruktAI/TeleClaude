"""Retain confirmed confined-child publication observations with the owning session."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO = "PRAGMA table_info(github_session_bindings)"
_COLUMN = "push_proofs_json"
_ADD = "ALTER TABLE github_session_bindings ADD COLUMN push_proofs_json TEXT NOT NULL DEFAULT '[]'"


async def up(db: aiosqlite.Connection) -> None:
    """Older sessions gain no inferred publication evidence."""
    cursor = await db.execute(_TABLE_INFO)
    columns = await cursor.fetchall()
    if not any(column[1] == _COLUMN for column in columns):
        await db.execute(_ADD)
    await db.commit()
