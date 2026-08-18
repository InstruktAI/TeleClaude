"""Allow every envelope in a receipt-backed peer bundle to be persisted."""

from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Replace the legacy one-envelope-per-receipt shape without losing bindings."""
    await db.execute(
        "CREATE TABLE turn_receipt_envelopes_new ("
        "binding_id TEXT NOT NULL, inbound_queue_id INTEGER NOT NULL, envelope_index INTEGER NOT NULL DEFAULT 0, "
        "occurrence_key TEXT NOT NULL, text_kind TEXT NOT NULL, "
        "envelope_span_start INTEGER NOT NULL, envelope_span_end INTEGER NOT NULL, "
        "body_span_start INTEGER NOT NULL, body_span_end INTEGER NOT NULL, authored_part_id INTEGER, "
        "PRIMARY KEY (binding_id, inbound_queue_id, envelope_index))"
    )
    await db.execute(
        "INSERT INTO turn_receipt_envelopes_new "
        "(binding_id, inbound_queue_id, envelope_index, occurrence_key, text_kind, envelope_span_start, "
        "envelope_span_end, body_span_start, body_span_end, authored_part_id) "
        "SELECT binding_id, inbound_queue_id, 0, occurrence_key, text_kind, envelope_span_start, "
        "envelope_span_end, body_span_start, body_span_end, authored_part_id FROM turn_receipt_envelopes"
    )
    await db.execute("DROP TABLE turn_receipt_envelopes")
    await db.execute("ALTER TABLE turn_receipt_envelopes_new RENAME TO turn_receipt_envelopes")
