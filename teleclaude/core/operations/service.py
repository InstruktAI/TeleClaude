"""Durable receipt-backed operation runtime for long-running local workflows."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import HTTPException
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import IntegrityError

from teleclaude.api_models import OperationStatusPayload
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.next_machine import next_work
from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

OPERATION_KIND_TODO_WORK = "todo_work"
TERMINAL_OPERATION_STATES = {"completed", "failed", "stale", "cancelled"}
NONTERMINAL_OPERATION_STATES = {"queued", "running"}

_operations_service: OperationsService | None = None
_progress_callback: ContextVar[Callable[[str, str, str], None] | None] = ContextVar(
    "operations_progress_callback",
    default=None,
)


def set_operations_service(service: "OperationsService") -> None:
    """Install the process-wide operations service."""
    global _operations_service
    _operations_service = service


def get_operations_service() -> "OperationsService":
    """Return the configured operations service."""
    if _operations_service is None:
        raise HTTPException(status_code=503, detail="operations service not initialized")
    return _operations_service


def emit_operation_progress(phase: str, decision: str, reason: str) -> None:
    """Forward next-machine phase updates to the active operation, if any."""
    callback = _progress_callback.get()
    if callback is not None:
        callback(phase, decision, reason)


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

    async def start(self) -> None:
        """Normalize any abandoned nonterminal operations from a previous daemon run."""
        stale_count = await self._db.mark_nonterminal_operations_stale(
            error_text="daemon restarted before operation completed",
        )
        if stale_count:
            logger.warning("Marked %d abandoned operation(s) stale during startup", stale_count)

    async def expire_stale_operations(self) -> int:
        """Mark long-silent running operations stale."""
        older_than = (datetime.now(timezone.utc) - timedelta(seconds=self._stale_after_s)).isoformat()
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
    ) -> OperationStatusPayload:
        """Create or reattach a receipt-backed todo-work operation."""
        lock = await self._get_submit_lock(
            kind=OPERATION_KIND_TODO_WORK,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=OPERATION_KIND_TODO_WORK,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    return self._serialize_operation(existing)

            existing = await self._db.find_matching_nonterminal_operation(
                kind=OPERATION_KIND_TODO_WORK,
                caller_session_id=caller_session_id,
                cwd=cwd,
                slug=slug,
            )
            if existing is not None:
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id)
                return self._serialize_operation(existing)

            payload_json = json.dumps(
                {
                    "kind": OPERATION_KIND_TODO_WORK,
                    "slug": slug,
                    "cwd": cwd,
                },
                sort_keys=True,
            )
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=OPERATION_KIND_TODO_WORK,
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
                    kind=OPERATION_KIND_TODO_WORK,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                return self._serialize_operation(existing)

            await self._ensure_operation_task(created.operation_id)
            return self._serialize_operation(created)

    async def get_operation_for_caller(
        self,
        *,
        operation_id: str,
        caller_session_id: str,
        human_role: str | None,
    ) -> OperationStatusPayload:
        """Return operation status if owned by the caller or an admin."""
        operation = await self._db.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        if human_role != "admin" and operation.caller_session_id != caller_session_id:
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

    async def _ensure_operation_task(self, operation_id: str) -> None:
        async with self._live_guard:
            live = self._live_tasks.get(operation_id)
            if live is not None and not live.done():
                return
            task = self._task_registry.spawn(
                self._run_todo_work_operation(operation_id),
                name=f"operation-{operation_id[:8]}",
            )
            self._live_tasks[operation_id] = task

    async def _run_todo_work_operation(self, operation_id: str) -> None:
        heartbeat_task: asyncio.Task[None] | None = None
        stop_heartbeat = asyncio.Event()
        token: Token[Callable[[str, str, str], None] | None] | None = None
        latest_progress: tuple[str, str, str] | None = None
        progress_tasks: set[asyncio.Task[None]] = set()
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            claimed = await self._db.claim_operation(operation_id, now_iso)
            if not claimed:
                return

            operation = await self._db.get_operation(operation_id)
            if operation is None:
                return

            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(operation_id, stop_heartbeat),
                name=f"operation-heartbeat-{operation_id[:8]}",
            )

            def _capture_progress(phase: str, decision: str, reason: str) -> None:
                nonlocal latest_progress
                latest_progress = (phase, decision, reason)
                task = asyncio.create_task(self._record_progress(operation_id, phase, decision, reason))
                progress_tasks.add(task)
                task.add_done_callback(progress_tasks.discard)

            token = _progress_callback.set(_capture_progress)
            result = await next_work(
                self._db,
                operation.slug,
                operation.cwd,
                operation.caller_session_id,
            )
            if latest_progress is not None:
                phase, decision, reason = latest_progress
                await self._record_progress(operation_id, phase, decision, reason)
            await self._db.complete_operation(
                operation_id,
                result,
                datetime.now(timezone.utc).isoformat(),
            )
        except asyncio.CancelledError:
            await self._db.fail_operation(
                operation_id,
                "operation cancelled before completion",
                datetime.now(timezone.utc).isoformat(),
                state="stale",
            )
            raise
        except Exception as exc:  # noqa: BLE001 - durable background failure record
            await self._db.fail_operation(
                operation_id,
                f"{type(exc).__name__}: {exc}",
                datetime.now(timezone.utc).isoformat(),
            )
            logger.exception("Background operation failed for %s", operation_id)
        finally:
            if token is not None:
                _progress_callback.reset(token)
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

    async def _heartbeat_loop(self, operation_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._heartbeat_interval_s)
            except TimeoutError:
                await self._db.touch_operation(operation_id, datetime.now(timezone.utc).isoformat())

    async def _record_progress(self, operation_id: str, phase: str, decision: str, reason: str) -> None:
        await self._db.update_operation_progress(
            operation_id,
            phase=phase,
            decision=decision,
            reason=reason,
            now_iso=datetime.now(timezone.utc).isoformat(),
        )

    def _serialize_operation(self, operation: Operation) -> OperationStatusPayload:
        payload: OperationStatusPayload = {
            "operation_id": operation.operation_id,
            "kind": operation.kind,
            "state": operation.state,
            "poll_after_ms": self._poll_after_ms if operation.state in NONTERMINAL_OPERATION_STATES else 0,
            "status_path": f"/operations/{operation.operation_id}",
            "recovery_command": f"telec operations get {operation.operation_id}",
        }
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
        if operation.client_request_id is not None:
            payload["client_request_id"] = operation.client_request_id
        return payload
