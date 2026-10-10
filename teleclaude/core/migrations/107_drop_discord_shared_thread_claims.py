"""Drop the shared Discord child claim ledger tables."""

from __future__ import annotations

import aiosqlite

_DROP_STATEMENTS = (
    "DROP TABLE IF EXISTS discord_thread_orphan_candidates",
    "DROP TABLE IF EXISTS discord_thread_claim_inventory_items",
    "DROP TABLE IF EXISTS discord_thread_reconciliation_epochs",
    "DROP TABLE IF EXISTS discord_thread_claim_members",
    "DROP TABLE IF EXISTS discord_shared_thread_owners",
    "DROP TABLE IF EXISTS discord_shared_thread_contenders",
)


async def up(db: aiosqlite.Connection) -> None:
    """Remove the tables no shared-forum code reads or writes."""
    for statement in _DROP_STATEMENTS:
        await db.execute(statement)  # guard: raw-sql
    await db.commit()
