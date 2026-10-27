"""Execution contract for receipt-backed todo removal operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine.remove import execute_todo_remove
from teleclaude.core.operations._kinds import OperationKind
from teleclaude.core.operations.todo_identity import todo_operation_context, todo_operation_submission

if TYPE_CHECKING:
    from teleclaude.core.operations.service import OperationsService, SerializedOperation

_REMOVE_PAYLOAD_INVALID_JSON = "todo remove operation payload is invalid JSON"
_REMOVE_PAYLOAD_FORCE_REQUIRED = "todo remove operation payload must include force"
_FORCE_FIELD = "force"


@dataclass(frozen=True)
class TodoRemovePayload:
    """Persisted request fields for a todo-remove operation."""

    force: bool


async def submit_todo_remove(
    service: OperationsService,
    *,
    slug: str,
    cwd: str,
    caller_session_id: str,
    client_request_id: str | None,
    force: bool = False,
    addressed_todo_id: str | None = None,
) -> SerializedOperation:
    """Create or reattach a receipt-backed todo-remove operation."""
    payload_json, existing_match_ok, on_existing = todo_operation_submission(
        kind=OperationKind.TODO_REMOVE,
        slug=slug,
        cwd=cwd,
        addressed_todo_id=addressed_todo_id,
        client_request_id=client_request_id,
        force=force,
    )
    return await service._submit_operation(
        kind=OperationKind.TODO_REMOVE,
        caller_session_id=caller_session_id,
        cwd=cwd,
        slug=slug,
        client_request_id=client_request_id,
        payload_json=payload_json,
        existing_match_ok=existing_match_ok,
        on_existing=on_existing,
    )


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
    cwd, _caller_session_id = todo_operation_context(operation)
    return await execute_todo_remove(
        db,
        operation.slug,
        cwd,
        force=payload.force,
        current_operation_id=operation.operation_id,
    )
