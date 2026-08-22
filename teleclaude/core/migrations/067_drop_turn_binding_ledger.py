"""Migrate output generations to native identity before retiring receipt bindings."""

from __future__ import annotations

import aiosqlite

_OUTPUT_GENERATION_COLUMNS_SQL = "SELECT name FROM pragma_table_info('output_generations')"
_NATIVE_RUNTIME_COLUMN = "native_runtime"
_NATIVE_SESSION_COLUMN = "native_session_id"
_NATIVE_ENTRY_COLUMN = "native_entry_id"
_ADD_NATIVE_RUNTIME_SQL = "ALTER TABLE output_generations ADD COLUMN native_runtime TEXT"
_ADD_NATIVE_SESSION_SQL = "ALTER TABLE output_generations ADD COLUMN native_session_id TEXT"
_ADD_NATIVE_ENTRY_SQL = "ALTER TABLE output_generations ADD COLUMN native_entry_id TEXT"
_CONTROL_DELIVERY_COLUMNS_SQL = "SELECT name FROM pragma_table_info('control_outbox')"
_CONTROL_ENVELOPE_NAME_COLUMN = "envelope_name"
_CONTROL_ENVELOPE_FIELDS_COLUMN = "envelope_fields_json"
_ADD_CONTROL_ENVELOPE_NAME_SQL = "ALTER TABLE control_outbox ADD COLUMN envelope_name TEXT"
_ADD_CONTROL_ENVELOPE_FIELDS_SQL = "ALTER TABLE control_outbox ADD COLUMN envelope_fields_json TEXT"
_INBOUND_COLUMNS_SQL = "SELECT name FROM pragma_table_info('inbound_queue')"
_BINDING_DISPOSITION_COLUMN = "binding_disposition"
_DROP_BINDING_DISPOSITION_SQL = "ALTER TABLE inbound_queue DROP COLUMN binding_disposition"
_DROP_LEDGER_TABLES_SQL = """
DROP TABLE IF EXISTS turn_receipt_envelopes;
DROP TABLE IF EXISTS turn_authored_parts;
DROP TABLE IF EXISTS binding_conflict_candidates;
DROP TABLE IF EXISTS accepted_turn_bindings;
"""
_BACKFILL_GENERATIONS_SQL = """
UPDATE output_generations
SET native_runtime = (
        SELECT native_runtime FROM accepted_turn_bindings
        WHERE accepted_turn_bindings.binding_id = output_generations.binding_id
    ),
    native_session_id = (
        SELECT native_session_id FROM accepted_turn_bindings
        WHERE accepted_turn_bindings.binding_id = output_generations.binding_id
    ),
    native_entry_id = (
        SELECT native_entry_id FROM accepted_turn_bindings
        WHERE accepted_turn_bindings.binding_id = output_generations.binding_id
    )
WHERE binding_id IS NOT NULL;
"""
_UNRESOLVED_BINDING_GENERATIONS_SQL = """
SELECT count(*) FROM output_generations
WHERE binding_id IS NOT NULL
  AND (native_runtime IS NULL OR native_session_id IS NULL OR native_entry_id IS NULL)
"""


async def _output_generation_columns(db: aiosqlite.Connection) -> set[str]:
    """Read the current output-generation shape before mutating it."""
    async with db.execute(_OUTPUT_GENERATION_COLUMNS_SQL) as cursor:  # guard: raw-sql
        rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


async def up(db: aiosqlite.Connection) -> None:
    """Add native identity columns before the later destructive ledger cutover."""
    columns = await _output_generation_columns(db)
    if _NATIVE_RUNTIME_COLUMN not in columns:
        await db.execute(_ADD_NATIVE_RUNTIME_SQL)  # guard: raw-sql
    if _NATIVE_SESSION_COLUMN not in columns:
        await db.execute(_ADD_NATIVE_SESSION_SQL)  # guard: raw-sql
    if _NATIVE_ENTRY_COLUMN not in columns:
        await db.execute(_ADD_NATIVE_ENTRY_SQL)  # guard: raw-sql
    await db.executescript(_BACKFILL_GENERATIONS_SQL)  # guard: raw-sql
    async with db.execute(_UNRESOLVED_BINDING_GENERATIONS_SQL) as cursor:  # guard: raw-sql
        unresolved_binding_generations = int((await cursor.fetchone())[0])
    if unresolved_binding_generations:
        raise RuntimeError("binding-backed output generations could not be resolved to native identity")
    async with db.execute(_CONTROL_DELIVERY_COLUMNS_SQL) as cursor:  # guard: raw-sql
        control_columns = {str(row[0]) for row in await cursor.fetchall()}
    if _CONTROL_ENVELOPE_NAME_COLUMN not in control_columns:
        await db.execute(_ADD_CONTROL_ENVELOPE_NAME_SQL)  # guard: raw-sql
    if _CONTROL_ENVELOPE_FIELDS_COLUMN not in control_columns:
        await db.execute(_ADD_CONTROL_ENVELOPE_FIELDS_SQL)  # guard: raw-sql
    async with db.execute(_INBOUND_COLUMNS_SQL) as cursor:  # guard: raw-sql
        inbound_columns = {str(row[0]) for row in await cursor.fetchall()}
    if _BINDING_DISPOSITION_COLUMN in inbound_columns:
        await db.execute(_DROP_BINDING_DISPOSITION_SQL)  # guard: raw-sql
    await db.executescript(_DROP_LEDGER_TABLES_SQL)  # guard: raw-sql
    await db.commit()


async def down(db: aiosqlite.Connection) -> None:
    """Owned SQLite state migrates forward only."""
    _ = db
