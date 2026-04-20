"""Add conversation_delivery_state table."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create the directional delivery cursor table."""
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversation_delivery_state (
            link_id TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL,
            delivered_through_ts TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (link_id, source_session_id, target_session_id),
            FOREIGN KEY (link_id) REFERENCES conversation_links(link_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_conversation_delivery_source_target
        ON conversation_delivery_state(source_session_id, target_session_id);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """SQLite does not support DROP TABLE in reversible migrations here — no-op."""
