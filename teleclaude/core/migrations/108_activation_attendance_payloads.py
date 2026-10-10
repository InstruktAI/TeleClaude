"""Give every stored procedure-activation operation the attendance its command now carries."""

from __future__ import annotations

import json

import aiosqlite

from teleclaude.core.operations._kinds import OPERATION_KIND_PROCEDURE_ACTIVATION
from teleclaude.docs_subscriptions import SubscriptionAttendance

_ATTENDANCE_FIELD = "attendance"
_BEGIN_SQL = "BEGIN"
_SELECT_ACTIVATIONS_SQL = "SELECT operation_id, payload_json FROM operations WHERE kind = ?"
_UPDATE_PAYLOAD_SQL = "UPDATE operations SET payload_json = ? WHERE operation_id = ?"
_INVALID_PAYLOAD_TEMPLATE = "Cannot read the payload of procedure-activation operation {operation_id}: {reason}"
_NOT_JSON_REASON = "payload is not valid JSON"
_NOT_OBJECT_REASON = "payload is not an object"


async def up(db: aiosqlite.Connection) -> None:
    """Set the attended attendance on each stored activation payload that lacks one; idempotent."""
    await db.execute(_BEGIN_SQL)
    try:
        async with db.execute(_SELECT_ACTIVATIONS_SQL, (OPERATION_KIND_PROCEDURE_ACTIVATION,)) as cursor:
            operations = await cursor.fetchall()
        for operation_id_raw, payload_json_raw in operations:
            operation_id = str(operation_id_raw)
            try:
                payload = json.loads(str(payload_json_raw))
            except (TypeError, ValueError) as exc:
                raise _payload_error(operation_id, _NOT_JSON_REASON) from exc
            if not isinstance(payload, dict):
                raise _payload_error(operation_id, _NOT_OBJECT_REASON)
            if _ATTENDANCE_FIELD in payload:
                continue
            payload[_ATTENDANCE_FIELD] = SubscriptionAttendance.ATTENDED.value
            await db.execute(_UPDATE_PAYLOAD_SQL, (json.dumps(payload, sort_keys=True), operation_id))
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _payload_error(operation_id: str, reason: str) -> RuntimeError:
    return RuntimeError(_INVALID_PAYLOAD_TEMPLATE.format(operation_id=operation_id, reason=reason))


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
