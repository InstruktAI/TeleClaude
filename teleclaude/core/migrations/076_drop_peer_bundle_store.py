"""Remove retired peer-bundle storage and delivery-refusal state."""

from __future__ import annotations

import aiosqlite

_BUNDLE_SEGMENTS_TABLE = "peer_bundle_segments"
_BUNDLES_TABLE = "peer_bundles"
_DELIVERY_STATE_TABLE = "conversation_delivery_state"
_DELIVERY_DISPOSITION_COLUMNS = (
    "disposition",
    "disposition_entry_ref",
    "disposition_reason",
)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    """Return whether the owned SQLite table still exists."""
    async with db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)) as cursor:
        return await cursor.fetchone() is not None


async def up(db: aiosqlite.Connection) -> None:
    """Migrate owned delivery storage to the current text-only contract."""
    for table_name in (_BUNDLE_SEGMENTS_TABLE, _BUNDLES_TABLE):
        if await _table_exists(db, table_name):
            await db.execute(f"DROP TABLE {table_name}")  # guard: static migration declaration
    async with db.execute(f"PRAGMA table_info({_DELIVERY_STATE_TABLE})") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    for column_name in _DELIVERY_DISPOSITION_COLUMNS:
        if column_name in columns:
            await db.execute(
                f"ALTER TABLE {_DELIVERY_STATE_TABLE} DROP COLUMN {column_name}"
            )  # guard: static migration declaration
    await db.commit()
