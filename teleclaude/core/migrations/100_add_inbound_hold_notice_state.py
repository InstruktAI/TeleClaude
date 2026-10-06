"""Persist retry state for held-message expiry notices."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO_SQL = "PRAGMA table_info(inbound_queue)"
_COLUMNS = (
    ("hold_notice_pending", "ALTER TABLE inbound_queue ADD COLUMN hold_notice_pending INTEGER NOT NULL DEFAULT 0"),
    (
        "hold_notice_attempt_count",
        "ALTER TABLE inbound_queue ADD COLUMN hold_notice_attempt_count INTEGER NOT NULL DEFAULT 0",
    ),
    ("hold_notice_next_retry_at", "ALTER TABLE inbound_queue ADD COLUMN hold_notice_next_retry_at TEXT"),
    ("hold_notice_error", "ALTER TABLE inbound_queue ADD COLUMN hold_notice_error TEXT"),
)


async def up(db: aiosqlite.Connection) -> None:
    """Add each notice-recovery field to existing inbound databases once."""
    async with db.execute(_TABLE_INFO_SQL) as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    for column_name, column_sql in _COLUMNS:
        if column_name not in columns:
            await db.execute(column_sql)  # guard: raw-sql
    await db.commit()
