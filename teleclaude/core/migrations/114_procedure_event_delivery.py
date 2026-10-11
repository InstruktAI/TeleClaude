"""Add responsibility-owned procedure event inbox and session delivery state."""

from __future__ import annotations

import json

import aiosqlite

from teleclaude.core.operations._kinds import OPERATION_KIND_PROCEDURE_ACTIVATION
from teleclaude.docs_subscriptions import EventDeliveryMode

_BEGIN_SQL = "BEGIN"
_SELECT_ACTIVATIONS_SQL = "SELECT operation_id, payload_json FROM operations WHERE kind = ?"
_UPDATE_PAYLOAD_SQL = "UPDATE operations SET payload_json = ? WHERE operation_id = ?"
_INVALID_PAYLOAD_TEMPLATE = "Cannot read the payload of procedure-activation operation {operation_id}: {reason}"
_NOT_JSON_REASON = "payload is not valid JSON"
_NOT_OBJECT_REASON = "payload is not an object"
_EVENT_DELIVERY_FIELD = "event_delivery"
_INTERRUPTIBLE_FIELD = "interruptible"

_CREATE_PROCEDURE_EVENT_INBOX_SQL = """
CREATE TABLE IF NOT EXISTS procedure_event_inbox (
    enqueue_order INTEGER PRIMARY KEY AUTOINCREMENT,
    activation_id TEXT NOT NULL UNIQUE,
    responsibility_key TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    home TEXT NOT NULL,
    subject TEXT,
    event_json TEXT NOT NULL,
    identity TEXT NOT NULL CHECK(identity IN ('home', 'subject')),
    attendance TEXT NOT NULL CHECK(attendance IN ('attended', 'unattended')),
    event_delivery TEXT NOT NULL CHECK(event_delivery IN ('sequential', 'batched')),
    interruptible INTEGER NOT NULL CHECK(interruptible IN (0, 1)),
    assigned_session_id TEXT,
    outcome TEXT NOT NULL DEFAULT 'pending' CHECK(outcome IN ('pending', 'delivered', 'failed', 'suspended')),
    outcome_reason TEXT,
    accepted_at TEXT NOT NULL,
    terminal_at TEXT,
    CHECK(
        (outcome IN ('pending', 'suspended') AND terminal_at IS NULL)
        OR (outcome IN ('delivered', 'failed') AND terminal_at IS NOT NULL)
    )
)
"""
_CREATE_PROCEDURE_EVENT_RESPONSIBILITY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_procedure_event_inbox_responsibility
ON procedure_event_inbox(responsibility_key, enqueue_order)
WHERE outcome IN ('pending', 'suspended')
"""
_CREATE_PROCEDURE_EVENT_ASSIGNED_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_procedure_event_inbox_assigned
ON procedure_event_inbox(assigned_session_id, enqueue_order)
WHERE outcome = 'pending'
"""
_CREATE_PROCEDURE_EVENT_SESSIONS_SQL = """
CREATE TABLE IF NOT EXISTS procedure_event_delivery_sessions (
    session_id TEXT PRIMARY KEY,
    procedure_id TEXT NOT NULL,
    responsibility_key TEXT NOT NULL,
    event_delivery TEXT NOT NULL CHECK(event_delivery IN ('sequential', 'batched')),
    interruptible INTEGER NOT NULL CHECK(interruptible IN (0, 1)),
    initialized_at TEXT NOT NULL,
    initial_entry_id TEXT,
    initial_entry_consumed_at TEXT,
    active_run_id TEXT,
    consumed_entry_id TEXT,
    wake_occurrence_id TEXT
)
"""
_SCHEMA_STATEMENTS = (
    _CREATE_PROCEDURE_EVENT_INBOX_SQL,
    _CREATE_PROCEDURE_EVENT_RESPONSIBILITY_INDEX_SQL,
    _CREATE_PROCEDURE_EVENT_ASSIGNED_INDEX_SQL,
    _CREATE_PROCEDURE_EVENT_SESSIONS_SQL,
)


async def up(db: aiosqlite.Connection) -> None:
    """Create the forward-only procedure event persistence structures."""
    await db.execute(_BEGIN_SQL)
    try:
        for statement in _SCHEMA_STATEMENTS:
            await db.execute(statement)
        async with db.execute(_SELECT_ACTIVATIONS_SQL, (OPERATION_KIND_PROCEDURE_ACTIVATION,)) as cursor:
            operations = await cursor.fetchall()
        for operation_id_raw, payload_json_raw in operations:
            operation_id = str(operation_id_raw)
            try:
                payload = json.loads(str(payload_json_raw))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    _INVALID_PAYLOAD_TEMPLATE.format(operation_id=operation_id, reason=_NOT_JSON_REASON)
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError(
                    _INVALID_PAYLOAD_TEMPLATE.format(operation_id=operation_id, reason=_NOT_OBJECT_REASON)
                )
            if _EVENT_DELIVERY_FIELD in payload and _INTERRUPTIBLE_FIELD in payload:
                continue
            payload.setdefault(_EVENT_DELIVERY_FIELD, EventDeliveryMode.SEQUENTIAL.value)
            payload.setdefault(_INTERRUPTIBLE_FIELD, False)
            await db.execute(_UPDATE_PAYLOAD_SQL, (json.dumps(payload, sort_keys=True), operation_id))
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
