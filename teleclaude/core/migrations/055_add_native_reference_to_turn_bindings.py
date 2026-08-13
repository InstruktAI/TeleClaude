"""Add the runtime-qualified native reference to accepted-turn bindings.

Task 2's binding schema recorded the injected span but not which native
transcript entry it belongs to. Per the Turn provenance invariant "native
references survive runtime boundaries" (a positional file or entry index is
never durable identity), a binding needs the runtime, the runtime's own
native-session identity, and the runtime's own stable entry id — not a file
offset or line number.
"""

from __future__ import annotations

import aiosqlite

_NEW_COLUMNS = (
    ("native_runtime", "TEXT"),
    ("native_session_id", "TEXT"),
    ("native_entry_id", "TEXT"),
)


async def up(db: aiosqlite.Connection) -> None:
    """Add native-reference columns and the one-binding-per-entry uniqueness guard."""
    async with db.execute("SELECT name FROM pragma_table_info('accepted_turn_bindings')") as cursor:
        rows = await cursor.fetchall()
    existing_columns = {str(row[0]) for row in rows}
    for column_name, column_type in _NEW_COLUMNS:
        if column_name in existing_columns:
            continue
        await db.execute(  # guard: raw-sql
            f"ALTER TABLE accepted_turn_bindings ADD COLUMN {column_name} {column_type}"
        )

    await db.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_accepted_turn_bindings_native_entry
        ON accepted_turn_bindings(native_runtime, native_session_id, native_entry_id)
        WHERE native_entry_id IS NOT NULL;
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
