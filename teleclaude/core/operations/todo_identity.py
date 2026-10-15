"""Identity carried by todo operations from submit through execution."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import TypedDict, cast

from fastapi import HTTPException

from teleclaude.core.db_models import Operation
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.workflow_store.store import get_workflow_store

_ADDRESSED_TODO_ID_FIELD = "addressed_todo_id"
_OPERATION_KIND_FIELD = "kind"
_OPERATION_SLUG_FIELD = "slug"
_OPERATION_CWD_FIELD = "cwd"
_OPERATION_FORCE_FIELD = "force"
_OPERATION_PAYLOAD_OBJECT_REQUIRED = "todo operation payload must be an object"
_ADDRESSED_TODO_ID_STRING_REQUIRED = "addressed todo identity must be a string"
_IDENTITY_REATTACH_REFUSAL = (
    "client request id {request_id} is already bound to {existing_target}; refusing to reuse it for {requested_target}"
)
_REQUEST_ID_UNKNOWN = "the supplied request id"
_UNADDRESSED_TODO_OPERATION = "slug-addressed operation"
_ADDRESSLESS_TODO_OPERATION = "an operation without a todo identity"
_ADDRESSED_OPERATION_TODO_REQUIRED = "identity-addressed operation requires a slug and checkout"
_TODO_OPERATION_CONTEXT_REQUIRED = "todo operation requires persisted checkout and caller context"


def todo_operation_context(operation: Operation) -> tuple[str, str]:
    """Narrow the persisted context shared by every receipt-backed todo operation."""
    cwd = operation.cwd
    caller_session_id = operation.caller_session_id
    if cwd is None or caller_session_id is None:
        raise RuntimeError(_TODO_OPERATION_CONTEXT_REQUIRED)
    return cwd, caller_session_id


class TodoOperationPayload(TypedDict, total=False):
    """Wire fields written by receipt-backed todo operations."""

    kind: str
    slug: str | None
    cwd: str
    force: bool
    addressed_todo_id: str
    reason: str


def operation_addressed_todo_id(operation: Operation) -> str | None:
    """Read the optional durable todo identity carried by an operation payload."""
    payload = json.loads(operation.payload_json)
    if not isinstance(payload, dict):
        raise ValueError(_OPERATION_PAYLOAD_OBJECT_REQUIRED)
    todo_id = payload.get(_ADDRESSED_TODO_ID_FIELD)
    if todo_id is None:
        return None
    if not isinstance(todo_id, str):
        raise ValueError(_ADDRESSED_TODO_ID_STRING_REQUIRED)
    return todo_id


def operation_reason(operation: Operation) -> str:
    """The reason a work call stated for a ready item, carried in the operation payload; empty when none was stated."""
    payload = json.loads(operation.payload_json)
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return reason if isinstance(reason, str) else ""


def operation_payload_abandon(operation: Operation) -> bool:
    """Read the ``abandon`` discriminator from a todo-integrate operation's payload; absent reads False."""
    payload = json.loads(operation.payload_json)
    return isinstance(payload, dict) and payload.get("abandon") is True


def operation_matches_todo_identity(operation: Operation, *, requested_todo_id: str | None) -> bool:
    """Match identity-addressed and slug-addressed submissions in both directions."""
    return operation_addressed_todo_id(operation) == requested_todo_id


def ensure_addressed_todo_match(
    operation: Operation,
    *,
    requested_todo_id: str | None,
    client_request_id: str | None,
) -> None:
    """Refuse a request-id reattach to an operation for a different todo identity."""
    existing_todo_id = operation_addressed_todo_id(operation)
    if existing_todo_id == requested_todo_id:
        return
    existing_target = existing_todo_id or _UNADDRESSED_TODO_OPERATION
    requested_target = requested_todo_id or _ADDRESSLESS_TODO_OPERATION
    raise HTTPException(
        status_code=409,
        detail=_IDENTITY_REATTACH_REFUSAL.format(
            request_id=client_request_id or _REQUEST_ID_UNKNOWN,
            existing_target=existing_target,
            requested_target=requested_target,
        ),
    )


def addressed_todo_operation_payload(
    payload: TodoOperationPayload,
    *,
    addressed_todo_id: str | None,
) -> TodoOperationPayload:
    """Add a durable identity to an operation payload when the caller supplied one."""
    if addressed_todo_id is not None:
        payload = cast(TodoOperationPayload, {**payload, _ADDRESSED_TODO_ID_FIELD: addressed_todo_id})
    return payload


def addressed_todo_reattach_hooks(
    *,
    addressed_todo_id: str | None,
    client_request_id: str | None,
) -> tuple[Callable[[Operation], bool], Callable[[Operation], None]]:
    """Return the nonterminal filter and request-id guard for one submission."""
    return (
        partial(operation_matches_todo_identity, requested_todo_id=addressed_todo_id),
        partial(
            ensure_addressed_todo_match,
            requested_todo_id=addressed_todo_id,
            client_request_id=client_request_id,
        ),
    )


def todo_operation_submission(
    *,
    kind: str,
    slug: str | None,
    cwd: str,
    addressed_todo_id: str | None,
    client_request_id: str | None,
    force: bool | None = None,
    reason: str | None = None,
) -> tuple[str, Callable[[Operation], bool], Callable[[Operation], None]]:
    """Build the durable payload and both identity-safe reattachment checks."""
    if force is None:
        payload = TodoOperationPayload(kind=kind, slug=slug, cwd=cwd)
    else:
        payload = TodoOperationPayload(kind=kind, slug=slug, cwd=cwd, force=force)
    if reason:
        payload["reason"] = reason
    payload_json = json.dumps(
        addressed_todo_operation_payload(payload, addressed_todo_id=addressed_todo_id),
        sort_keys=True,
    )
    existing_match_ok, on_existing = addressed_todo_reattach_hooks(
        addressed_todo_id=addressed_todo_id,
        client_request_id=client_request_id,
    )
    return payload_json, existing_match_ok, on_existing


@asynccontextmanager
async def pin_operation_todo_identity(operation: Operation) -> AsyncIterator[None]:
    """Install the operation's todo identity for its full execution, when addressed."""
    todo_id = operation_addressed_todo_id(operation)
    if todo_id is None:
        yield
        return
    if operation.slug is None or operation.cwd is None:
        raise ValueError(_ADDRESSED_OPERATION_TODO_REQUIRED)
    project_root = resolve_project_root(operation.cwd)
    todos_db = await get_workflow_store(project_root)
    with todos_db.identity_scope(operation.slug, todo_id):
        yield
