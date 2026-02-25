"""Add conversation link tables for direct and gathering conversations."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Apply migration - create link and member tables."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_links (
            link_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL CHECK(mode IN ('direct_link', 'gathering_link')),
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'closed')),
            created_by_session_id TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            closed_at TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_links_status
            ON conversation_links(status)
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_link_members (
            link_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            participant_name TEXT,
            participant_number INTEGER,
            participant_role TEXT,
            computer_name TEXT,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (link_id, session_id),
            FOREIGN KEY (link_id) REFERENCES conversation_links(link_id) ON DELETE CASCADE
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversation_link_members_session
            ON conversation_link_members(session_id)
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Revert migration."""
    await db.execute("DROP INDEX IF EXISTS idx_conversation_link_members_session")
    await db.execute("DROP TABLE IF EXISTS conversation_link_members")
    await db.execute("DROP INDEX IF EXISTS idx_conversation_links_status")
    await db.execute("DROP TABLE IF EXISTS conversation_links")
    await db.commit()
