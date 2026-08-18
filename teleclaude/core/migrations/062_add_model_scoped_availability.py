"""Add model-scoped agent availability records."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Migrate availability rows to the composite agent/model identity."""
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.executescript(
            """
            CREATE TABLE agent_availability_model_scoped (
                agent TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                available INTEGER DEFAULT 1,
                unavailable_until TEXT,
                reason TEXT,
                degraded_until TEXT,
                PRIMARY KEY (agent, model)
            );

            INSERT INTO agent_availability_model_scoped (
                agent, model, available, unavailable_until, reason, degraded_until
            )
            SELECT agent, '', available, unavailable_until, reason, degraded_until
            FROM agent_availability;

            DROP TABLE agent_availability;
            ALTER TABLE agent_availability_model_scoped RENAME TO agent_availability;
            """
        )
        await db.commit()
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def down(db: aiosqlite.Connection) -> None:
    """Owned availability state migrates forward only."""
