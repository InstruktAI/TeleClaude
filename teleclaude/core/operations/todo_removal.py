"""Execution contract for receipt-backed todo removal operations."""

from __future__ import annotations

import json
from dataclasses import dataclass

from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine.remove import execute_todo_remove

_REMOVE_PAYLOAD_INVALID_JSON = "todo remove operation payload is invalid JSON"
_REMOVE_PAYLOAD_FORCE_REQUIRED = "todo remove operation payload must include force"
_FORCE_FIELD = "force"


@dataclass(frozen=True)
class TodoRemovePayload:
    """Persisted request fields for a todo-remove operation."""

    force: bool


def _todo_remove_payload(operation: Operation) -> TodoRemovePayload:
    """Read the force override from one persisted todo-remove request."""
    try:
        payload = json.loads(operation.payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(_REMOVE_PAYLOAD_INVALID_JSON) from exc
    if not isinstance(payload, dict):
        raise ValueError(_REMOVE_PAYLOAD_FORCE_REQUIRED)
    force = payload.get(_FORCE_FIELD)
    if not isinstance(force, bool):
        raise ValueError(_REMOVE_PAYLOAD_FORCE_REQUIRED)
    return TodoRemovePayload(force=force)


async def run_todo_remove_operation(db: Db, operation: Operation) -> str:
    """Execute one persisted todo-remove request through the workflow owner."""
    payload = _todo_remove_payload(operation)
    return await execute_todo_remove(
        db,
        operation.slug,
        operation.cwd,
        force=payload.force,
        current_operation_id=operation.operation_id,
    )
