"""Add mirrors table and FTS index for conversation search."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create mirror storage and FTS triggers."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS mirrors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE,
            computer TEXT NOT NULL,
            agent TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            timestamp_start TEXT,
            timestamp_end TEXT,
            conversation_text TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project)")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC)")
    await db.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS mirrors_fts USING fts5(
            title,
            conversation_text,
            content='mirrors',
            content_rowid='id'
        )
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_ai AFTER INSERT ON mirrors BEGIN
            INSERT INTO mirrors_fts(rowid, title, conversation_text)
            VALUES (new.id, new.title, new.conversation_text);
        END
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_ad AFTER DELETE ON mirrors BEGIN
            INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
            VALUES ('delete', old.id, old.title, old.conversation_text);
        END
        """
    )
    await db.execute(
        """
        CREATE TRIGGER IF NOT EXISTS mirrors_au AFTER UPDATE ON mirrors BEGIN
            INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
            VALUES ('delete', old.id, old.title, old.conversation_text);
            INSERT INTO mirrors_fts(rowid, title, conversation_text)
            VALUES (new.id, new.title, new.conversation_text);
        END
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop mirror storage and FTS triggers."""
    await db.execute("DROP TRIGGER IF EXISTS mirrors_au")
    await db.execute("DROP TRIGGER IF EXISTS mirrors_ad")
    await db.execute("DROP TRIGGER IF EXISTS mirrors_ai")
    await db.execute("DROP TABLE IF EXISTS mirrors_fts")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_timestamp")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_project")
    await db.execute("DROP INDEX IF EXISTS idx_mirrors_agent")
    await db.execute("DROP TABLE IF EXISTS mirrors")
    await db.commit()
