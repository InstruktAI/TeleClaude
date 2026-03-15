"""Characterization tests for teleclaude.core.operations.service."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from typing_extensions import TypedDict, Unpack

import teleclaude.core.operations.service as service_module
from teleclaude.core.db_models import Operation
from teleclaude.core.operations.service import (
    OPERATION_KIND_TODO_WORK,
    OperationsService,
    emit_operation_progress,
    get_operations_service,
    set_operations_service,
)


class _TaskHandle:
    def __init__(self) -> None:
        self._done = False

    def done(self) -> bool:
        return self._done


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


@pytest.fixture(autouse=True)
def reset_operations_globals() -> Iterator[None]:
    previous_service = service_module._operations_service
    token = service_module._progress_callback.set(None)
    service_module._operations_service = None
    try:
        yield
    finally:
        service_module._operations_service = previous_service
        service_module._progress_callback.reset(token)


def _operation(**overrides: Unpack[_OperationValues]) -> Operation:
    values: _OperationValues = {
        "operation_id": "op-1",
        "kind": OPERATION_KIND_TODO_WORK,
        "caller_session_id": "session-1",
        "client_request_id": None,
        "cwd": "/tmp/worktree",
        "slug": None,
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
    task_registry: _RecordingTaskRegistry | MagicMock | None = None,
    poll_after_ms: int = 250,
    stale_after_s: float = 30.0,
) -> OperationsService:
    return OperationsService(
        db=db or MagicMock(),
        task_registry=task_registry or _RecordingTaskRegistry(),
        poll_after_ms=poll_after_ms,
        stale_after_s=stale_after_s,
    )


@pytest.mark.unit
def test_get_operations_service_raises_http_503_before_initialization() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_operations_service()

    assert exc_info.value.status_code == 503


@pytest.mark.unit
def test_get_operations_service_returns_process_wide_service_instance() -> None:
    service = _service()

    set_operations_service(service)

    assert get_operations_service() is service


@pytest.mark.unit
def test_emit_operation_progress_forwards_phase_updates_to_active_callback() -> None:
    seen: list[tuple[str, str, str]] = []

    def capture(phase: str, decision: str, reason: str) -> None:
        seen.append((phase, decision, reason))

    token = service_module._progress_callback.set(capture)
    try:
        emit_operation_progress("build", "continue", "tests ready")
    finally:
        service_module._progress_callback.reset(token)

    assert seen == [("build", "continue", "tests ready")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_start_marks_abandoned_nonterminal_operations_stale() -> None:
    db = MagicMock()
    db.mark_nonterminal_operations_stale = AsyncMock(return_value=0)
    service = _service(db=db)

    await service.start()

    db.mark_nonterminal_operations_stale.assert_awaited_once_with(
        error_text="daemon restarted before operation completed",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expire_stale_operations_uses_current_time_minus_stale_window() -> None:
    db = MagicMock()
    db.expire_stale_operations = AsyncMock(return_value=4)
    service = _service(db=db, stale_after_s=12.5)
    fixed_now = datetime(2024, 2, 3, 4, 5, 6, tzinfo=UTC)

    with patch.object(service_module, "datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        result = await service.expire_stale_operations()

    assert result == 4
    db.expire_stale_operations.assert_awaited_once_with(
        (fixed_now - timedelta(seconds=12.5)).isoformat(),
        error_text="operation heartbeat expired",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_work_returns_existing_request_match_without_creating_new_row() -> None:
    existing = _operation(
        operation_id="existing-op",
        slug="chartest-core-operations",
        client_request_id="req-1",
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=existing)
    db.find_matching_nonterminal_operation = AsyncMock()
    db.create_operation = AsyncMock()
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    result = await service.submit_todo_work(
        slug="chartest-core-operations",
        cwd="/tmp/worktree",
        caller_session_id="session-1",
        client_request_id="req-1",
    )

    assert result["operation_id"] == "existing-op"
    assert result["client_request_id"] == "req-1"
    db.find_matching_nonterminal_operation.assert_not_awaited()
    db.create_operation.assert_not_awaited()
    assert registry.spawned_names == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_work_reattaches_queued_match_and_starts_background_task() -> None:
    existing = _operation(
        operation_id="queued-op",
        slug="chartest-core-operations",
        state="queued",
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=None)
    db.find_matching_nonterminal_operation = AsyncMock(return_value=existing)
    db.create_operation = AsyncMock()
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    result = await service.submit_todo_work(
        slug="chartest-core-operations",
        cwd="/tmp/worktree",
        caller_session_id="session-1",
        client_request_id="req-1",
    )

    assert result["operation_id"] == "queued-op"
    assert registry.spawned_names == ["operation-queued-op"]
    db.create_operation.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_work_returns_running_match_without_spawning_duplicate_task() -> None:
    existing = _operation(
        operation_id="running-op",
        slug="chartest-core-operations",
        state="running",
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=None)
    db.find_matching_nonterminal_operation = AsyncMock(return_value=existing)
    db.create_operation = AsyncMock()
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    result = await service.submit_todo_work(
        slug="chartest-core-operations",
        cwd="/tmp/worktree",
        caller_session_id="session-1",
        client_request_id="req-1",
    )

    assert result["operation_id"] == "running-op"
    assert registry.spawned_names == []
    db.create_operation.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_work_creates_new_operation_with_serialized_payload() -> None:
    created = _operation(
        operation_id="generated-op",
        slug="chartest-core-operations",
        client_request_id="req-1",
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(return_value=None)
    db.find_matching_nonterminal_operation = AsyncMock(return_value=None)
    db.create_operation = AsyncMock(return_value=created)
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    with patch.object(service_module.uuid, "uuid4", return_value="generated-op"):
        result = await service.submit_todo_work(
            slug="chartest-core-operations",
            cwd="/tmp/worktree",
            caller_session_id="session-1",
            client_request_id="req-1",
        )

    create_kwargs = db.create_operation.await_args.kwargs
    assert result["operation_id"] == "generated-op"
    assert registry.spawned_names == ["operation-generated-op"]
    assert create_kwargs["operation_id"] == "generated-op"
    assert create_kwargs["kind"] == OPERATION_KIND_TODO_WORK
    assert create_kwargs["state"] == "queued"
    assert json.loads(create_kwargs["payload_json"]) == {
        "cwd": "/tmp/worktree",
        "kind": OPERATION_KIND_TODO_WORK,
        "slug": "chartest-core-operations",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_todo_work_reuses_existing_request_after_integrity_error() -> None:
    existing = _operation(
        operation_id="existing-op",
        slug="chartest-core-operations",
        state="running",
        client_request_id="req-1",
    )
    db = MagicMock()
    db.get_operation_by_request = AsyncMock(side_effect=[None, existing])
    db.find_matching_nonterminal_operation = AsyncMock(return_value=None)
    db.create_operation = AsyncMock(
        side_effect=IntegrityError("insert into operations", {"client_request_id": "req-1"}, Exception("dup")),
    )
    registry = _RecordingTaskRegistry()
    service = _service(db=db, task_registry=registry)

    result = await service.submit_todo_work(
        slug="chartest-core-operations",
        cwd="/tmp/worktree",
        caller_session_id="session-1",
        client_request_id="req-1",
    )

    assert result["operation_id"] == "existing-op"
    assert registry.spawned_names == []
    assert db.get_operation_by_request.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_operation_for_caller_returns_owned_operation() -> None:
    db = MagicMock()
    db.get_operation = AsyncMock(
        return_value=_operation(
            operation_id="done-op",
            caller_session_id="owner-session",
            state="completed",
            slug="chartest-core-operations",
            result_text="ok",
        )
    )
    service = _service(db=db)

    result = await service.get_operation_for_caller(
        operation_id="done-op",
        caller_session_id="owner-session",
        human_role=None,
    )

    assert result["operation_id"] == "done-op"
    assert result["poll_after_ms"] == 0
    assert result["result"] == "ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_operation_for_caller_allows_admin_to_read_foreign_operation() -> None:
    db = MagicMock()
    db.get_operation = AsyncMock(
        return_value=_operation(
            operation_id="foreign-op",
            caller_session_id="someone-else",
            state="running",
        )
    )
    service = _service(db=db)

    result = await service.get_operation_for_caller(
        operation_id="foreign-op",
        caller_session_id="owner-session",
        human_role="admin",
    )

    assert result["operation_id"] == "foreign-op"
    assert result["poll_after_ms"] == 250


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "caller_session_id"),
    [
        (None, "owner-session"),
        (_operation(caller_session_id="someone-else"), "owner-session"),
    ],
)
async def test_get_operation_for_caller_returns_404_for_missing_or_foreign_operation(
    operation: Operation | None,
    caller_session_id: str,
) -> None:
    db = MagicMock()
    db.get_operation = AsyncMock(return_value=operation)
    service = _service(db=db)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_operation_for_caller(
            operation_id="missing-op",
            caller_session_id=caller_session_id,
            human_role=None,
        )

    assert exc_info.value.status_code == 404
