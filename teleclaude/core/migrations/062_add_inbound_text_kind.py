"""Persist the canonical transcript kind on every accepted inbound row."""

from __future__ import annotations

import aiosqlite

_COLUMN_NAME = "text_kind"
_COLUMN_SQL = "ALTER TABLE inbound_queue ADD COLUMN text_kind TEXT NOT NULL DEFAULT 'ordinary'"
_SOURCE_FEATURE_COLUMN = "source_feature"
_SOURCE_FEATURE_SQL = "ALTER TABLE inbound_queue ADD COLUMN source_feature TEXT NOT NULL DEFAULT ''"
_OCCURRENCE_KEY_COLUMN = "occurrence_key"
_OCCURRENCE_KEY_SQL = "ALTER TABLE inbound_queue ADD COLUMN occurrence_key TEXT"
_REMINDER_KIND = "reminder"
_IDENTITY_KIND = "identity_content"
_CONTROL_KIND = "platform_control"
_ORDINARY_KIND = "ordinary"
_CONTROL_OPENERS = (
    "[TeleClaude Checkpoint]",
    "[TeleClaude Notification]",
    "[TeleClaude Input Request]",
)
_CONTROL_UPDATE_SQL = "UPDATE inbound_queue SET text_kind = ? WHERE content LIKE ? OR content LIKE ? OR content LIKE ?"
_RECEIPT_ENVELOPES_SQL = (
    "CREATE TABLE IF NOT EXISTS turn_receipt_envelopes ("
    "binding_id TEXT NOT NULL, inbound_queue_id INTEGER NOT NULL, envelope_index INTEGER NOT NULL DEFAULT 0, occurrence_key TEXT NOT NULL, "
    "text_kind TEXT NOT NULL, envelope_span_start INTEGER NOT NULL, envelope_span_end INTEGER NOT NULL, "
    "body_span_start INTEGER NOT NULL, body_span_end INTEGER NOT NULL, authored_part_id INTEGER, "
    "PRIMARY KEY (binding_id, inbound_queue_id, envelope_index))"
)
_COPY_LEGACY_RECEIPTS_SQL = (
    "INSERT OR IGNORE INTO turn_receipt_envelopes ("
    "binding_id, inbound_queue_id, envelope_index, occurrence_key, text_kind, envelope_span_start, envelope_span_end, "
    "body_span_start, body_span_end, authored_part_id) "
    "SELECT binding_id, inbound_queue_id, 0, COALESCE(inbound_queue.occurrence_key, inbound_queue.source_message_id), inbound_queue.text_kind, "
    "injected_span_start, injected_span_end, injected_span_start, injected_span_end, NULL "
    "FROM accepted_turn_bindings JOIN inbound_queue ON inbound_queue.id = accepted_turn_bindings.inbound_queue_id "
    "WHERE inbound_queue_id IS NOT NULL AND injected_span_start IS NOT NULL AND injected_span_end IS NOT NULL "
    "AND COALESCE(inbound_queue.occurrence_key, inbound_queue.source_message_id) IS NOT NULL "
    "AND COALESCE(inbound_queue.occurrence_key, inbound_queue.source_message_id) != ''"
)
_LATEST_BINDINGS_SQL = (
    "CREATE TABLE accepted_turn_bindings_new ("
    "binding_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, native_runtime TEXT, native_session_id TEXT, "
    "native_entry_id TEXT, created_at TEXT NOT NULL)"
)
_COPY_LATEST_BINDINGS_SQL = (
    "INSERT INTO accepted_turn_bindings_new "
    "(binding_id, session_id, native_runtime, native_session_id, native_entry_id, created_at) "
    "SELECT binding_id, session_id, native_runtime, native_session_id, native_entry_id, created_at "
    "FROM accepted_turn_bindings"
)
_LATEST_BINDING_INDEXES_SQL = (
    "CREATE INDEX idx_accepted_turn_bindings_session ON accepted_turn_bindings(session_id);"
    "CREATE UNIQUE INDEX idx_accepted_turn_bindings_native_entry "
    "ON accepted_turn_bindings(native_runtime, native_session_id, native_entry_id) "
    "WHERE native_entry_id IS NOT NULL;"
)


async def up(db: aiosqlite.Connection) -> None:
    """Migrate owned inbound rows to the current closed text-kind contract."""
    async with db.execute("PRAGMA table_info(inbound_queue)") as cursor:
        columns = {str(row[1]) for row in await cursor.fetchall()}
    if _COLUMN_NAME not in columns:
        await db.execute(_COLUMN_SQL)  # guard: raw-sql
    if _SOURCE_FEATURE_COLUMN not in columns:
        await db.execute(_SOURCE_FEATURE_SQL)  # guard: raw-sql
    if _OCCURRENCE_KEY_COLUMN not in columns:
        await db.execute(_OCCURRENCE_KEY_SQL)  # guard: raw-sql
    await db.execute(
        "UPDATE inbound_queue SET occurrence_key = source_message_id WHERE occurrence_key IS NULL",
    )
    await db.execute(
        "UPDATE inbound_queue SET text_kind = ? WHERE message_type = ?",
        (_REMINDER_KIND, _REMINDER_KIND),
    )
    await db.execute(
        "UPDATE inbound_queue SET text_kind = ? WHERE caller_session_id IS NOT NULL",
        (_IDENTITY_KIND,),
    )
    await db.execute(
        _CONTROL_UPDATE_SQL,
        (_CONTROL_KIND, *(f"{opener}%" for opener in _CONTROL_OPENERS)),
    )
    await db.execute(
        "UPDATE inbound_queue SET text_kind = ? WHERE text_kind IS NULL OR text_kind = ''",
        (_ORDINARY_KIND,),
    )
    await db.execute(
        "UPDATE inbound_queue SET source_feature = CASE "
        "WHEN text_kind = 'reminder' THEN 'reminder' "
        "WHEN caller_session_id IS NOT NULL THEN 'caller_send' "
        "WHEN origin IN ('telegram', 'discord', 'whatsapp', 'web') THEN origin "
        "ELSE 'listener' END WHERE source_feature = ''",
    )
    await db.commit()
    await db.execute("PRAGMA foreign_keys=OFF")
    try:
        await db.execute("BEGIN")
        await db.execute(_RECEIPT_ENVELOPES_SQL)  # guard: raw-sql
        await db.execute(_COPY_LEGACY_RECEIPTS_SQL)  # guard: raw-sql
        async with db.execute("SELECT name FROM pragma_table_info('accepted_turn_bindings')") as cursor:
            binding_columns = {str(row[0]) for row in await cursor.fetchall()}
        if "inbound_queue_id" in binding_columns:
            await db.execute(_LATEST_BINDINGS_SQL)  # guard: raw-sql
            await db.execute(_COPY_LATEST_BINDINGS_SQL)  # guard: raw-sql
            await db.execute("DROP TABLE accepted_turn_bindings")  # guard: raw-sql
            await db.execute(
                "ALTER TABLE accepted_turn_bindings_new RENAME TO accepted_turn_bindings"
            )  # guard: raw-sql
            await db.executescript(_LATEST_BINDING_INDEXES_SQL)  # guard: raw-sql
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.execute("PRAGMA foreign_keys=ON")
    await db.commit()
