"""Give a spawn registry row the identity a process needs to be told from another.

A detached child registered with a bare pid is told from a reused pid by nothing. A row that carries the
process's start identity, the computer and boot session it ran in, and the generation that registered it lets a
later process classify it without a clock or a group number
(``local/projects/teleclaude/design/process-lifecycle``). The four columns are nullable; every existing row, the
chiptunes worker's included, keeps them empty and keeps its pid-only semantics.
"""

from __future__ import annotations

import aiosqlite

_COLUMNS_SQL = "SELECT name FROM pragma_table_info('process_spawn_registry')"
_ADD_COLUMN_SQL = "ALTER TABLE process_spawn_registry ADD COLUMN {column} TEXT"
_NEW_COLUMNS = ("identity", "host", "boot", "generation")


async def up(db: aiosqlite.Connection) -> None:
    """Add each nullable identity column that is absent; every stored row keeps its state."""
    async with db.execute(_COLUMNS_SQL) as cursor:
        existing = {str(row[0]) for row in await cursor.fetchall()}
    for column in _NEW_COLUMNS:
        if column not in existing:
            await db.execute(_ADD_COLUMN_SQL.format(column=column))
    await db.commit()
