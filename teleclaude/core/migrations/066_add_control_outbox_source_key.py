"""Add producer-owned control delivery deduplication keys."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Migrate existing rows to stable synthetic source keys before enforcing uniqueness."""
    await db.executescript(
        """
        ALTER TABLE control_outbox ADD COLUMN source_key TEXT;
        UPDATE control_outbox SET source_key = 'legacy:' || id WHERE source_key IS NULL;
        CREATE UNIQUE INDEX idx_control_outbox_source_key ON control_outbox(source_key);
        """
    )
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
