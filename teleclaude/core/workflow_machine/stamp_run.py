"""Running a stamp so that at most one stamp's gates run on an item, and every repeat observes its result.

The ownership protocol is ``local/projects/teleclaude/design/process-lifecycle`` (gate runner ownership); the
contract is ``local/projects/teleclaude/spec/feature/workflow/work-review-cycle``. A stamp takes the item's slot
(the flight on the item record), classifies any earlier unit through its registry row, spawns the runner, makes
the runner's identity durable in the registry, and only then lets the workload start. A unit is released only when
it is observed ended or classified dead; one that may still run holds the slot and nothing is signalled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.db import db
from teleclaude.core.next_machine.git_ops import has_build_commits_beyond_main
from teleclaude.core.process_group import UnitClass, classify_unit
from teleclaude.core.process_identity import boot_session
from teleclaude.core.workflow_machine.act_types import ActRefused, ActRequest, Refusal
from teleclaude.core.workflow_machine.gate_unit import (
    RunnerHandle,
    RunnerNotReady,
    await_outcome,
    end_bootstrap,
    send_go,
    start_runner,
)
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_machine.stamp import NO_HEAD, StampRefusal, check_refs, worktree_path
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase, StampInFlight

logger = get_logger(__name__)

GATE_OWNER_TEMPLATE: Final = "stamp-gate:{item_id}"
LEASE_SECONDS: Final = 900
ATTACH_DEADLINE_SECONDS: Final = 900
ATTACH_POLL_SECONDS: Final = 1.0
_RUNNING: dict[str, asyncio.Task[str]] = {}
_SLOT_LOCKS: dict[str, asyncio.Lock] = {}


class GateUnsettled(Exception):
    """The gate's processes could not be shown to have ended; the slot stays with them."""


@dataclass
class _StartState:
    """How far a unit's start got: the runner held, the row written, and whether GO may have reached the runner."""

    handle: RunnerHandle | None = None
    registered: bool = False
    go_may_have_been_sent: bool = False
    ended: bool = False


class Slot(StrEnum):
    """What taking the stamp slot found."""

    RECORDED = "recorded"
    OWNED = "owned"
    ATTACH = "attach"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _forget(key: str, task: asyncio.Task[str]) -> None:
    """Drop a settled task from the running set, retrieving its outcome so none goes unobserved."""
    _RUNNING.pop(key, None)
    if not task.cancelled():
        task.exception()


def _flight_of(raw: dict[str, StateValue] | None) -> StampInFlight | None:
    return workflow_record_of(raw).stamp_in_flight if raw is not None else None


async def _classify_flight(flight: StampInFlight) -> tuple[UnitClass, int]:
    """Classify the unit an earlier invocation left, and the group to name when it is unknown.

    A task of this process that is still running is live. Otherwise only the registry row decides, and only on the
    computer and boot that wrote it. No row means no workload can exist: a row is written before the workload may
    start and deleted only after the unit was proved dead or ended.
    """
    task = _RUNNING.get(flight.key)
    if task is not None and not task.done():
        return UnitClass.LIVE, 0
    if flight.host != config.computer.name:
        return UnitClass.UNKNOWN, 0
    row = await db.get_process_spawn_registry_entry(flight.owner_key)
    if row is None:
        return UnitClass.DEAD, 0
    unit = classify_unit(
        host=row.host or "",
        boot=row.boot or "",
        pid=row.pid,
        identity=row.identity or "",
        local_host=config.computer.name,
        local_boot=boot_session(),
    )
    if unit is UnitClass.DEAD and row.generation:
        await db.delete_identified_registry_entry(owner=row.owner, generation=row.generation)
    return unit, row.pid


def _take(
    request: ActRequest, session_id: str, key: str, owner_key: str, expected: str | None, outcome: list[Slot]
) -> Callable[..., ItemChange | None]:
    """The change that takes the slot, decided against the state read inside the commit."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            raise ActRefused(Refusal.UNKNOWN_ITEM.value.format(act=request.act.value, item=request.item))
        state = TodoState.model_validate(current)
        record = state.workflow
        if key in record.act_status:
            outcome.append(Slot.RECORDED)
            return None
        if read_phase(state, integration_head=NO_HEAD, creative_incomplete=False).phase is not Phase.WORK:
            raise ActRefused(Refusal.WRONG_PHASE.value.format(act=request.act.value, phase=state.lifecycle_phase))
        if state.active_runner != session_id:
            raise ActRefused(Refusal.HOLDER_CHANGED.value.format(act=request.act.value))
        flight = record.stamp_in_flight
        if (flight.key if flight is not None else None) != expected:
            raise ActRefused(Refusal.STAMP_IN_FLIGHT.value.format(act=request.act.value))
        updated = record.model_copy(deep=True)
        updated.stamp_in_flight = StampInFlight(
            key=key,
            sha=request.sha,
            session_id=session_id,
            started_at=_now(),
            host=config.computer.name,
            owner_key=owner_key,
        )
        outcome.append(Slot.OWNED)
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    return mutate


def _release(key: str) -> Callable[..., ItemChange | None]:
    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        if record.stamp_in_flight is None or record.stamp_in_flight.key != key:
            return None
        updated = record.model_copy(deep=True)
        updated.stamp_in_flight = None
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    return mutate


async def _release_slot(store: WorkflowStore, request: ActRequest, session_id: str, key: str) -> None:
    await store.commit_item_change(request.item, expect_digests={}, mutate=_release(key), updated_by=session_id)


async def _prior_unit_allows(store: WorkflowStore, request: ActRequest, key: str) -> tuple[str | None, Slot | None]:
    """The key of the flight to replace (None when there is none), or the slot outcome that ends the attempt.

    A live unit of this invocation attaches; a live unit of another is refused; an unknown unit holds the slot and is
    refused naming where it may still run; a dead unit has its row removed and is replaced.
    """
    flight = _flight_of(await store.read_state(request.item))
    if flight is None:
        return None, None
    unit, pgid = await _classify_flight(flight)
    if unit is UnitClass.DEAD:
        return flight.key, None
    if unit is UnitClass.LIVE:
        if flight.key == key:
            return flight.key, Slot.ATTACH
        raise ActRefused(Refusal.STAMP_IN_FLIGHT.value.format(act=request.act.value))
    if flight.host != config.computer.name:
        raise ActRefused(StampRefusal.UNIT_STARTED_ELSEWHERE.value.format(host=flight.host))
    raise ActRefused(StampRefusal.UNKNOWN_UNIT.value.format(pgid=pgid))


async def _start_unit(request: ActRequest, owner_key: str, key: str, state: _StartState) -> RunnerHandle:
    """Check the references, spawn the runner, record its identity and release the workload.

    ``state`` records how far the start got, so a failure or a cancellation is judged by it afterwards.
    """
    worktree = str(worktree_path(request.project_root, request.item))
    boot = boot_session()
    if not boot or not config.computer.name:
        raise ActRefused(StampRefusal.NO_IDENTITY.value)
    await check_refs(request.project_root, request.item, request.sha)
    if not await asyncio.to_thread(has_build_commits_beyond_main, worktree):
        raise ActRefused(StampRefusal.NO_BUILD_COMMITS.value)
    try:
        state.handle = await asyncio.to_thread(start_runner, worktree, request.item)
    except RunnerNotReady as failure:
        raise ActRefused(StampRefusal.NOT_STARTED.value.format(reason=str(failure))) from failure
    state.registered = await db.insert_identified_registry_entry(
        owner=owner_key,
        pid=state.handle.pid,
        lease_expires_at=(datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        identity=state.handle.identity,
        host=config.computer.name,
        boot=boot,
        generation=key,
    )
    if not state.registered:
        raise ActRefused(StampRefusal.ROW_EXISTS.value)
    state.go_may_have_been_sent = True
    await asyncio.to_thread(send_go, state.handle)
    return state.handle


async def _undo_before_go(owner_key: str, key: str, state: _StartState) -> None:
    """Take back a start that failed before GO could have reached the runner: no workload exists to leave behind."""
    if state.handle is not None:
        await asyncio.to_thread(end_bootstrap, state.handle)
    if state.registered:
        await db.delete_identified_registry_entry(owner=owner_key, generation=key)


async def _run_unit(
    store: WorkflowStore,
    request: ActRequest,
    session_id: str,
    key: str,
    owner_key: str,
    lock: asyncio.Lock,
    commit: Callable[[], Awaitable[str]],
) -> str:
    """Start the unit, wait for it, record its end, check the references again and commit.

    This is one task that owns the slot from the moment it is taken, so no caller's cancellation stops it. A failure
    before GO could have been delivered is undone completely. Once GO may have reached the runner, nothing is deleted
    or released until the unit is observed ended: a failure then, or a cancellation at any point, keeps the row and
    the slot, and the classifier decides later. The unit is recorded as ended only after the runner has exited and
    no other live member of its group is left.
    """
    state = _StartState()
    try:
        async with lock:
            try:
                await _start_unit(request, owner_key, key, state)
            except Exception:
                if not state.go_may_have_been_sent:
                    await _undo_before_go(owner_key, key, state)
                    raise
        assert state.handle is not None  # a start that got past GO holds its handle
        result = await asyncio.to_thread(await_outcome, state.handle)
        if not result.ended:
            raise GateUnsettled(StampRefusal.UNSETTLED.value)
        state.ended = True
        await db.delete_identified_registry_entry(owner=owner_key, generation=key)
        if not result.outcome.passed:
            raise ActRefused(StampRefusal.GATE_FAILED.value.format(output=result.outcome.output))
        await check_refs(request.project_root, request.item, request.sha)
        return await commit()
    except GateUnsettled:
        raise
    except Exception:
        if state.go_may_have_been_sent and not state.ended:
            raise  # the unit may still run: the row and the slot stay until it is observed ended
        await _release_slot(store, request, session_id, key)
        raise


async def _acquire(
    store: WorkflowStore,
    request: ActRequest,
    session_id: str,
    item_id: str,
    key: str,
    commit: Callable[[], Awaitable[str]],
) -> tuple[Slot, asyncio.Task[str] | None]:
    """Classify the earlier unit, take the slot and start the task that owns the new unit, with no other stamp between.

    One lock per item covers the classification, the slot and the task's whole start phase, so no other stamp of the
    item in this process interleaves; the task is registered before the lock is released.
    """
    owner_key = GATE_OWNER_TEMPLATE.format(item_id=item_id)
    lock = _SLOT_LOCKS.setdefault(f"{request.project_root}:{request.item}", asyncio.Lock())
    async with lock:
        expected, ended = await _prior_unit_allows(store, request, key)
        if ended is Slot.ATTACH:
            return Slot.ATTACH, None
        outcome: list[Slot] = []
        await store.commit_item_change(
            request.item,
            expect_digests={},
            mutate=_take(request, session_id, key, owner_key, expected, outcome),
            updated_by=session_id,
        )
        if outcome[-1] is not Slot.OWNED:
            return outcome[-1], None
        task = asyncio.ensure_future(_run_unit(store, request, session_id, key, owner_key, lock, commit))
        _RUNNING[key] = task
        task.add_done_callback(partial(_forget, key))
    return Slot.OWNED, task


async def run_stamp(
    store: WorkflowStore,
    request: ActRequest,
    session_id: str,
    item_id: str,
    key: str,
    commit: Callable[[], Awaitable[str]],
) -> str:
    """Perform a stamp so that at most one stamp's gates run on an item, and every repeat observes its result.

    The running work is a task independent of the request that started it: a request that ends does not release the
    slot or stop the gates, and a repeat of the same invocation attaches until it records.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ATTACH_DEADLINE_SECONDS
    while True:
        slot, task = await _acquire(store, request, session_id, item_id, key, commit)
        if slot is Slot.RECORDED:
            return key
        if task is not None:
            return await asyncio.shield(task)
        if loop.time() >= deadline:
            raise ActRefused(Refusal.STAMP_IN_FLIGHT.value.format(act=request.act.value))
        await asyncio.sleep(ATTACH_POLL_SECONDS)
