"""Todo rename operation service tests."""

from __future__ import annotations

import json
from typing import Unpack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from typing_extensions import TypedDict

import teleclaude.core.operations.service as service_module
from teleclaude.core.db_models import Operation
from teleclaude.core.operations.service import OPERATION_KIND_TODO_RENAME, OperationsService

_CWD = "/tmp/worktree"
_OLD_SLUG = "old-slug"
_NEW_SLUG = "new-slug"
_FIRST_TARGET = "first-target"
_SECOND_TARGET = "second-target"
_SESSION_ID = "session-1"
_REQUEST_ID = "req-1"
_GENERATED_OPERATION_ID = "generated-rename-op"
_RENAME_OPERATION_ID = "rename-op"
_QUEUED_TASK_NAME = "operation-generated-rename-op"
_RENAME_RESULT = "renamed"


class _TaskHandle:
    def done(self) -> bool:
        return False


class _RecordingTaskRegistry:
    def __init__(self) -> None:
        self.spawned_names: list[str] = []

    def spawn(self, coro: object, *, name: str) -> _TaskHandle:
        self.spawned_names.append(name)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return _TaskHandle()


class _OperationValues(TypedDict, total=False):
    operation_id: str
    kind: str
    caller_session_id: str
    client_request_id: str | None
    cwd: str
    slug: str | None
    payload_json: str
    state: str
    progress_phase: str | None
    progress_decision: str | None
    progress_reason: str | None
    result_text: str | None
    error_text: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    heartbeat_at: str | None
    attempt_count: int


def _operation(**overrides: Unpack[_OperationValues]) -> Operation:
    values: _OperationValues = {
        "operation_id": "op-1",
        "kind": OPERATION_KIND_TODO_RENAME,
        "caller_session_id": _SESSION_ID,
        "client_request_id": None,
        "cwd": _CWD,
        "slug": _OLD_SLUG,
        "payload_json": "{}",
        "state": "queued",
        "progress_phase": None,
        "progress_decision": None,
        "progress_reason": None,
        "result_text": None,
        "error_text": None,
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "started_at": None,
        "completed_at": None,
        "heartbeat_at": None,
        "attempt_count": 0,
    }
    values.update(overrides)
    return Operation(**values)


def _service(
    *,
    db: MagicMock | None = None,
    task_registry: _RecordingTaskRegistry | None = None,
) -> OperationsService:
    return OperationsService(db=db or MagicMock(), task_registry=task_registry or _RecordingTaskRegistry())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_rename_creates_new_operation_with_source_slug_and_target_payload() -> None:
    created = _operation(
        operation_id=_GENERATED_OPERATION_ID,
        client_request_id=_REQUEST_ID,
        payload_json=json.dumps(
            {
                "cwd": _CWD,
                "kind": OPERATION_KIND_TODO_RENAME,
                "old_slug": _OLD_SLUG,
                "new_slug": _NEW_SLUG,
            }
        ),
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=None)
    db.find_matching_nonterminal_operation = AsyncMock(return_value=None)
    db.create_operation = AsyncMock(return_value=created)
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    with patch.object(service_module.uuid, "uuid4", return_value=_GENERATED_OPERATION_ID):
        result = await service.submit_todo_rename(
            old_slug=_OLD_SLUG,
            new_slug=_NEW_SLUG,
            cwd=_CWD,
            caller_session_id=_SESSION_ID,
            client_request_id=_REQUEST_ID,
        )

    create_kwargs = db.create_operation.await_args.kwargs
    assert result["operation_id"] == _GENERATED_OPERATION_ID
    assert result["slug"] == _OLD_SLUG
    assert registry.spawned_names == [_QUEUED_TASK_NAME]
    assert create_kwargs["slug"] == _OLD_SLUG
    assert create_kwargs["kind"] == OPERATION_KIND_TODO_RENAME
    assert json.loads(create_kwargs["payload_json"]) == {
        "cwd": _CWD,
        "kind": OPERATION_KIND_TODO_RENAME,
        "old_slug": _OLD_SLUG,
        "new_slug": _NEW_SLUG,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_rename_rejects_reattach_when_target_differs() -> None:
    existing = _operation(
        operation_id=_RENAME_OPERATION_ID,
        payload_json=json.dumps(
            {
                "cwd": _CWD,
                "kind": OPERATION_KIND_TODO_RENAME,
                "old_slug": _OLD_SLUG,
                "new_slug": _FIRST_TARGET,
            }
        ),
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=None)
    db.find_matching_nonterminal_operation = AsyncMock(return_value=existing)
    db.create_operation = AsyncMock()
    service = _service(db=db)

    with pytest.raises(HTTPException) as exc_info:
        await service.submit_todo_rename(
            old_slug=_OLD_SLUG,
            new_slug=_SECOND_TARGET,
            cwd=_CWD,
            caller_session_id=_SESSION_ID,
            client_request_id=None,
        )

    assert exc_info.value.status_code == 409
    db.create_operation.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_todo_rename_operation_passes_current_operation_id() -> None:
    operation = _operation(
        operation_id=_RENAME_OPERATION_ID,
        payload_json=json.dumps(
            {
                "cwd": _CWD,
                "kind": OPERATION_KIND_TODO_RENAME,
                "old_slug": _OLD_SLUG,
                "new_slug": _NEW_SLUG,
            }
        ),
    )
    db = MagicMock()
    service = _service(db=db)

    async def execute_todo_rename(
        db_arg: object,
        old_slug: str,
        new_slug: str,
        cwd: str,
        *,
        current_operation_id: str,
    ) -> str:
        assert db_arg is db
        assert old_slug == _OLD_SLUG
        assert new_slug == _NEW_SLUG
        assert cwd == _CWD
        assert current_operation_id == _RENAME_OPERATION_ID
        return _RENAME_RESULT

    rename_module = service_module.importlib.import_module("teleclaude.core.next_machine.rename")
    with patch.object(rename_module, "execute_todo_rename", new=execute_todo_rename, create=True):
        result = await service._run_todo_rename(operation)

    assert result == _RENAME_RESULT
