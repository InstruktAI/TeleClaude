"""Record on each inbound row the session clock instant and turn identity its acceptance wrote.

A control wake that ends undelivered retires only its own acceptance: the settlement compares the session's
recorded input clock and runtime turn identity against what the wake's acceptance recorded. Rows accepted before
this migration carry neither value and are never settled. See
``local/projects/teleclaude/spec/feature/agent_runtime/control-delivery``.
"""

from __future__ import annotations

from typing import Final

import aiosqlite

_COLUMNS_SQL: Final = "SELECT name FROM pragma_table_info('inbound_queue')"
_ADD_COLUMN_SQL_TEMPLATE: Final = "ALTER TABLE inbound_queue ADD COLUMN {column} TEXT"
_EVIDENCE_COLUMNS: Final = ("accepted_input_at", "accepted_runtime_turn_id")


async def up(db: aiosqlite.Connection) -> None:
    """Add the two nullable evidence columns to ``inbound_queue`` when they are absent."""
    async with db.execute(_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    for column in _EVIDENCE_COLUMNS:
        if column not in existing:
            await db.execute(_ADD_COLUMN_SQL_TEMPLATE.format(column=column))
    await db.commit()
