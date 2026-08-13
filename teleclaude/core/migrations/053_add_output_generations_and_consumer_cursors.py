"""Add durable output generation, per-consumer cursor, and receipt tables.

A generation identity is what lets an adapter edit only its own in-flight
message; per-consumer cursors are what stop one consumer's delivery progress
from muting another's.
"""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create the generation, consumer cursor, and consumer receipt tables."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS output_generations (
            generation_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            binding_id TEXT,
            is_legacy INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_output_generations_session
        ON output_generations(session_id, created_at);

        CREATE TABLE IF NOT EXISTS output_consumer_cursors (
            session_id TEXT NOT NULL,
            consumer TEXT NOT NULL,
            generation_id TEXT,
            char_offset INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, consumer)
        );

        CREATE TABLE IF NOT EXISTS output_consumer_receipts (
            session_id TEXT NOT NULL,
            consumer TEXT NOT NULL,
            generation_id TEXT NOT NULL,
            platform_message_id TEXT,
            delivered_char_offset INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, consumer, generation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_output_consumer_receipts_session_consumer
        ON output_consumer_receipts(session_id, consumer, updated_at DESC);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
