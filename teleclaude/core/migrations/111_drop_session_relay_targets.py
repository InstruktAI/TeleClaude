"""Drop private relay targets and advance stored exchange roles to desk-scope people."""

from __future__ import annotations

import aiosqlite

_TABLE_INFO_SQL = "PRAGMA table_info(sessions)"
_COLUMN = "relay_targets"
_DROP_COLUMN_SQL = "ALTER TABLE sessions DROP COLUMN relay_targets"
_ADMIN_ROLE_JSON = '"role": "Admin"'
_PERSON_ROLE_JSON = '"role": "Person"'
_REWRITE_EXCHANGE_ROLE_SQL = (
    "UPDATE sessions SET relay_exchange = replace(relay_exchange, ?, ?) WHERE instr(relay_exchange, ?) > 0"
)


async def up(db: aiosqlite.Connection) -> None:
    """Remove the target column and migrate the exchange's answerer role."""
    async with db.execute(_TABLE_INFO_SQL) as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN in columns:
        await db.execute(_DROP_COLUMN_SQL)  # guard: raw-sql
    await db.execute(_REWRITE_EXCHANGE_ROLE_SQL, (_ADMIN_ROLE_JSON, _PERSON_ROLE_JSON, _ADMIN_ROLE_JSON))
    await db.commit()
