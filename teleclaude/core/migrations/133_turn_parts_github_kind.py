"""Admit the GitHub comment part kind and its author channel facts on turn authored parts."""

from __future__ import annotations

import aiosqlite

_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'turn_authored_parts'"
_REBUILD_SQL = """
CREATE TABLE turn_authored_parts_rebuilt (
    binding_id TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL CHECK(part_kind IN ('local', 'caller', 'peer', 'github')),
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    original_source_session_id TEXT,
    author_kind TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_agent_runtime TEXT,
    author_thinking_mode TEXT,
    author_machine_role TEXT,
    author_job_role TEXT,
    author_channel_login TEXT,
    author_channel_link TEXT,
    PRIMARY KEY (binding_id, part_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
);
INSERT INTO turn_authored_parts_rebuilt (
    binding_id, part_id, part_kind, span_start, span_end, original_source_session_id,
    author_kind, author_display, author_agent_runtime, author_thinking_mode,
    author_machine_role, author_job_role
)
SELECT
    binding_id, part_id, part_kind, span_start, span_end, original_source_session_id,
    author_kind, author_display, author_agent_runtime, author_thinking_mode,
    author_machine_role, author_job_role
FROM turn_authored_parts;
DROP TABLE turn_authored_parts;
ALTER TABLE turn_authored_parts_rebuilt RENAME TO turn_authored_parts;
"""


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild the parts table, since SQLite cannot alter a CHECK constraint, keeping every row."""
    async with db.execute(_TABLE_EXISTS_SQL) as cursor:  # guard: raw-sql
        if await cursor.fetchone() is None:
            return
    await db.executescript(_REBUILD_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
