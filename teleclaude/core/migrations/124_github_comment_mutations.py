"""Retain separate native maintenance observations without rewriting creation provenance."""

from __future__ import annotations

import aiosqlite

_ADD_MUTATIONS = "ALTER TABLE github_object_associations ADD COLUMN mutations_json TEXT NOT NULL DEFAULT '[]'"
_TABLE_INFO = "PRAGMA table_info(github_object_associations)"
_MUTATIONS_COLUMN = "mutations_json"


async def up(db: aiosqlite.Connection) -> None:
    """Give retained creator rows an empty collection; reconstruct no provider effects."""
    cursor = await db.execute(_TABLE_INFO)
    columns = await cursor.fetchall()
    if not any(column[1] == _MUTATIONS_COLUMN for column in columns):
        await db.execute(_ADD_MUTATIONS)
    await db.commit()
