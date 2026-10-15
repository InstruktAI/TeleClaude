"""The converted-row record's insert: made in the transaction of the conversion it records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core.todos_db._activation_schema import CONVERTED_TABLE

_INSERT_CONVERTED = (
    f"INSERT OR IGNORE INTO {CONVERTED_TABLE} (row_id, replaced_phase, converted_at, path) "
    "VALUES (:row_id, :replaced_phase, :converted_at, :path)"
)


_SELECT_ONE = f"SELECT 1 FROM {CONVERTED_TABLE} WHERE row_id = :row_id"


async def is_converted_row(session: SqlAsyncSession, row_id: str) -> bool:
    """Whether the converted-row record holds the row: it was converted to the machine's vocabulary."""
    connection = await session.connection()
    return (await connection.execute(text(_SELECT_ONE), {"row_id": row_id})).first() is not None  # guard: raw-sql


async def insert_converted_row(
    session: SqlAsyncSession, row_id: str, replaced_phase: str, path: str, *, at: str | None = None
) -> None:
    """Record one conversion; the record is history and is never updated."""
    connection = await session.connection()
    await connection.execute(  # guard: raw-sql
        text(_INSERT_CONVERTED),
        {
            "row_id": row_id,
            "replaced_phase": replaced_phase,
            "converted_at": at or datetime.now(UTC).isoformat(),
            "path": path,
        },
    )
