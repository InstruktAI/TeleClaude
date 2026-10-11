"""Record accepted wake correlation and the idle snapshot used at delivery admission."""

from __future__ import annotations

import aiosqlite

_TABLE_NAME = "procedure_event_delivery_sessions"
_TABLE_INFO_SQL = f"SELECT name FROM pragma_table_info('{_TABLE_NAME}')"
_BEGIN_SQL = "BEGIN"
_ALTER_COLUMN_SQL = "ALTER TABLE {table} ADD COLUMN {column} {declaration}"
_WAKE_ACCEPTED_OCCURRENCE_ID = "wake_accepted_occurrence_id"
_WAKE_OBSERVED_LAST_INPUT_AT = "wake_observed_last_input_at"
_WAKE_OBSERVED_LAST_AGENT_STOP_AT = "wake_observed_last_agent_stop_at"
_WAKE_OBSERVED_LAST_AGENT_IDLE_AT = "wake_observed_last_agent_idle_at"
_WAKE_OBSERVED_INBOUND_ID = "wake_observed_inbound_id"
_COLUMNS = (
    (_WAKE_ACCEPTED_OCCURRENCE_ID, "TEXT"),
    (_WAKE_OBSERVED_LAST_INPUT_AT, "TEXT"),
    (_WAKE_OBSERVED_LAST_AGENT_STOP_AT, "TEXT"),
    (_WAKE_OBSERVED_LAST_AGENT_IDLE_AT, "TEXT"),
    (_WAKE_OBSERVED_INBOUND_ID, "INTEGER"),
)


async def up(db: aiosqlite.Connection) -> None:
    """Add persisted correlation for admission of content-free wake opportunities."""
    async with db.execute(_TABLE_INFO_SQL) as cursor:
        rows = await cursor.fetchall()
    existing = {str(row[0]) for row in rows}
    await db.execute(_BEGIN_SQL)
    try:
        for column, declaration in _COLUMNS:
            if column not in existing:
                await db.execute(_ALTER_COLUMN_SQL.format(table=_TABLE_NAME, column=column, declaration=declaration))
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
