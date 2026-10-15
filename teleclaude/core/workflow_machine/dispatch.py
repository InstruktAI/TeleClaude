"""The platform's creative dispatch of a holder's handoff: start the phase's worker once, name who hears it idle.

``local/projects/teleclaude/spec/feature/workflow/item-lifecycle`` (the creative capabilities, row 6): the dispatch
completes idempotently after the sweep found nothing and before the claim is released. The start is claimed on the item
before the session exists, by a conditional write that records the process making it; the session it creates is named on
the same record, and the session registered to hear it idle is recorded when that registration succeeds. A retry after any
interruption therefore finds the claim, tells an interrupted start from a running one by the recorded process, adopts a
session the interrupted start created (open or already ended, of the same command, project and slug, created since the
claim), and starts nothing twice. Two concurrent reconciliations contend on the one claim.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.config.machine import config
from teleclaude.core.db import db
from teleclaude.core.next_machine._types import StateValue
from teleclaude.core.process_identity import ProcessState, probe_process, start_identity
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.workflow_record import DispatchStart, WorkflowRecord

OWNER_WALK_CAP = 32
NO_OWNER = ("", "")
NO_IDENTITY = "the process that starts the creative worker cannot be named, so the start is not made"
CLAIM_ROUNDS = 3


class DispatchPending(Exception):
    """The dispatch cannot finish yet: another start is running, or the process of an interrupted one is unknown."""


class DispatchRefused(Exception):
    """The dispatch cannot be made at all."""


@dataclass(frozen=True)
class WorkerSpec:
    """The worker a creative phase starts, as the handoff's effect carries it."""

    command: str
    args: str
    project_root: str
    slug: str
    recipient: str


@dataclass(frozen=True)
class DispatchResult:
    """The worker session the dispatch ran and the session registered to hear it idle (empty when none)."""

    session_id: str
    supervisor: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def continuation_owner(recipient: str) -> tuple[str, str]:
    """The nearest open session above the dispatch's recipient and its tmux name; empty when none is above it.

    The recipient has handed the item on and does not continue the creative lane: the session that started it, or the
    nearest open one above, is told when the worker idles and calls the next step.
    """
    current = recipient
    for _ in range(OWNER_WALK_CAP):
        session = await db.get_session(current)
        if session is None or not session.initiator_session_id:
            return NO_OWNER
        current = session.initiator_session_id
        owner = await db.get_session(current)
        if owner is not None and owner.closed_at is None:
            return owner.session_id, owner.tmux_session_name or NO_OWNER[1]
    return NO_OWNER


async def _write(store: WorkflowStore, slug: str, change: Callable[[WorkflowRecord], bool]) -> None:
    """Apply a change to the item's record in one conditional write; ``change`` returns whether it altered anything."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current).model_copy(deep=True)
        if not change(record):
            return None
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: record.to_state()})

    await store.commit_item_change(slug, expect_digests={}, mutate=mutate, updated_by=None)


async def _read_start(store: WorkflowStore, todo_id: str, act_key: str) -> DispatchStart | None:
    state = await store.read_state_by_id(todo_id)
    return workflow_record_of(state).dispatch_starts.get(act_key) if state is not None else None


async def _adopt(spec: WorkerSpec, since: str) -> str:
    """The session an interrupted start created: the same command, project and slug, opened since the claim."""
    root = Path(spec.project_root).resolve()
    for session in await db.list_sessions(include_closed=True, include_headless=True):
        created = session.created_at
        if (
            session.command == spec.command
            and session.working_slug == spec.slug
            and session.project_path
            and Path(session.project_path).resolve() == root
            and not session.initiator_session_id
            and created is not None
            and created.isoformat() >= since
        ):
            return session.session_id
    return ""


async def _claim(store: WorkflowStore, spec: WorkerSpec, act_key: str, identity: str) -> bool:
    """Claim the start for this process; False when another claim stands that is not known to have ended."""
    taken: list[bool] = []

    def change(record: WorkflowRecord) -> bool:
        existing = record.dispatch_starts.get(act_key)
        if existing is not None and (
            existing.session_id or probe_process(existing.owner_pid, existing.owner_identity) is not ProcessState.ENDED
        ):
            taken.append(False)
            return False
        record.dispatch_starts[act_key] = DispatchStart(
            started_at=_now(), owner_pid=os.getpid(), owner_identity=identity
        )
        taken.append(True)
        return True

    await _write(store, spec.slug, change)
    return taken[0] if taken else False


async def _release_claim(store: WorkflowStore, spec: WorkerSpec, act_key: str) -> None:
    """Withdraw this process's unnamed claim after a failed start, so a retry can claim it."""

    def change(record: WorkflowRecord) -> bool:
        existing = record.dispatch_starts.get(act_key)
        if existing is None or existing.session_id or existing.owner_pid != os.getpid():
            return False
        del record.dispatch_starts[act_key]
        return True

    await _write(store, spec.slug, change)


async def _name(store: WorkflowStore, spec: WorkerSpec, act_key: str, session_id: str) -> None:
    def change(record: WorkflowRecord) -> bool:
        existing = record.dispatch_starts.get(act_key)
        if existing is None or existing.session_id == session_id:
            return False
        record.dispatch_starts[act_key] = existing.model_copy(update={"session_id": session_id})
        return True

    await _write(store, spec.slug, change)


async def _create(spec: WorkerSpec) -> str:
    """Start the worker through the platform's session runner, with the daemon's own credential."""
    from teleclaude.core.next_machine.lifecycle_runner import (  # noqa: PLC0415 - deferred cycle: the runner reads this package
        default_session_runner,
    )

    client = default_session_runner()
    await client.connect()
    try:
        created = await client.run_session(
            command=spec.command, project_path=spec.project_root, args=spec.args, detach=True
        )
    finally:
        await client.close()
    return str(created.session_id)


async def _worker_session(store: WorkflowStore, todo_id: str, spec: WorkerSpec, act_key: str) -> str:
    """The worker session of this handoff: the one already named, one an interrupted start created, or a new one."""
    identity = start_identity(os.getpid())
    if not identity:
        raise DispatchRefused(NO_IDENTITY)
    for _ in range(CLAIM_ROUNDS):
        existing = await _read_start(store, todo_id, act_key)
        if existing is not None and existing.session_id:
            return existing.session_id
        if (
            existing is not None
            and probe_process(existing.owner_pid, existing.owner_identity) is not ProcessState.ENDED
        ):
            raise DispatchPending(act_key)
        adopted = await _adopt(spec, existing.started_at) if existing is not None else ""
        if adopted:
            await _claim(store, spec, act_key, identity)
            await _name(store, spec, act_key, adopted)
            return adopted
        if not await _claim(store, spec, act_key, identity):
            continue
        try:
            session_id = await _create(spec)
        except BaseException:
            await _release_claim(store, spec, act_key)
            raise
        await _name(store, spec, act_key, session_id)
        return session_id
    raise DispatchPending(act_key)


async def _supervise(store: WorkflowStore, todo_id: str, spec: WorkerSpec, act_key: str, session_id: str) -> str:
    """Register the continuing session to hear the worker idle; recorded only when the registration succeeded."""
    from teleclaude.core.session_listeners import (  # noqa: PLC0415 - deferred cycle: listeners read the session store
        establish_supervision,
    )

    existing = await _read_start(store, todo_id, act_key)
    if existing is not None and existing.supervised:
        return existing.supervised
    owner_id, owner_tmux = await continuation_owner(spec.recipient)
    if not owner_id:
        return ""
    established = await establish_supervision(
        session_id, owner_id, owner_tmux, caller_computer=config.computer.name, startup_work_expected=True
    )
    if not established:
        return ""

    def change(record: WorkflowRecord) -> bool:
        start = record.dispatch_starts.get(act_key)
        if start is None or start.supervised == owner_id:
            return False
        record.dispatch_starts[act_key] = start.model_copy(update={"supervised": owner_id})
        return True

    await _write(store, spec.slug, change)
    return owner_id


async def dispatch_worker(store: WorkflowStore, todo_id: str, spec: WorkerSpec, act_key: str) -> DispatchResult:
    """Run the handoff's worker dispatch to completion, idempotently, and report what it did."""
    session_id = await _worker_session(store, todo_id, spec, act_key)
    supervisor = await _supervise(store, todo_id, spec, act_key, session_id)
    return DispatchResult(session_id=session_id, supervisor=supervisor)
