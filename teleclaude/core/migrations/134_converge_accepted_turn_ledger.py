"""Converge the accepted-turn ledger tables that an older schema left in a shape the binder cannot write.

Migration 079 created the aggregate with ``CREATE TABLE IF NOT EXISTS``, which does nothing to a table an earlier
``schema.sql`` run already created. A database that recreated the retired ledger before 079 therefore kept its
retired shape: nullable native identity on the root, a receipt table without ``envelope_index``, and a parts table
whose ``part_kind`` does not admit ``caller``. The binder's single transaction rolls back on every such table.

Each stale table is dropped, children before the root, and created as ``schema.sql`` declares it. A stale table holds
no committed row: every binding write inserts the root, its parts and its receipt in one transaction that the stale
shape rolls back, and no binder wrote between the retirement and 079. A table already in the current shape, or in any
later shape that still admits ``caller``, is left as it is.
"""

from __future__ import annotations

import aiosqlite

_BINDINGS = "accepted_turn_bindings"
_RECEIPTS = "turn_receipt_envelopes"
_PARTS = "turn_authored_parts"

_NATIVE_IDENTITY_COLUMNS = ("native_runtime", "native_session_id", "native_entry_id")


async def _columns(db: aiosqlite.Connection, table: str) -> dict[str, bool]:
    """Return each column of ``table`` with whether it is declared NOT NULL; empty when the table is absent."""
    async with db.execute('SELECT name, "notnull" FROM pragma_table_info(?)', (table,)) as cursor:  # guard: raw-sql
        return {str(row[0]): bool(row[1]) for row in await cursor.fetchall()}


async def _bindings_are_stale(db: aiosqlite.Connection) -> bool:
    """Whether the root table lets its native identity be NULL."""
    columns = await _columns(db, _BINDINGS)
    return bool(columns) and not all(columns.get(name, False) for name in _NATIVE_IDENTITY_COLUMNS)


async def _receipts_are_stale(db: aiosqlite.Connection) -> bool:
    """Whether the receipt table lacks the envelope order column."""
    columns = await _columns(db, _RECEIPTS)
    return bool(columns) and "envelope_index" not in columns


async def _parts_are_stale(db: aiosqlite.Connection) -> bool:
    """Whether the parts table's ``part_kind`` constraint does not admit ``caller``."""
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (_PARTS,)
    ) as cursor:  # guard: raw-sql
        row = await cursor.fetchone()
    return row is not None and "'caller'" not in str(row[0])


async def _create_bindings(db: aiosqlite.Connection) -> None:
    """Create the root table and its session index at the shape ``schema.sql`` declares."""
    await db.executescript(
        """
CREATE TABLE accepted_turn_bindings (
    binding_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(native_runtime, native_session_id, native_entry_id)
);
CREATE INDEX IF NOT EXISTS idx_accepted_turn_bindings_session ON accepted_turn_bindings(session_id, created_at);
"""
    )  # guard: raw-sql


async def _create_receipts(db: aiosqlite.Connection) -> None:
    """Create the receipt table and its binding index at the shape ``schema.sql`` declares."""
    await db.executescript(
        """
CREATE TABLE turn_receipt_envelopes (
    binding_id TEXT NOT NULL,
    inbound_queue_id INTEGER NOT NULL,
    envelope_index INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    envelope_span_start INTEGER NOT NULL,
    envelope_span_end INTEGER NOT NULL,
    body_span_start INTEGER NOT NULL,
    body_span_end INTEGER NOT NULL,
    authored_part_id INTEGER,
    PRIMARY KEY (binding_id, inbound_queue_id, envelope_index),
    UNIQUE (inbound_queue_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE,
    FOREIGN KEY (inbound_queue_id) REFERENCES inbound_queue(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_turn_receipt_envelopes_binding ON turn_receipt_envelopes(binding_id);
"""
    )  # guard: raw-sql


async def _create_parts(db: aiosqlite.Connection) -> None:
    """Create the parts table at the shape ``schema.sql`` declares."""
    await db.executescript(
        """
CREATE TABLE turn_authored_parts (
    binding_id TEXT NOT NULL,
    part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL CHECK(part_kind IN ('local', 'caller', 'peer')),
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    original_source_session_id TEXT,
    author_kind TEXT NOT NULL,
    author_display TEXT NOT NULL,
    author_agent_runtime TEXT,
    author_thinking_mode TEXT,
    author_machine_role TEXT,
    author_job_role TEXT,
    PRIMARY KEY (binding_id, part_id),
    FOREIGN KEY (binding_id) REFERENCES accepted_turn_bindings(binding_id) ON DELETE CASCADE
);
"""
    )  # guard: raw-sql


async def up(db: aiosqlite.Connection) -> None:
    """Rebuild every stale aggregate table at the shape ``schema.sql`` declares."""
    bindings_stale = await _bindings_are_stale(db)
    receipts_stale = await _receipts_are_stale(db)
    parts_stale = await _parts_are_stale(db)
    if receipts_stale:
        await db.execute(f"DROP TABLE {_RECEIPTS}")  # guard: raw-sql
    if parts_stale:
        await db.execute(f"DROP TABLE {_PARTS}")  # guard: raw-sql
    if bindings_stale:
        await db.execute(f"DROP TABLE {_BINDINGS}")  # guard: raw-sql
        await _create_bindings(db)
    if receipts_stale:
        await _create_receipts(db)
    if parts_stale:
        await _create_parts(db)
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
