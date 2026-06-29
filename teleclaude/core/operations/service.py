"""Durable receipt-backed operation runtime for long-running local workflows."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable
from contextvars import Token
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, cast

from fastapi import HTTPException
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import IntegrityError

from teleclaude.constants import HUMAN_ROLE_ADMIN
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import EventType, OperationCompletedContext
from teleclaude.core.integration.state_machine import next_integrate
from teleclaude.core.next_machine.create import next_create
from teleclaude.core.next_machine.kinds import KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lifecycle_runner import (
    ManualLifecycleStatus,
    RunnerSkipReason,
    SessionRunner,
    adopt_manual_lifecycle_session,
    default_session_runner,
)
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.remove import execute_todo_remove
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.operation_caller_identity import reset_caller_session_id, set_caller_session_id
from teleclaude.core.operation_progress import reset_progress_callback, set_progress_callback
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todos_db import get_todos_db
from teleclaude.core.todos_db._exceptions import ClaimConflict, OperationErrorPayload, OperationFailure
from teleclaude.events.envelope import EventVisibility

logger = get_logger(__name__)


class SerializedOperation(TypedDict, total=False):
    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str
    slug: str
    completion_event: str
    progress_phase: str
    progress_decision: str
    progress_reason: str
    result: str
    error: str
    error_payload: OperationErrorPayload
    client_request_id: str


OPERATION_KIND_TODO_WORK = "todo_work"
OPERATION_KIND_TASK_RUN = "task_run"
OPERATION_KIND_TODO_INTEGRATE = "todo_integrate"
OPERATION_KIND_TODO_CREATE = "todo_create"
OPERATION_KIND_TODO_PREPARE = "todo_prepare"
OPERATION_KIND_TODO_RENAME = "todo_rename"
OPERATION_KIND_TODO_REMOVE = "todo_remove"
_COMPLETION_EVENTS: dict[str, EventType] = {
    OPERATION_KIND_TODO_WORK: "operation.todo_work.completed",
    OPERATION_KIND_TASK_RUN: "operation.task_run.completed",
    OPERATION_KIND_TODO_INTEGRATE: "operation.todo_integrate.completed",
    OPERATION_KIND_TODO_CREATE: "operation.todo_create.completed",
    OPERATION_KIND_TODO_PREPARE: "operation.todo_prepare.completed",
    OPERATION_KIND_TODO_RENAME: "operation.todo_rename.completed",
    OPERATION_KIND_TODO_REMOVE: "operation.todo_remove.completed",
}
TERMINAL_OPERATION_STATES = {"completed", "failed", "stale", "cancelled"}
NONTERMINAL_OPERATION_STATES = {"queued", "running"}

_operations_service: OperationsService | None = None


def set_operations_service(service: OperationsService) -> None:
    """Install the process-wide operations service."""
    global _operations_service
    _operations_service = service


def get_operations_service() -> OperationsService:
    """Return the configured operations service."""
    if _operations_service is None:
        raise HTTPException(status_code=503, detail="operations service not initialized")
    return _operations_service


class OperationsService:
    """Submit, track, and inspect durable background operations."""

    def __init__(
        self,
        *,
        db: Db,
        task_registry: TaskRegistry,
        poll_after_ms: int = 250,
        heartbeat_interval_s: float = 2.0,
        stale_after_s: float = 30.0,
        lifecycle_client_factory: Callable[[], SessionRunner] = default_session_runner,
    ) -> None:
        self._db = db
        self._task_registry = task_registry
        self._poll_after_ms = poll_after_ms
        self._heartbeat_interval_s = heartbeat_interval_s
        self._stale_after_s = stale_after_s
        self._submit_locks: dict[tuple[str, str, str, str | None], asyncio.Lock] = {}
        self._submit_guard = asyncio.Lock()
        self._live_tasks: dict[str, asyncio.Task[None]] = {}
        self._live_guard = asyncio.Lock()
        self._lifecycle_client_factory = lifecycle_client_factory

    async def start(self) -> None:
        """Normalize any abandoned nonterminal operations from a previous daemon run."""
        stale_count = await self._db.mark_nonterminal_operations_stale(
            error_text="daemon restarted before operation completed",
        )
        if stale_count:
            logger.warning("Marked %d abandoned operation(s) stale during startup", stale_count)

    async def expire_stale_operations(self) -> int:
        """Mark long-silent running operations stale."""
        older_than = (datetime.now(UTC) - timedelta(seconds=self._stale_after_s)).isoformat()
        return await self._db.expire_stale_operations(
            older_than,
            error_text="operation heartbeat expired",
        )

    async def submit_todo_work(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed manual-start operation.

        The single ``/todos/work`` route serves both lanes: the operation kind is
        resolved from the todo's stored ``kind`` so a ``kind=task`` start records a
        ``task_run`` operation (routed to the task-run lane) while every SDLC kind
        records ``todo_work``. No caller flag selects the lane.
        """
        operation_kind = await self._resolve_work_operation_kind(slug=slug, cwd=cwd)
        lock = await self._get_submit_lock(
            kind=operation_kind,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=operation_kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=operation_kind,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=operation_kind)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {
                    "kind": operation_kind,
                    "slug": slug,
                    "cwd": cwd,
                },
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=operation_kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=operation_kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=operation_kind)
            return self._serialize_operation(created)

    async def _resolve_work_operation_kind(self, *, slug: str | None, cwd: str) -> str:
        """Resolve the manual-start operation kind from the todo's stored kind.

        A ``kind=task`` todo starts as a ``task_run`` operation; every SDLC kind
        (and a slug-less or stateless start) resolves to ``todo_work``.
        """
        if slug is None:
            return OPERATION_KIND_TODO_WORK
        todos_db = await get_todos_db(Path(cwd).resolve())
        state = await todos_db.read_state(slug)
        if state is None:
            return OPERATION_KIND_TODO_WORK
        raw_kind = state.get("kind")
        if not isinstance(raw_kind, str):
            return OPERATION_KIND_TODO_WORK
        try:
            kind = canonical_kind(raw_kind)
        except ValueError:
            return OPERATION_KIND_TODO_WORK
        return OPERATION_KIND_TASK_RUN if kind == KIND_TASK else OPERATION_KIND_TODO_WORK

    async def submit_todo_integrate(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-integrate operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_INTEGRATE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_INTEGRATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_INTEGRATE,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=OPERATION_KIND_TODO_INTEGRATE)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {
                    "kind": OPERATION_KIND_TODO_INTEGRATE,
                    "slug": slug,
                    "cwd": cwd,
                },
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_INTEGRATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_INTEGRATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=OPERATION_KIND_TODO_INTEGRATE)
            return self._serialize_operation(created)

    async def submit_todo_create(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-create operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_CREATE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_CREATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_CREATE,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=OPERATION_KIND_TODO_CREATE)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {"kind": OPERATION_KIND_TODO_CREATE, "slug": slug, "cwd": cwd},
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_CREATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_CREATE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=OPERATION_KIND_TODO_CREATE)
            return self._serialize_operation(created)

    async def submit_todo_prepare(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-prepare operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_PREPARE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_PREPARE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_PREPARE,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=OPERATION_KIND_TODO_PREPARE)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {"kind": OPERATION_KIND_TODO_PREPARE, "slug": slug, "cwd": cwd},
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_PREPARE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_PREPARE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=OPERATION_KIND_TODO_PREPARE)
            return self._serialize_operation(created)

    async def submit_todo_remove(
        self,
        *,
        slug: str,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-remove operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_REMOVE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_REMOVE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_REMOVE,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=OPERATION_KIND_TODO_REMOVE)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {"kind": OPERATION_KIND_TODO_REMOVE, "slug": slug, "cwd": cwd},
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_REMOVE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_REMOVE,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=OPERATION_KIND_TODO_REMOVE)
            return self._serialize_operation(created)

    async def submit_todo_rename(
        self,
        *,
        old_slug: str,
        new_slug: str,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-rename operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_RENAME,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=old_slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_RENAME,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    self._ensure_rename_target_matches(existing, new_slug)
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_RENAME,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=old_slug,
            )
            if existing is not None:
                self._ensure_rename_target_matches(existing, new_slug)
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=OPERATION_KIND_TODO_RENAME)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {
                    "kind": OPERATION_KIND_TODO_RENAME,
                    "old_slug": old_slug,
                    "new_slug": new_slug,
                    "cwd": cwd,
                },
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_RENAME,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=old_slug,
                    payload_json=payload_json,
                    state="queued",
                )
            except IntegrityError:
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_RENAME,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                self._ensure_rename_target_matches(existing, new_slug)
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id, kind=OPERATION_KIND_TODO_RENAME)
            return self._serialize_operation(created)

    async def get_operation_for_caller(
        self,
        *,
        operation_id: str,
        caller_session_id: str,
        human_role: str | None,
    ) -> SerializedOperation:
        """Return operation status if owned by the caller or an admin."""
        operation = await self._db.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        if human_role != HUMAN_ROLE_ADMIN and operation.caller_session_id != caller_session_id:
            raise HTTPException(status_code=404, detail="operation not found")
        return self._serialize_operation(operation)

    async def _get_submit_lock(
        self,
        *,
        kind: str,
        caller_session_id: str,
        cwd: str,
        slug: str | None,
    ) -> asyncio.Lock:
        key = (kind, caller_session_id, cwd, slug)
        async with self._submit_guard:
            lock = self._submit_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._submit_locks[key] = lock
            return lock

    async def _ensure_operation_task(self, operation_id: str, *, kind: str = OPERATION_KIND_TODO_WORK) -> None:
        factories: dict[str, Callable[[Operation], Awaitable[str]]] = {
            OPERATION_KIND_TODO_WORK: self._run_todo_work,
            OPERATION_KIND_TASK_RUN: self._run_task_run,
            OPERATION_KIND_TODO_INTEGRATE: lambda op: next_integrate(self._db, op.slug, op.cwd),
            OPERATION_KIND_TODO_CREATE: lambda op: next_create(self._db, op.slug, op.cwd),
            OPERATION_KIND_TODO_PREPARE: self._run_todo_prepare,
            OPERATION_KIND_TODO_RENAME: self._run_todo_rename,
            OPERATION_KIND_TODO_REMOVE: lambda op: execute_todo_remove(self._db, op.slug, op.cwd),
        }
        factory = factories.get(kind)
        if factory is None:
            raise ValueError(f"unsupported operation kind: {kind}")
        operation_coro = self._run_operation(operation_id, kind, factory)
        async with self._live_guard:
            live = self._live_tasks.get(operation_id)
            if live is not None and not live.done():
                return
            task = self._task_registry.spawn(
                operation_coro,
                name=f"operation-{operation_id}",
            )
            self._live_tasks[operation_id] = task

    async def _run_operation(
        self,
        operation_id: str,
        kind: str,
        coro_factory: Callable[[Operation], Awaitable[str]],
    ) -> None:
        """Generic operation runner shared by all operation kinds."""
        heartbeat_task: asyncio.Task[None] | None = None
        stop_heartbeat = asyncio.Event()
        token: Token[Callable[[str, str, str], None] | None] | None = None
        caller_token: Token[str | None] | None = None
        latest_progress: tuple[str, str, str] | None = None
        progress_tasks: set[asyncio.Task[None]] = set()
        completion_event = _COMPLETION_EVENTS.get(kind)
        try:
            now_iso = datetime.now(UTC).isoformat()
            claimed = await self._db.claim_operation(operation_id, now_iso)
            if not claimed:
                return

            operation = await self._db.get_operation(operation_id)
            if operation is None:
                return

            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(operation_id, stop_heartbeat),
                name=f"operation-heartbeat-{operation_id}",
            )

            def _capture_progress(phase: str, decision: str, reason: str) -> None:
                nonlocal latest_progress
                latest_progress = (phase, decision, reason)
                task = asyncio.create_task(
                    self._record_progress(operation_id, phase, decision, reason),
                    name=f"operation-progress-{operation_id}",
                )
                progress_tasks.add(task)
                task.add_done_callback(progress_tasks.discard)

            token = set_progress_callback(_capture_progress)
            caller_token = set_caller_session_id(operation.caller_session_id)
            result = await coro_factory(operation)
            await self._flush_latest_progress(operation_id, latest_progress)
            await self._db.complete_operation(
                operation_id,
                result,
                datetime.now(UTC).isoformat(),
            )
            self._emit_completion_event(completion_event, operation_id)
        except asyncio.CancelledError:
            await self._db.fail_operation(
                operation_id,
                "operation cancelled before completion",
                datetime.now(UTC).isoformat(),
                state="stale",
            )
            raise
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            error_payload_json: str | None = None
            if isinstance(exc, OperationFailure):
                error_text = exc.summary()
                error_payload_json = json.dumps(exc.to_error_payload(), sort_keys=True)
            await self._db.fail_operation(
                operation_id,
                error_text,
                datetime.now(UTC).isoformat(),
                error_payload_json=error_payload_json,
            )
            self._emit_completion_event(completion_event, operation_id, error=error_text)
            logger.exception(
                "Background operation failed",
                operation_id=operation_id,
                error_text=error_text,
            )
        finally:
            if token is not None:
                reset_progress_callback(token)
            if caller_token is not None:
                reset_caller_session_id(caller_token)
            if progress_tasks:
                await asyncio.gather(*progress_tasks, return_exceptions=True)
            if heartbeat_task is not None:
                stop_heartbeat.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            async with self._live_guard:
                self._live_tasks.pop(operation_id, None)

    async def _run_todo_rename(self, operation: Operation) -> str:
        payload = self._rename_payload(operation)
        rename_module = importlib.import_module("teleclaude.core.next_machine.rename")
        rename_func_obj = getattr(rename_module, "execute_todo_rename", None)
        if not callable(rename_func_obj):
            raise RuntimeError("execute_todo_rename is not available")

        rename_func = cast(Callable[..., Awaitable[str]], rename_func_obj)
        signature = inspect.signature(rename_func)
        if "current_operation_id" in signature.parameters:
            return await rename_func(
                self._db,
                payload["old_slug"],
                payload["new_slug"],
                payload["cwd"],
                current_operation_id=operation.operation_id,
            )
        return await rename_func(self._db, payload["old_slug"], payload["new_slug"], payload["cwd"])

    async def _run_todo_prepare(self, operation: Operation) -> str:
        return await self._run_todo_lifecycle_operation(
            operation,
            state_machine=lambda op: next_prepare(self._db, op.slug, op.cwd),
        )

    async def _run_todo_work(self, operation: Operation) -> str:
        return await self._run_todo_lifecycle_operation(
            operation,
            state_machine=lambda op: next_work(self._db, op.slug, op.cwd),
        )

    async def _run_task_run(self, operation: Operation) -> str:
        return await self._run_todo_lifecycle_operation(
            operation,
            state_machine=self._continue_task_run_in_place,
        )

    @staticmethod
    async def _continue_task_run_in_place(operation: Operation) -> str:
        """In-place continuation for a caller already bound to the task slug.

        A task is normally executed by a dedicated ``/next-run-task`` worker the
        bridge dispatches; an operator START is unbound and takes that path. This
        fallback only fires when the caller session already drives the slug, so it
        returns the run-task continuation rather than the SDLC work machine.
        """
        slug = operation.slug or "<auto>"
        return (
            f"TASK_RUNNING: {slug} — execute the next firing from the current task-plan, "
            "append the result to the log, and stay alive for follow-up."
        )

    async def _run_todo_lifecycle_operation(
        self,
        operation: Operation,
        *,
        state_machine: Callable[[Operation], Awaitable[str]],
    ) -> str:
        if operation.slug is None:
            return await state_machine(operation)

        slug = operation.slug
        adoption = await adopt_manual_lifecycle_session(
            operation.cwd,
            slug,
            operation.caller_session_id,
            db=self._db,
        )
        if adoption.status in {ManualLifecycleStatus.ADOPTED, ManualLifecycleStatus.ALREADY_ACTIVE}:
            return await state_machine(operation)
        if adoption.status is ManualLifecycleStatus.ALREADY_DRIVEN:
            raise ClaimConflict(slug=slug, holder=adoption.session_id)
        if adoption.status is ManualLifecycleStatus.SKIPPED:
            reason = self._format_manual_lifecycle_reason(adoption.reason)
            return f"RUNNER_NOT_DISPATCHED: {slug} {reason}"

        return await state_machine(operation)

    @staticmethod
    def _format_manual_lifecycle_reason(reason: RunnerSkipReason | str | None) -> str:
        if isinstance(reason, RunnerSkipReason):
            return reason.value
        return str(reason)

    def _ensure_rename_target_matches(self, operation: Operation, new_slug: str) -> None:
        payload = self._rename_payload(operation)
        if payload["new_slug"] != new_slug:
            raise HTTPException(status_code=409, detail="todo rename operation already targets a different slug")

    def _rename_payload(self, operation: Operation) -> dict[str, str]:
        try:
            payload = json.loads(operation.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("todo rename operation payload is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("todo rename operation payload must be an object")
        old_slug = payload.get("old_slug")
        new_slug = payload.get("new_slug")
        cwd = payload.get("cwd")
        if not isinstance(old_slug, str) or not isinstance(new_slug, str) or not isinstance(cwd, str):
            raise ValueError("todo rename operation payload must include old_slug, new_slug, and cwd")
        return {"old_slug": old_slug, "new_slug": new_slug, "cwd": cwd}

    async def _heartbeat_loop(self, operation_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                async with asyncio.timeout(self._heartbeat_interval_s):
                    await stop_event.wait()
            except TimeoutError:
                await self._db.touch_operation(operation_id, datetime.now(UTC).isoformat())

    async def _record_progress(self, operation_id: str, phase: str, decision: str, reason: str) -> None:
        await self._db.update_operation_progress(
            operation_id,
            phase=phase,
            decision=decision,
            reason=reason,
            now_iso=datetime.now(UTC).isoformat(),
        )

    async def _flush_latest_progress(
        self,
        operation_id: str,
        latest_progress: tuple[str, str, str] | None,
    ) -> None:
        if latest_progress is None:
            return
        phase, decision, reason = latest_progress
        await self._record_progress(operation_id, phase, decision, reason)

    def _emit_completion_event(
        self, completion_event: str | None, operation_id: str, *, error: str | None = None
    ) -> None:
        if not completion_event:
            return
        context = OperationCompletedContext(operation_id=operation_id, error=error)
        event_bus.emit(completion_event, context, visibility=EventVisibility.CLUSTER)  # type: ignore[arg-type]

    def _serialize_operation(self, operation: Operation) -> SerializedOperation:
        payload: SerializedOperation = {
            "operation_id": operation.operation_id,
            "kind": operation.kind,
            "state": operation.state,
            "poll_after_ms": self._poll_after_ms if operation.state in NONTERMINAL_OPERATION_STATES else 0,
            "status_path": f"/operations/{operation.operation_id}",
            "recovery_command": f"telec operations get {operation.operation_id}",
        }
        completion_event = _COMPLETION_EVENTS.get(operation.kind)
        if completion_event is not None:
            payload["completion_event"] = completion_event
        if operation.slug is not None:
            payload["slug"] = operation.slug
        if operation.progress_phase:
            payload["progress_phase"] = operation.progress_phase
        if operation.progress_decision:
            payload["progress_decision"] = operation.progress_decision
        if operation.progress_reason:
            payload["progress_reason"] = operation.progress_reason
        if operation.result_text is not None:
            payload["result"] = operation.result_text
        if operation.error_text is not None:
            payload["error"] = operation.error_text
        if operation.error_payload is not None:
            parsed_error_payload = json.loads(operation.error_payload)
            if not isinstance(parsed_error_payload, dict):
                raise ValueError("operation error_payload must be a JSON object")
            payload["error_payload"] = cast(OperationErrorPayload, parsed_error_payload)
        if operation.client_request_id is not None:
            payload["client_request_id"] = operation.client_request_id
        return payload
