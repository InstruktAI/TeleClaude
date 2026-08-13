"""Add accepted-row caller provenance and accepted-turn binding tables.

Two owned-data changes land in one migration because both are accepted-input
state and the same durable contract binds them to the same row:

1. Accepted-row caller provenance columns on ``inbound_queue`` — the caller's
   event-author class and runtime/role qualifiers, present at acceptance,
   before any transcript entry exists to bind to.
2. ``accepted_turn_bindings`` / ``turn_authored_parts`` — the durable link from
   an accepted receipt to its native transcript turn, with the turn's ordered
   authored parts.

A row written by the old shape and bound by the new one is the half-migrated
state this single migration exists to prevent.
"""

from __future__ import annotations

import aiosqlite

_NEW_INBOUND_QUEUE_COLUMNS = (
    ("caller_session_id", "TEXT"),
    ("caller_author_kind", "TEXT"),
    ("caller_author_display", "TEXT"),
    ("caller_agent_runtime", "TEXT"),
    ("caller_thinking_mode", "TEXT"),
    ("caller_machine_role", "TEXT"),
    ("caller_job_role", "TEXT"),
)


async def up(db: aiosqlite.Connection) -> None:
    """Add accepted-row caller provenance columns and the binding tables."""
    async with db.execute("SELECT name FROM pragma_table_info('inbound_queue')") as cursor:
        rows = await cursor.fetchall()
    existing_columns = {str(row[0]) for row in rows}
    for column_name, column_type in _NEW_INBOUND_QUEUE_COLUMNS:
        if column_name in existing_columns:
            continue
        await db.execute(f"ALTER TABLE inbound_queue ADD COLUMN {column_name} {column_type}")  # guard: raw-sql

    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS accepted_turn_bindings (
            binding_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            inbound_queue_id INTEGER NOT NULL,
            injected_span_start INTEGER,
            injected_span_end INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_accepted_turn_bindings_inbound
        ON accepted_turn_bindings(inbound_queue_id);

        CREATE INDEX IF NOT EXISTS idx_accepted_turn_bindings_session
        ON accepted_turn_bindings(session_id);

        CREATE TABLE IF NOT EXISTS turn_authored_parts (
            binding_id TEXT NOT NULL,
            part_id INTEGER NOT NULL,
            part_kind TEXT NOT NULL CHECK(part_kind IN ('local', 'injected_peer')),
            span_start INTEGER NOT NULL,
            span_end INTEGER NOT NULL,
            original_source_session_id TEXT NOT NULL,
            author_kind TEXT NOT NULL CHECK(author_kind IN ('human', 'agent', 'machine')),
            author_display TEXT NOT NULL,
            author_agent_runtime TEXT,
            author_thinking_mode TEXT,
            author_machine_role TEXT,
            author_job_role TEXT,
            PRIMARY KEY (binding_id, part_id),
            FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_turn_authored_parts_source
        ON turn_authored_parts(original_source_session_id);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP COLUMN — no-op."""
