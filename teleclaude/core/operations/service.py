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

from teleclaude.caller_identity import CliCaller
from teleclaude.config.machine import config
from teleclaude.constants import RUNNER_NOT_DISPATCHED
from teleclaude.core.cleanup_step import cleanup_step
from teleclaude.core.command_dispatch import invoke_command_handler
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db import Db
from teleclaude.core.db_models import Operation
from teleclaude.core.integration.state_machine import next_integrate
from teleclaude.core.models._types import JsonDict
from teleclaude.core.next_machine.create import next_create
from teleclaude.core.next_machine.kinds import KIND_TASK, canonical_kind
from teleclaude.core.next_machine.lifecycle_runner import (
    DispatchOrigin,
    ManualLifecycleStatus,
    RunnerLane,
    RunnerSkipReason,
    SessionRunner,
    default_session_runner,
    dispatch_lifecycle_session,
)
from teleclaude.core.next_machine.manual_start import (
    adopt_manual_lifecycle_session,
    resolve_manual_dispatch_intent,
    work_feedback_for_manual_skip,
)
from teleclaude.core.next_machine.prepare import next_prepare
from teleclaude.core.next_machine.slug_resolution import resolve_holder_children_db
from teleclaude.core.next_machine.work import next_work
from teleclaude.core.operation_caller_identity import (
    OperationCallerTokens,
    relayed_caller_computer,
    reset_operation_caller,
    set_operation_caller,
)
from teleclaude.core.operation_follow_through import follow_through_scope
from teleclaude.core.operation_progress import reset_progress_callback, set_progress_callback
from teleclaude.core.operations._command_outcome import command_result_outcome
from teleclaude.core.operations._delivery import (
    DeliveryOutcome,
    deliver_operation_outcome,
    deliver_recovered_operations,
    emit_and_deliver_operation_outcome,
    emit_operation_outcome,
)
from teleclaude.core.operations._kinds import (
    _COMMAND_TYPE_TO_OPERATION_KIND,
    OperationKind,
    outcome_events_for,
)
from teleclaude.core.operations._outcome import OperationCompletion
from teleclaude.core.operations._receipt import recovery_command
from teleclaude.core.operations._relayed_ownership import was_started_by_principal
from teleclaude.core.operations._rename_payload import ensure_rename_target_matches, rename_payload
from teleclaude.core.operations.job_run import JobRunRequest, job_project_path, job_run_payload, run_job_run_operation
from teleclaude.core.operations.todo_board_repair import run_todo_board_repair_operation
from teleclaude.core.operations.todo_filing import FilingOrder, run_todo_filing_operation
from teleclaude.core.operations.todo_filing import submit_todo_filing as _submit_todo_filing
from teleclaude.core.operations.todo_identity import (
    pin_operation_todo_identity,
    todo_operation_context,
    todo_operation_submission,
)
from teleclaude.core.operations.todo_removal import run_todo_remove_operation
from teleclaude.core.operations.todo_removal import submit_todo_remove as _submit_todo_remove
from teleclaude.core.operations.todo_store_switch import run_todo_store_switch_operation
from teleclaude.core.operations.todo_store_switch import submit_todo_store_switch as _submit_todo_store_switch
from teleclaude.core.project_state import resolve_project_state_root as resolve_project_root
from teleclaude.core.shutdown_drain import OwnedUnit, get_shutdown_drain
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.todos_db._exceptions import ClaimConflict, OperationErrorPayload, OperationFailure
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.identity_reach import resolve_reach
from teleclaude.types.command_wire import command_from_dict
from teleclaude.types.commands import CallerProvenance, InternalCommand

logger = get_logger(__name__)


class SerializedOperation(TypedDict, total=False):
    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str
    slug: str
    success_event: str
    failure_event: str
    computer: str
    progress_phase: str
    progress_decision: str
    progress_reason: str
    result: str
    error: str
    work_feedback: str
    error_payload: OperationErrorPayload
    client_request_id: str


TERMINAL_OPERATION_STATES = {"completed", "failed", "stale", "cancelled"}
NONTERMINAL_OPERATION_STATES = {"queued", "running"}
_HOLDER_AWARE_LANES = frozenset({RunnerLane.PREPARE, RunnerLane.WORK})
_FOLLOW_THROUGH_TASK_NAME_TEMPLATE = "operation-follow-through-{operation_id}"
_OPERATION_WORK_TEMPLATE = "operation:{kind}"
_FOLLOW_THROUGH_WORK = "operation-follow-through"
_RUNNER_NOT_DISPATCHED_RESULT_TEMPLATE = "{prefix}: {slug} {reason}"
_LEASE_TOUCH_FAILED_EVENT = "operation_lease_touch_failed"
_OPERATION_HEARTBEAT_CLEANUP_COMPONENT = "operation_heartbeat"


def _operation_payload_abandon(operation: Operation) -> bool:
    """Read the ``abandon`` discriminator from a todo-integrate operation's payload; absent reads False."""
    payload = json.loads(operation.payload_json)
    return isinstance(payload, dict) and payload.get("abandon") is True


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

    submit_todo_store_switch = _submit_todo_store_switch
    submit_todo_remove = _submit_todo_remove
    submit_todo_filing = _submit_todo_filing

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
        self._submit_locks: dict[tuple[str, str | None, str | None, str | None, bool], asyncio.Lock] = {}
        self._submit_guard = asyncio.Lock()
        self._live_tasks: dict[str, asyncio.Task[None]] = {}
        self._live_guard = asyncio.Lock()
        self._lifecycle_client_factory = lifecycle_client_factory
        self._pending_startup_recovery: list[Operation] = []
        self._filing_order = FilingOrder()

    async def start(self) -> None:
        """Normalize abandoned nonterminal operations; retain them for `deliver_startup_recovery`."""
        await self._db.backfill_operation_subject_facts()
        staled = await self._db.mark_nonterminal_operations_stale(
            error_text="daemon restarted before operation completed",
        )
        if staled:
            logger.warning("Marked %d abandoned operation(s) stale during startup", len(staled))
        self._pending_startup_recovery = staled

    async def deliver_startup_recovery(self) -> None:
        """Emit and deliver each operation `start` retained, containing per-row faults."""
        pending, self._pending_startup_recovery = self._pending_startup_recovery, []
        await deliver_recovered_operations(pending, emit=emit_operation_outcome, deliver=deliver_operation_outcome)

    async def expire_stale_operations(self) -> None:
        """Mark long-silent running operations stale and deliver each one's outcome."""
        older_than = (datetime.now(UTC) - timedelta(seconds=self._stale_after_s)).isoformat()
        staled = await self._db.expire_stale_operations(
            older_than,
            error_text="operation heartbeat expired",
        )
        for operation in staled:
            await emit_and_deliver_operation_outcome(
                operation,
                outcome=DeliveryOutcome.STALE,
                occurred_at=parse_iso_datetime(operation.completed_at),
                emit=emit_operation_outcome,
                deliver=deliver_operation_outcome,
                error=operation.error_text,
            )

    async def submit_todo_work(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
        addressed_todo_id: str | None = None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed manual-start operation.

        The single ``/todos/work`` route serves both lanes: the operation kind is
        resolved from the todo's stored ``kind`` so a ``kind=task`` start records a
        ``task_run`` operation (routed to the task-run lane) while every SDLC kind
        records ``todo_work``. No caller flag selects the lane.
        """
        operation_kind = await self._resolve_work_operation_kind(slug=slug, cwd=cwd)
        payload_json, existing_match_ok, on_existing = todo_operation_submission(
            kind=operation_kind,
            slug=slug,
            cwd=cwd,
            addressed_todo_id=addressed_todo_id,
            client_request_id=client_request_id,
        )
        return await self._submit_operation(
            kind=operation_kind,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
            client_request_id=client_request_id,
            payload_json=payload_json,
            existing_match_ok=existing_match_ok,
            on_existing=on_existing,
        )

    @staticmethod
    def _require_resolved_checkout(cwd: str) -> Path:
        """Resolve an untrusted caller cwd to its owning checkout, or raise a 400.

        Shared by every todo-operation boundary that accepts a caller-supplied
        cwd — submission and async execution alike — so a mis-resolved cwd
        fails loud instead of silently targeting a stray store.
        """
        try:
            return resolve_project_root(cwd)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _resolve_work_operation_kind(self, *, slug: str | None, cwd: str) -> str:
        """Resolve the manual-start operation kind from the todo's stored kind.

        A ``kind=task`` todo starts as a ``task_run`` operation; every SDLC kind
        (and a slug-less or stateless start) resolves to ``todo_work``.
        """
        if slug is None:
            return OperationKind.TODO_WORK
        project_root = self._require_resolved_checkout(cwd)
        todos_db = await get_workflow_store(project_root)
        state = await todos_db.read_state(slug)
        if state is None:
            return OperationKind.TODO_WORK
        raw_kind = state.get("kind")
        if not isinstance(raw_kind, str):
            return OperationKind.TODO_WORK
        try:
            kind = canonical_kind(raw_kind)
        except ValueError:
            return OperationKind.TODO_WORK
        return OperationKind.TASK_RUN if kind == KIND_TASK else OperationKind.TODO_WORK

    async def submit_todo_integrate(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
        abandon: bool = False,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-integrate operation.

        ``abandon`` is part of the submit-lock key and the reattach match, so a
        plain integrate and an ``--abandon`` integrate never reattach to each other.
        """
        payload_json = json.dumps(
            {
                "kind": OperationKind.TODO_INTEGRATE,
                "slug": slug,
                "cwd": cwd,
                "abandon": abandon,
            },
            sort_keys=True,
        )
        return await self._submit_operation(
            kind=OperationKind.TODO_INTEGRATE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
            client_request_id=client_request_id,
            payload_json=payload_json,
            abandon=abandon,
            existing_match_ok=lambda op: _operation_payload_abandon(op) == abandon,
        )

    async def submit_todo_create(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-create operation."""
        payload_json = json.dumps(
            {"kind": OperationKind.TODO_CREATE, "slug": slug, "cwd": cwd},
            sort_keys=True,
        )
        return await self._submit_operation(
            kind=OperationKind.TODO_CREATE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
            client_request_id=client_request_id,
            payload_json=payload_json,
        )

    async def submit_todo_prepare(
        self,
        *,
        slug: str | None,
        cwd: str,
        caller_session_id: str,
        client_request_id: str | None,
        addressed_todo_id: str | None = None,
    ) -> SerializedOperation:
        """Create or reattach a receipt-backed todo-prepare operation."""
        self._require_resolved_checkout(cwd)
        payload_json, existing_match_ok, on_existing = todo_operation_submission(
            kind=OperationKind.TODO_PREPARE,
            slug=slug,
            cwd=cwd,
            addressed_todo_id=addressed_todo_id,
            client_request_id=client_request_id,
        )
        return await self._submit_operation(
            kind=OperationKind.TODO_PREPARE,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
            client_request_id=client_request_id,
            payload_json=payload_json,
            existing_match_ok=existing_match_ok,
            on_existing=on_existing,
        )

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
        payload_json = json.dumps(
            {
                "kind": OperationKind.TODO_RENAME,
                "old_slug": old_slug,
                "new_slug": new_slug,
                "cwd": cwd,
            },
            sort_keys=True,
        )
        return await self._submit_operation(
            kind=OperationKind.TODO_RENAME,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=old_slug,
            client_request_id=client_request_id,
            payload_json=payload_json,
            on_existing=lambda op: ensure_rename_target_matches(op, new_slug),
        )

    async def submit_job_run(
        self,
        *,
        name: str,
        project: str | None,
        caller_session_id: str | None,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Create a receipt-backed manual run of one job; the operation ends with the run's outcome."""
        request = JobRunRequest(name=name, project=project)
        return await self._submit_operation(
            kind=OperationKind.JOB_RUN,
            caller_session_id=caller_session_id,
            cwd=None,
            session_project_path=job_project_path(request),
            slug=None,
            client_request_id=client_request_id,
            payload_json=job_run_payload(OperationKind.JOB_RUN, request),
        )

    async def submit(
        self,
        command: InternalCommand,
        *,
        caller: CallerProvenance | None,
        client_request_id: str | None,
    ) -> SerializedOperation:
        """Submit a RECEIPT command-backed operation; the command is the row's payload.

        The kind is derived from the command's own type, and the serialized
        command is persisted as ``payload_json`` — the row is self-contained
        across a daemon restart, and the wire format and the storage format
        stay the same object. A caller-less submission records no caller.
        """
        kind = _COMMAND_TYPE_TO_OPERATION_KIND.get(command.command_type)
        if kind is None:
            raise ValueError(f"unsupported command-backed operation kind: {command.command_type.value}")
        session_project_path = None
        session_id = getattr(command, "session_id", None)
        if isinstance(session_id, str) and kind in {
            OperationKind.SESSION_CLOSE,
            OperationKind.AGENT_RESTART,
            OperationKind.AGENT_HANDOFF,
        }:
            session = await self._db.get_session(session_id)
            session_project_path = session.project_path if session is not None else None
        payload_json = json.dumps(command.to_dict(), sort_keys=True)
        caller_provenance_json = json.dumps(caller.to_dict(), sort_keys=True) if caller is not None else None
        return await self._submit_operation(
            kind=kind,
            caller_session_id=caller.session_id if caller is not None else None,
            cwd=None,
            session_project_path=session_project_path,
            slug=None,
            client_request_id=client_request_id,
            payload_json=payload_json,
            caller_computer=caller.computer if caller is not None else None,
            caller_provenance_json=caller_provenance_json,
        )

    async def _submit_operation(
        self,
        *,
        kind: str,
        caller_session_id: str | None,
        cwd: str | None,
        slug: str | None,
        client_request_id: str | None,
        payload_json: str,
        abandon: bool = False,
        caller_computer: str | None = None,
        caller_provenance_json: str | None = None,
        session_project_path: str | None = None,
        existing_match_ok: Callable[[Operation], bool] | None = None,
        on_existing: Callable[[Operation], None] | None = None,
    ) -> SerializedOperation:
        """Lock, reattach, or create one operation.

        ``existing_match_ok`` narrows reuse and ``on_existing`` validates returned rows.
        Addressless submissions skip reattachment because kind/caller/cwd/slug cannot identify the target.
        """
        # A caller session on the computer whose request was carried here has its outcome delivered there.
        caller_computer = caller_computer or relayed_caller_computer(caller_session_id)
        lock = await self._get_submit_lock(
            kind=kind,
            caller_session_id=caller_session_id,
            cwd=cwd,
            slug=slug,
            abandon=abandon,
        )
        async with lock:
            if client_request_id:
                existing = await self._db.get_operation_by_request(
                    kind=kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is not None:
                    if on_existing is not None:
                        on_existing(existing)
                    return self._serialize_operation(existing)

            existing = (
                await self._db.find_matching_nonterminal_operation(
                    kind=kind,
                    caller_session_id=caller_session_id,
                    cwd=cwd,
                    slug=slug,
                    existing_match_ok=existing_match_ok,
                )
                if cwd is not None
                else None
            )
            if existing is not None:
                if on_existing is not None:
                    on_existing(existing)
                if existing.state == "queued":
                    await self._ensure_operation_task(existing.operation_id, kind=kind)
                return self._serialize_operation(existing)

            unit = get_shutdown_drain().begin_work(_OPERATION_WORK_TEMPLATE.format(kind=kind))
            operation_id = str(uuid.uuid4())
            try:
                created = await self._db.create_operation(
                    operation_id=operation_id,
                    kind=kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                    cwd=cwd,
                    slug=slug,
                    payload_json=payload_json,
                    state="queued",
                    caller_computer=caller_computer,
                    caller_provenance_json=caller_provenance_json,
                    session_project_path=session_project_path,
                )
            except IntegrityError:
                unit.release()
                if not client_request_id:
                    raise
                existing = await self._db.get_operation_by_request(
                    kind=kind,
                    caller_session_id=caller_session_id,
                    client_request_id=client_request_id,
                )
                if existing is None:
                    raise
                if on_existing is not None:
                    on_existing(existing)
                return self._serialize_operation(existing)
            except BaseException:
                unit.release()
                raise

            await self._ensure_operation_task(created.operation_id, kind=kind, unit=unit)
            return self._serialize_operation(created)

    async def get_operation_for_caller(
        self,
        *,
        operation_id: str,
        caller_session_id: str | None,
        caller: CliCaller,
        relayed_principal: str | None = None,
    ) -> SerializedOperation:
        """Return operation status if owned by the caller or an effective project admin."""
        operation = await self._db.get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        if relayed_principal is not None:
            if was_started_by_principal(operation, relayed_principal):
                return self._serialize_operation(operation)
        elif caller_session_id is not None and operation.caller_session_id == caller_session_id:
            return self._serialize_operation(operation)
        if not resolve_reach(caller).admits(operation.subject, operation.subject_owner, None):
            raise HTTPException(status_code=404, detail="operation not found")
        return self._serialize_operation(operation)

    async def _get_submit_lock(
        self,
        *,
        kind: str,
        caller_session_id: str | None,
        cwd: str | None,
        slug: str | None,
        abandon: bool = False,
    ) -> asyncio.Lock:
        key = (kind, caller_session_id, cwd, slug, abandon)
        async with self._submit_guard:
            lock = self._submit_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._submit_locks[key] = lock
            return lock

    async def _ensure_operation_task(
        self,
        operation_id: str,
        *,
        kind: str = OperationKind.TODO_WORK,
        unit: OwnedUnit | None = None,
    ) -> None:
        """Run the operation in a task that owns `unit` until its outcome is delivered.

        A caller that already admitted new work hands over the unit it registered;
        a row accepted earlier gets a unit registered here.
        """
        unit = unit or get_shutdown_drain().register(_OPERATION_WORK_TEMPLATE.format(kind=kind))
        factories: dict[str, Callable[[Operation], Awaitable[str | OperationCompletion]]] = {
            OperationKind.TODO_WORK: self._run_todo_work,
            OperationKind.TASK_RUN: self._run_task_run,
            OperationKind.TODO_INTEGRATE: lambda op: next_integrate(
                self._db, op.slug, todo_operation_context(op)[0], abandon=_operation_payload_abandon(op)
            ),
            OperationKind.TODO_CREATE: lambda op: next_create(self._db, op.slug, todo_operation_context(op)[0]),
            OperationKind.TODO_PREPARE: self._run_todo_prepare,
            OperationKind.TODO_RENAME: self._run_todo_rename,
            OperationKind.TODO_REMOVE: lambda op: run_todo_remove_operation(self._db, op),
            OperationKind.TODO_FILING: lambda op: run_todo_filing_operation(self._db, op, self._filing_order),
            OperationKind.TODO_STORE_SWITCH: lambda op: run_todo_store_switch_operation(self._db, op),
            OperationKind.TODO_BOARD_REPAIR: run_todo_board_repair_operation,
            OperationKind.SESSION_CLOSE: self._run_command_backed_operation,
            OperationKind.AGENT_RESTART: self._run_command_backed_operation,
            OperationKind.AGENT_HANDOFF: self._run_command_backed_operation,
            OperationKind.PROCEDURE_ACTIVATION: self._run_command_backed_operation,
            OperationKind.JOB_RUN: run_job_run_operation,
        }
        factory = factories.get(kind)
        if factory is None:
            unit.release()
            raise ValueError(f"unsupported operation kind: {kind}")
        operation_coro = self._run_operation(operation_id, kind, factory)
        async with self._live_guard:
            live = self._live_tasks.get(operation_id)
            if live is not None and not live.done():
                operation_coro.close()
                unit.release()
                return
            task = self._task_registry.spawn(
                unit.carry(operation_coro),
                name=f"operation-{operation_id}",
            )
            self._live_tasks[operation_id] = task

    async def _run_operation(
        self,
        operation_id: str,
        kind: str,
        coro_factory: Callable[[Operation], Awaitable[str | OperationCompletion]],
    ) -> None:
        """Generic operation runner shared by all operation kinds."""
        heartbeat_task: asyncio.Task[None] | None = None
        stop_heartbeat = asyncio.Event()
        token: Token[Callable[[str, str, str], None] | None] | None = None
        caller_token: OperationCallerTokens | None = None
        latest_progress: tuple[str, str, str] | None = None
        progress_tasks: set[asyncio.Task[None]] = set()
        operation: Operation | None = None
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
            caller_token = set_operation_caller(operation, config.computer.name)
            async with pin_operation_todo_identity(operation), follow_through_scope() as follow_throughs:
                outcome = await coro_factory(operation)
            completion = outcome if isinstance(outcome, OperationCompletion) else OperationCompletion(outcome)
            await self._flush_latest_progress(operation_id, latest_progress)
            completed_at = datetime.now(UTC)
            if await self._db.complete_operation(
                operation_id,
                completion.result,
                completed_at.isoformat(),
                work_feedback=completion.work_feedback,
            ):
                await emit_and_deliver_operation_outcome(
                    operation,
                    outcome=DeliveryOutcome.COMPLETED,
                    occurred_at=completed_at,
                    emit=emit_operation_outcome,
                    deliver=deliver_operation_outcome,
                )
            for follow_through in follow_throughs:
                follow_through_unit = get_shutdown_drain().register(_FOLLOW_THROUGH_WORK)
                self._task_registry.spawn(
                    follow_through_unit.carry(follow_through()),
                    name=_FOLLOW_THROUGH_TASK_NAME_TEMPLATE.format(operation_id=operation_id),
                )
        except asyncio.CancelledError:
            error_text = "operation cancelled before completion"
            cancelled_at = datetime.now(UTC)
            transitioned = await self._db.fail_operation(
                operation_id,
                error_text,
                cancelled_at.isoformat(),
                state="stale",
            )
            if transitioned and operation is not None:
                await emit_and_deliver_operation_outcome(
                    operation,
                    outcome=DeliveryOutcome.STALE,
                    occurred_at=cancelled_at,
                    emit=emit_operation_outcome,
                    deliver=deliver_operation_outcome,
                    error=error_text,
                )
            raise
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            error_payload_json: str | None = None
            if isinstance(exc, OperationFailure):
                error_text = exc.summary()
                error_payload_json = json.dumps(exc.to_error_payload(), sort_keys=True)
            failed_at = datetime.now(UTC)
            transitioned = await self._db.fail_operation(
                operation_id,
                error_text,
                failed_at.isoformat(),
                error_payload_json=error_payload_json,
                work_feedback=exc.work_feedback if isinstance(exc, OperationFailure) else None,
            )
            if transitioned and operation is not None:
                await emit_and_deliver_operation_outcome(
                    operation,
                    outcome=DeliveryOutcome.FAILED,
                    occurred_at=failed_at,
                    emit=emit_operation_outcome,
                    deliver=deliver_operation_outcome,
                    error=error_text,
                )
            logger.exception(
                "Background operation failed",
                operation_id=operation_id,
                error_text=error_text,
            )
        finally:
            if token is not None:
                reset_progress_callback(token)
            if caller_token is not None:
                reset_operation_caller(caller_token)
            if progress_tasks:
                await asyncio.gather(*progress_tasks, return_exceptions=True)
            if heartbeat_task is not None:
                stop_heartbeat.set()
                heartbeat_task.cancel()
                with cleanup_step(_OPERATION_HEARTBEAT_CLEANUP_COMPONENT):
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
            async with self._live_guard:
                self._live_tasks.pop(operation_id, None)

    async def _run_todo_rename(self, operation: Operation) -> str:
        payload = rename_payload(operation)
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

    async def _run_command_backed_operation(self, operation: Operation) -> str:
        """Reconstruct the command, recheck relayed receipts, and run its handler.

        Restart reports failure as an ``(ok, error)`` tuple rather than raising;
        convert ``ok=False`` into an exception so the row records failure.
        """
        payload = json.loads(operation.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("command-backed operation payload must be a JSON object")
        command = command_from_dict(cast(JsonDict, payload))
        if command.relayed_principal is not None:
            from teleclaude.core.relayed_intake import redecide_deferred  # noqa: PLC0415 - deferred cycle

            await redecide_deferred(command)
        result = await invoke_command_handler(command)
        ok, error = command_result_outcome(result)
        if ok is False:
            raise RuntimeError(error or f"{command.command_type.value} failed")
        return json.dumps(result, sort_keys=True)

    async def _run_todo_prepare(self, operation: Operation) -> str | OperationCompletion:
        return await self._run_todo_lifecycle_operation(
            operation,
            lane=RunnerLane.PREPARE,
            state_machine=lambda op, cwd: next_prepare(self._db, op.slug, cwd),
        )

    async def _run_todo_work(self, operation: Operation) -> str | OperationCompletion:
        return await self._run_todo_lifecycle_operation(
            operation,
            lane=RunnerLane.WORK,
            state_machine=lambda op, cwd: next_work(self._db, op.slug, cwd),
        )

    async def _run_task_run(self, operation: Operation) -> str | OperationCompletion:
        return await self._run_todo_lifecycle_operation(
            operation,
            lane=RunnerLane.TASK_RUN,
            state_machine=lambda op, _cwd: self._continue_task_run_in_place(op),
        )

    @staticmethod
    async def _continue_task_run_in_place(operation: Operation) -> str:
        """In-place continuation for a caller already bound to the task slug.

        A task is normally executed by a dedicated ``/run-task`` worker the
        bridge dispatches; an operator START is unbound and takes that path. This
        fallback only fires when the caller session already drives the slug, so it
        returns the run-task continuation rather than the SDLC work machine.
        """
        slug = operation.slug or "<auto>"
        return (
            f"TASK_RUNNING: {slug} — first stamp this firing's start with "
            f"`telec todo stamp {slug} --task-firing-started`, then execute the next firing "
            "from the current task-plan, record the result in the log, and stamp the firing's "
            "outcome: a success ends "
            "this session (delivered if one-shot, recorded and resting if recurring); an "
            "error stays alive as the human-inspection beacon."
        )

    async def _run_todo_lifecycle_operation(
        self,
        operation: Operation,
        *,
        lane: RunnerLane,
        state_machine: Callable[[Operation, str], Awaitable[str | OperationCompletion]],
    ) -> str | OperationCompletion:
        cwd, caller_session_id = todo_operation_context(operation)
        if operation.slug is None:
            return await state_machine(operation, cwd)

        slug = operation.slug
        project_root = self._require_resolved_checkout(cwd)
        todos_db = await get_workflow_store(project_root)

        if lane in _HOLDER_AWARE_LANES and await resolve_holder_children_db(todos_db, slug):
            return await state_machine(operation, cwd)

        adoption = await adopt_manual_lifecycle_session(
            cwd,
            slug,
            caller_session_id,
            db=self._db,
            requested_lane=lane,
        )
        if adoption.status in {ManualLifecycleStatus.ADOPTED, ManualLifecycleStatus.ALREADY_ACTIVE}:
            return await state_machine(operation, cwd)
        if adoption.status is ManualLifecycleStatus.ALREADY_DRIVEN:
            raise ClaimConflict(slug=slug, holder=adoption.session_id)
        if adoption.status is ManualLifecycleStatus.SKIPPED:
            reason = self._format_manual_lifecycle_reason(adoption.reason)
            return OperationCompletion(
                _RUNNER_NOT_DISPATCHED_RESULT_TEMPLATE.format(prefix=RUNNER_NOT_DISPATCHED, slug=slug, reason=reason),
                work_feedback=adoption.work_feedback,
            )

        intent, skip_reason = await resolve_manual_dispatch_intent(todos_db, slug, requested_lane=lane)
        if intent is None:
            reason = skip_reason.value if skip_reason is not None else RunnerSkipReason.INVALID_KIND.value
            return OperationCompletion(
                _RUNNER_NOT_DISPATCHED_RESULT_TEMPLATE.format(prefix=RUNNER_NOT_DISPATCHED, slug=slug, reason=reason),
                work_feedback=work_feedback_for_manual_skip(skip_reason),
            )
        client = self._lifecycle_client_factory()
        await client.connect()
        try:
            session_id = await dispatch_lifecycle_session(
                client=client,
                runtime_db=self._db,
                todos_db=todos_db,
                project_path=str(project_root),
                intent=intent,
                origin=DispatchOrigin.MANUAL,
            )
        finally:
            await client.close()
        return f"RUNNER_DISPATCHED: {slug} {intent.lane.value} {session_id}"

    @staticmethod
    def _format_manual_lifecycle_reason(reason: RunnerSkipReason | str | None) -> str:
        if isinstance(reason, RunnerSkipReason):
            return reason.value
        return str(reason)

    async def _heartbeat_loop(self, operation_id: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                async with asyncio.timeout(self._heartbeat_interval_s):
                    await stop_event.wait()
            except TimeoutError:
                try:
                    await self._db.touch_operation(operation_id, datetime.now(UTC).isoformat())
                except Exception:
                    logger.exception(_LEASE_TOUCH_FAILED_EVENT, operation_id=operation_id)

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

    def _serialize_operation(self, operation: Operation) -> SerializedOperation:
        payload: SerializedOperation = {
            "operation_id": operation.operation_id,
            "kind": operation.kind,
            "state": operation.state,
            "poll_after_ms": self._poll_after_ms if operation.state in NONTERMINAL_OPERATION_STATES else 0,
            "status_path": f"/operations/{operation.operation_id}",
            "recovery_command": recovery_command(operation.operation_id),
            "computer": config.computer.name,
        }
        events = outcome_events_for(operation.kind)
        if events is not None:
            payload["success_event"], payload["failure_event"] = events
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
        if operation.work_feedback is not None:
            payload["work_feedback"] = operation.work_feedback
        return payload
