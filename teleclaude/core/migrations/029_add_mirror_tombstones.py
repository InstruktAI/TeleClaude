"""Add tombstones for empty transcripts so reconciliation converges."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Create empty-transcript tombstones."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS mirror_tombstones (
            source_identity TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            transcript_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_mtime TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Drop empty-transcript tombstones."""
    await db.execute("DROP TABLE IF EXISTS mirror_tombstones")
    await db.commit()
