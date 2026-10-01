"""Add the mesh master's durable conversation bindings, adoption sources and orphan record."""

from __future__ import annotations

import aiosqlite

_CONVERSATION_BINDING_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS conversation_bindings (
    origin TEXT NOT NULL,
    key_field TEXT NOT NULL,
    conversation_key TEXT NOT NULL,
    host TEXT NOT NULL,
    session_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    entered_at TEXT NOT NULL,
    PRIMARY KEY (origin, key_field, conversation_key)
);
CREATE TABLE IF NOT EXISTS conversation_bindings_adoption (
    computer TEXT PRIMARY KEY,
    answered_at TEXT
);
CREATE TABLE IF NOT EXISTS conversation_binding_orphans (
    session_id TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Create the binding record the mesh master routes shared-adapter conversations from."""
    await db.executescript(_CONVERSATION_BINDING_TABLES_SQL)
    await db.commit()
