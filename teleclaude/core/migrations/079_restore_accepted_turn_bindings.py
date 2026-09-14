"""Restore accepted-occurrence bindings after the ledger retirement."""

from __future__ import annotations

import aiosqlite

_INBOUND_COLUMNS_SQL = "SELECT name FROM pragma_table_info('inbound_queue')"
_BINDING_COLUMN = "binding_disposition"
_ADD_BINDING_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN binding_disposition TEXT"
_MARK_LEGACY_SQL = """
UPDATE inbound_queue
SET binding_disposition = 'legacy_pre_cutover'
WHERE status = 'delivered' AND binding_disposition IS NULL
"""
_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS accepted_turn_bindings (
    binding_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, native_runtime TEXT NOT NULL,
    native_session_id TEXT NOT NULL, native_entry_id TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(native_runtime, native_session_id, native_entry_id)
);
CREATE TABLE IF NOT EXISTS turn_receipt_envelopes (
    binding_id TEXT NOT NULL, inbound_queue_id INTEGER NOT NULL, envelope_index INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL, envelope_span_start INTEGER NOT NULL, envelope_span_end INTEGER NOT NULL,
    body_span_start INTEGER NOT NULL, body_span_end INTEGER NOT NULL, authored_part_id INTEGER,
    PRIMARY KEY(binding_id, inbound_queue_id, envelope_index), UNIQUE(inbound_queue_id)
);
CREATE TABLE IF NOT EXISTS binding_conflict_candidates (
    inbound_queue_id INTEGER NOT NULL, native_runtime TEXT NOT NULL, native_session_id TEXT NOT NULL,
    native_entry_id TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(inbound_queue_id, native_runtime, native_session_id, native_entry_id)
);
CREATE TABLE IF NOT EXISTS turn_authored_parts (
    binding_id TEXT NOT NULL, part_id INTEGER NOT NULL,
    part_kind TEXT NOT NULL CHECK(part_kind IN ('local', 'caller', 'peer')),
    span_start INTEGER NOT NULL, span_end INTEGER NOT NULL, original_source_session_id TEXT,
    author_kind TEXT NOT NULL, author_display TEXT NOT NULL, author_agent_runtime TEXT,
    author_thinking_mode TEXT, author_machine_role TEXT, author_job_role TEXT,
    PRIMARY KEY(binding_id, part_id)
);
CREATE INDEX IF NOT EXISTS idx_accepted_turn_bindings_session ON accepted_turn_bindings(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turn_receipt_envelopes_binding ON turn_receipt_envelopes(binding_id);
"""


async def up(db: aiosqlite.Connection) -> None:
    """Install the current durable shape and mark pre-restoration deliveries legacy."""
    async with db.execute(_INBOUND_COLUMNS_SQL) as cursor:  # guard: raw-sql
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _BINDING_COLUMN not in columns:
        await db.execute(_ADD_BINDING_COLUMN_SQL)  # guard: raw-sql
    await db.executescript(_LEDGER_SQL)  # guard: raw-sql
    await db.execute(_MARK_LEGACY_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned persisted shape only migrates forward."""
    _ = db
