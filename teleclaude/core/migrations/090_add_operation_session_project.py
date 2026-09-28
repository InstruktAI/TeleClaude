"""Record the project scope of command-backed session operations."""

from __future__ import annotations

import json
from typing import cast

import aiosqlite

from teleclaude.core.models._types import JsonDict
from teleclaude.core.operations._kinds import _COMMAND_TYPE_TO_OPERATION_KIND
from teleclaude.types.commands import command_from_dict

_SESSION_PROJECT_PATH_COLUMN = "session_project_path"
_SESSION_ID_FIELD = "session_id"
_SESSION_COMMAND_OPERATION_KINDS = ("session_close", "agent_restart", "agent_handoff")
_SELECT_COLUMNS_SQL = "SELECT name FROM pragma_table_info('operations')"
_ADD_COLUMN_SQL = "ALTER TABLE operations ADD COLUMN session_project_path TEXT"
_BEGIN_SQL = "BEGIN"
_SELECT_COMMAND_OPERATIONS_SQL = """
SELECT operation_id, kind, payload_json
FROM operations
WHERE kind IN (?, ?, ?) AND cwd IS NULL
"""
_SELECT_SESSION_PROJECT_SQL = "SELECT project_path FROM sessions WHERE session_id = ?"
_UPDATE_OPERATION_PROJECT_SQL = "UPDATE operations SET session_project_path = ? WHERE operation_id = ?"
_BACKFILL_FAILURE_TEMPLATE = "Cannot derive session project scope for operation {operation_id}: {reason}"
_INVALID_JSON_REASON = "payload is not valid JSON"
_INVALID_OBJECT_REASON = "payload is not an object"
_INVALID_COMMAND_REASON = "payload is not a valid command for its operation kind"
_INVALID_SESSION_ID_REASON = "command has no valid session identifier"
_INVALID_PROJECT_PATH_REASON = "target session has an invalid project path"


async def up(db: aiosqlite.Connection) -> None:
    """Add the operation scope and backfill it from extant target sessions."""
    async with db.execute(_SELECT_COLUMNS_SQL) as cursor:
        columns = {str(row[0]) for row in await cursor.fetchall()}
    if _SESSION_PROJECT_PATH_COLUMN in columns:
        return

    await db.execute(_BEGIN_SQL)
    try:
        await db.execute(_ADD_COLUMN_SQL)
        async with db.execute(_SELECT_COMMAND_OPERATIONS_SQL, _SESSION_COMMAND_OPERATION_KINDS) as cursor:
            operations = await cursor.fetchall()
        for operation_id_raw, operation_kind_raw, payload_json_raw in operations:
            try:
                payload = json.loads(str(payload_json_raw))
            except (TypeError, ValueError) as exc:
                raise _backfill_error(operation_id_raw, _INVALID_JSON_REASON) from exc
            if not isinstance(payload, dict):
                raise _backfill_error(operation_id_raw, _INVALID_OBJECT_REASON)
            try:
                command = command_from_dict(cast(JsonDict, payload))
            except (KeyError, TypeError, ValueError) as exc:
                raise _backfill_error(operation_id_raw, _INVALID_COMMAND_REASON) from exc
            if _COMMAND_TYPE_TO_OPERATION_KIND.get(command.command_type) != operation_kind_raw:
                raise _backfill_error(operation_id_raw, _INVALID_COMMAND_REASON)
            session_id = getattr(command, _SESSION_ID_FIELD, None)
            if not isinstance(session_id, str) or not session_id.strip():
                raise _backfill_error(operation_id_raw, _INVALID_SESSION_ID_REASON)
            async with db.execute(_SELECT_SESSION_PROJECT_SQL, (session_id,)) as cursor:
                session = await cursor.fetchone()
            if session is None:
                continue
            project_path_raw = session[0]
            if project_path_raw is not None and (not isinstance(project_path_raw, str) or not project_path_raw):
                raise _backfill_error(operation_id_raw, _INVALID_PROJECT_PATH_REASON)
            if project_path_raw is not None:
                await db.execute(
                    _UPDATE_OPERATION_PROJECT_SQL,
                    (project_path_raw, str(operation_id_raw)),
                )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _backfill_error(operation_id: object, reason: str) -> RuntimeError:
    return RuntimeError(_BACKFILL_FAILURE_TEMPLATE.format(operation_id=operation_id, reason=reason))


async def down(db: aiosqlite.Connection) -> None:
    """SQLite down migration omitted."""
