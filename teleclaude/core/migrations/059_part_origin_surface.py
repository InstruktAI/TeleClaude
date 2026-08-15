"""Allow a human UI turn to carry a surface origin without a source session."""

from __future__ import annotations

import aiosqlite

_CREATE_TABLE_SQL = """
CREATE TABLE turn_authored_parts_new (
    binding_id TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    original_source_session_id TEXT,
    author_kind TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_agent_runtime TEXT,
    author_thinking_mode TEXT,
    author_machine_role TEXT,
    author_job_role TEXT,
    origin_surface TEXT,
    PRIMARY KEY (binding_id, part_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
)
"""
_COPY_ROWS_SQL = """
INSERT INTO turn_authored_parts_new (
    binding_id, part_id, part_kind, span_start, span_end,
    original_source_session_id, author_kind, author_display,
    author_agent_runtime, author_thinking_mode, author_machine_role,
    author_job_role, origin_surface
)
SELECT
    binding_id, part_id, part_kind, span_start, span_end,
    original_source_session_id, author_kind, author_display,
    author_agent_runtime, author_thinking_mode, author_machine_role,
    author_job_role, NULL
FROM turn_authored_parts
"""
_SOURCE_INDEX_SQL = "CREATE INDEX idx_turn_authored_parts_source ON turn_authored_parts(original_source_session_id)"


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild owned turn parts with a nullable source and named UI surface."""
    async with db.execute("SELECT name FROM pragma_table_info('turn_authored_parts')") as cursor:
        existing_columns = {str(row[0]) for row in await cursor.fetchall()}
    if "origin_surface" in existing_columns:
        return
    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_COPY_ROWS_SQL)
        await db.execute("DROP TABLE turn_authored_parts")
        await db.execute("ALTER TABLE turn_authored_parts_new RENAME TO turn_authored_parts")
        await db.execute(_SOURCE_INDEX_SQL)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
