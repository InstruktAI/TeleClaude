"""Add the durable, master-held claim ledger for shared Discord children."""

from __future__ import annotations

import aiosqlite

_CLAIM_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS discord_shared_thread_contenders (
    thread_id INTEGER NOT NULL,
    computer TEXT NOT NULL,
    parent_id INTEGER NOT NULL,
    child_kind TEXT NOT NULL,
    local_identity TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    protocol_generation INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, computer)
);
CREATE TABLE IF NOT EXISTS discord_shared_thread_owners (
    thread_id INTEGER PRIMARY KEY,
    parent_id INTEGER NOT NULL,
    child_kind TEXT NOT NULL,
    owner_computer TEXT NOT NULL,
    local_identity TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    protocol_generation INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS discord_thread_claim_members (
    computer TEXT PRIMARY KEY,
    protocol_generation INTEGER NOT NULL,
    adoption_state TEXT NOT NULL,
    inventory_completed_epoch INTEGER,
    first_observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    inventory_completed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS discord_thread_reconciliation_epochs (
    protocol_generation INTEGER PRIMARY KEY,
    current_epoch INTEGER NOT NULL,
    phase TEXT NOT NULL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS discord_thread_claim_inventory_items (
    computer TEXT NOT NULL,
    protocol_generation INTEGER NOT NULL,
    inventory_epoch INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    parent_id INTEGER NOT NULL,
    child_kind TEXT NOT NULL,
    local_identity TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    PRIMARY KEY (computer, protocol_generation, inventory_epoch, thread_id)
);
CREATE TABLE IF NOT EXISTS discord_thread_orphan_candidates (
    thread_id INTEGER PRIMARY KEY,
    parent_id INTEGER NOT NULL,
    first_qualifying_epoch INTEGER NOT NULL,
    last_qualifying_epoch INTEGER NOT NULL,
    consecutive_complete_epochs INTEGER NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Move owned Discord child ownership state to the current durable schema."""
    await db.executescript(_CLAIM_TABLES_SQL)  # guard: static migration declaration
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted state migrates forward only."""
    _ = db
