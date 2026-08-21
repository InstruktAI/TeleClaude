"""Add the control-delivery outbox owned independently from conversational input."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create durable control payload storage and its empty-path index."""
    await db.executescript(
        """
        CREATE TABLE control_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            body TEXT NOT NULL,
            body_digest TEXT NOT NULL,
            source_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            outcome TEXT CHECK(outcome IN ('delivered', 'failed')),
            terminal_at TEXT,
            CHECK(
                (outcome IS NULL AND terminal_at IS NULL)
                OR (outcome IS NOT NULL AND terminal_at IS NOT NULL)
            )
        );
        CREATE INDEX idx_control_outbox_pending_session
            ON control_outbox(session_id, id)
            WHERE outcome IS NULL;
        CREATE UNIQUE INDEX idx_control_outbox_source_key ON control_outbox(source_key);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
