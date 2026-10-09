"""Drop the retired hook-service contract and outbound-delivery tables."""

from __future__ import annotations

import aiosqlite

_DROP_STATEMENTS = (
    "DROP INDEX IF EXISTS idx_webhook_contracts_active",
    "DROP INDEX IF EXISTS idx_webhook_outbox_status",
    "DROP INDEX IF EXISTS idx_webhook_outbox_next_attempt",
    "DROP TABLE IF EXISTS webhook_outbox",
    "DROP TABLE IF EXISTS webhook_contracts",
)


async def up(db: aiosqlite.Connection) -> None:
    """Remove the tables no hook-service code reads or writes, with their indexes."""
    for statement in _DROP_STATEMENTS:
        await db.execute(statement)  # guard: raw-sql
    await db.commit()
