"""The stamp's pre-commit work: the reference checks and the build gates, each run once per invocation.

``local/projects/teleclaude/spec/feature/workflow/work-review-cycle`` is the contract. A stamp at commit
H is accepted only while H is the integration head, the item's worktree branch head and H agree, the
worktree is clean, the worktree carries file-changing commits beyond the shared branch, and the
project's native test target passes. The references are read again after the gates ran.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.git_ops import (
    get_head_commit,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
)
from teleclaude.core.workflow_machine.act_types import ActRefused, ActRequest, Refusal
from teleclaude.core.workflow_machine.gate_unit import (
    UNSETTLED_TEMPLATE,
    is_group_alive,
    is_process_alive,
    is_token_alive,
    run_in_runner,
    settle_group,
)
from teleclaude.core.workflow_machine.phase_reading import read_phase
from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.workflow_store.types import ItemChange
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase, StampInFlight

logger = get_logger(__name__)


class StampRefusal(StrEnum):
    """Why a stamp is refused; each names the disagreeing references or the failing gate."""

    NOT_HEAD = "stamp: {sha} is not the integration head ({head})"
    WORKTREE_HEAD = "stamp: the worktree branch head {worktree} differs from {sha}"
    UNCLEAN = "stamp: the worktree has uncommitted changes"
    NO_BUILD_COMMITS = "stamp: the worktree carries no file-changing commit beyond the shared branch"
    GATE_FAILED = "stamp: {output}"
    HEAD_UNKNOWN = "stamp: the integration head of {item} cannot be read"


NO_HEAD: Final = ""
ORIGIN: Final = "origin"
BRANCH_REF_TEMPLATE: Final = "refs/heads/{branch}"
REMOTE_READ_TIMEOUT_SECONDS: Final = 10
REMOTE_READ_FAILED_TEMPLATE: Final = "the integration ref of {item} cannot be read: {reason}"


def worktree_path(project_root: str, item: str) -> Path:
    """The item's worktree, whose name derives from the item identity."""
    return Path(project_root) / WORKTREE_DIR / item


class RemoteReadFailed(Exception):
    """The branch on origin could not be observed; distinct from observing that it does not exist."""


def _read_remote_head(project_root: str, item: str) -> str:
    """One bounded read of the branch on origin; empty only when the remote answered and has no such branch."""
    try:
        output = Repo(project_root).git.ls_remote(
            ORIGIN, BRANCH_REF_TEMPLATE.format(branch=item), kill_after_timeout=REMOTE_READ_TIMEOUT_SECONDS
        )
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        raise RemoteReadFailed(REMOTE_READ_FAILED_TEMPLATE.format(item=item, reason=str(exc).strip())) from exc
    parts = output.strip().split()
    return parts[0] if parts else NO_HEAD


async def integration_head(project_root: str, item: str) -> str:
    """The commit the item's integration ref carries now; empty when it does not exist.

    Raises ``RemoteReadFailed`` when the remote cannot be read within the bound.
    """
    return await asyncio.to_thread(_read_remote_head, project_root, item)


async def check_refs(project_root: str, item: str, sha: str) -> None:
    """Refuse when the integration head, the worktree head and the stamped commit disagree, or the worktree is dirty."""
    try:
        head = await integration_head(project_root, item)
    except RemoteReadFailed as failure:
        raise ActRefused(str(failure)) from failure
    if not head:
        raise ActRefused(StampRefusal.HEAD_UNKNOWN.value.format(item=item))
    if head != sha:
        raise ActRefused(StampRefusal.NOT_HEAD.value.format(sha=sha, head=head))
    worktree = await asyncio.to_thread(get_head_commit, str(worktree_path(project_root, item)))
    if worktree != sha:
        raise ActRefused(StampRefusal.WORKTREE_HEAD.value.format(worktree=worktree or NO_HEAD, sha=sha))
    if await asyncio.to_thread(has_uncommitted_changes, project_root, item):
        raise ActRefused(StampRefusal.UNCLEAN.value)


class GateUnsettled(Exception):
    """The gate's processes could not be shown to have ended; the slot stays with them."""


async def run_gates(
    project_root: str,
    item: str,
    key: str,
    record_runner: Callable[[int, float], Coroutine[None, None, None]],
    record_unit: Callable[[int, float], Coroutine[None, None, None]],
) -> None:
    """Refuse unless the worktree carries build commits and the project's native test target passes.

    The gates run in a runner process that enforces its own time limit. The invocation stays marked as
    running until its gate unit has been observed settled, whatever happens to the task awaiting it, and a
    unit that cannot be settled keeps the slot.
    """
    worktree = str(worktree_path(project_root, item))
    if not await asyncio.to_thread(has_build_commits_beyond_main, worktree):
        raise ActRefused(StampRefusal.NO_BUILD_COMMITS.value)
    loop = asyncio.get_running_loop()

    def reporter(record: Callable[[int, float], Coroutine[None, None, None]]) -> Callable[[int, float], None]:
        def report(pid: int, started: float) -> None:
            try:
                asyncio.run_coroutine_threadsafe(record(pid, started), loop).result(RECORD_TIMEOUT_SECONDS)
            except Exception:  # the probes still find the processes; recording must never fail the gate
                logger.warning(RECORD_FAILED_LOG, item=item, exc_info=True)

        return report

    with _THREADS_LOCK:
        _GATE_THREADS.add(key)
    try:
        run = await asyncio.to_thread(
            run_in_runner, worktree, item, key, reporter(record_runner), reporter(record_unit)
        )
    finally:
        with _THREADS_LOCK:
            _GATE_THREADS.discard(key)
    if not run.settled:
        raise GateUnsettled(UNSETTLED_TEMPLATE)
    if not run.outcome.passed:
        raise ActRefused(StampRefusal.GATE_FAILED.value.format(output=run.outcome.output))


PROCESS_INSTANCE: Final = uuid.uuid4().hex
GATE_CEILING_SECONDS: Final = 660
UNRECORDED_BOUND_SECONDS: Final = 900
RECORD_TIMEOUT_SECONDS: Final = 10
RUNNER_PID_FIELD: Final = "runner_pid"
RUNNER_STARTED_FIELD: Final = "runner_started"
UNIT_PGID_FIELD: Final = "unit_pgid"
UNIT_STARTED_FIELD: Final = "unit_started"
RECORD_FAILED_LOG: Final = "the gate's process identity could not be recorded"
ATTACH_DEADLINE_SECONDS: Final = 900
ATTACH_POLL_SECONDS: Final = 1.0
_RUNNING: dict[str, asyncio.Task[str]] = {}
_GATE_THREADS: set[str] = set()
_THREADS_LOCK = threading.Lock()
_SLOT_LOCKS: dict[str, asyncio.Lock] = {}


class Slot(StrEnum):
    """What taking the stamp slot found."""

    RECORDED = "recorded"
    OWNED = "owned"
    ATTACH = "attach"


def _forget(key: str, task: asyncio.Task[str]) -> None:
    """Drop a settled gate task from the running set, retrieving its outcome so none goes unobserved."""
    _RUNNING.pop(key, None)
    if not task.cancelled():
        task.exception()


def _is_live(flight: StampInFlight) -> bool:
    """Whether the flight's gates are known to be running.

    The work itself says so: a task or gate thread of this process, the recorded gate unit (a process in its
    group), the recorded runner process (same pid, same start time), or a process showing the invocation's
    token, which backs the recorded identities and never replaces them. A flight with no recorded identity
    cannot be proven settled, so it counts as live for the lifetime the runner enforces over the gates.
    """
    task = _RUNNING.get(flight.key)
    if (task is not None and not task.done()) or flight.key in _GATE_THREADS:
        return True
    if is_group_alive(flight.unit_pgid, flight.unit_started) or is_process_alive(
        flight.runner_pid, flight.runner_started
    ):
        return True
    if is_token_alive(flight.key):
        return True
    if flight.unit_pgid or flight.runner_pid:
        return False
    age = (datetime.now(UTC) - datetime.fromisoformat(flight.started_at)).total_seconds()
    return age < UNRECORDED_BOUND_SECONDS


def _take(request: ActRequest, session_id: str, key: str, outcome: list[Slot]) -> Callable[..., ItemChange | None]:
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
        if flight is not None and _is_live(flight):
            if flight.key == key:
                outcome.append(Slot.ATTACH)
                return None
            raise ActRefused(Refusal.STAMP_IN_FLIGHT.value.format(act=request.act.value))
        updated = record.model_copy(deep=True)
        updated.stamp_in_flight = StampInFlight(
            key=key, sha=request.sha, session_id=session_id, started_at=_now(), owner=PROCESS_INSTANCE
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


async def _record_identity(
    store: WorkflowStore, item: str, session_id: str, key: str, update: Mapping[str, int | float]
) -> None:
    """Record a process identity of the gate on the flight, so a later process can tell whether it still runs."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        flight = record.stamp_in_flight
        if flight is None or flight.key != key:
            return None
        updated = record.model_copy(deep=True)
        updated.stamp_in_flight = flight.model_copy(update=dict(update))
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=session_id)


async def _record_runner(store: WorkflowStore, item: str, session_id: str, key: str, pid: int, started: float) -> None:
    await _record_identity(store, item, session_id, key, {RUNNER_PID_FIELD: pid, RUNNER_STARTED_FIELD: started})


async def _record_unit(store: WorkflowStore, item: str, session_id: str, key: str, pgid: int, started: float) -> None:
    await _record_identity(store, item, session_id, key, {UNIT_PGID_FIELD: pgid, UNIT_STARTED_FIELD: started})


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _settle(
    store: WorkflowStore, request: ActRequest, session_id: str, key: str, commit: Callable[[], Awaitable[str]]
) -> str:
    """Check the references, run the gates, check again and commit, as one task that owns the slot until it settles.

    A gate that ends without recording the stamp releases the slot; a cancelled task leaves it for its
    expiry, because its gate thread may still be running.
    """
    try:
        await check_refs(request.project_root, request.item, request.sha)
        await run_gates(
            request.project_root,
            request.item,
            key,
            partial(_record_runner, store, request.item, session_id, key),
            partial(_record_unit, store, request.item, session_id, key),
        )
        await check_refs(request.project_root, request.item, request.sha)
        return await commit()
    except GateUnsettled:
        raise
    except Exception:
        await store.commit_item_change(request.item, expect_digests={}, mutate=_release(key), updated_by=session_id)
        raise


def _settle_overdue(flight: StampInFlight) -> None:
    """Kill the runner and the unit of a flight past the lifetime the gates are given, and wait until they are gone."""
    if flight.runner_pid:
        settle_group(flight.runner_pid, flight.runner_started)
    if flight.unit_pgid:
        settle_group(flight.unit_pgid, flight.unit_started)


async def _enforce_ceiling(store: WorkflowStore, item: str) -> None:
    """Enforce the lifetime the gates are given on a flight that no live task of this process runs.

    The runner enforces it in the ordinary case; this is the backstop for a runner that died with its unit
    still running. It only ends processes whose time is up, and the flight is replaced only once they are gone.
    """
    raw = await store.read_state(item)
    flight = workflow_record_of(raw).stamp_in_flight if raw is not None else None
    if flight is None:
        return
    task = _RUNNING.get(flight.key)
    if (task is not None and not task.done()) or flight.key in _GATE_THREADS:
        return
    if (datetime.now(UTC) - datetime.fromisoformat(flight.started_at)).total_seconds() >= GATE_CEILING_SECONDS:
        await asyncio.to_thread(_settle_overdue, flight)


async def _acquire(
    store: WorkflowStore, request: ActRequest, session_id: str, key: str, commit: Callable[[], Awaitable[str]]
) -> tuple[Slot, asyncio.Task[str] | None]:
    """Take the slot and, when owned, start the running task, with no other stamp of this item in between.

    The lock makes the durable acquisition and the in-process registration one step for every stamp of the
    item in this process, so no submission can find the slot owned here without finding it running.
    """
    lock = _SLOT_LOCKS.setdefault(f"{request.project_root}:{request.item}", asyncio.Lock())
    async with lock:
        await _enforce_ceiling(store, request.item)
        outcome: list[Slot] = []
        await store.commit_item_change(
            request.item,
            expect_digests={},
            mutate=_take(request, session_id, key, outcome),
            updated_by=session_id,
        )
        if outcome[-1] is not Slot.OWNED:
            return outcome[-1], None
        task = asyncio.ensure_future(_settle(store, request, session_id, key, commit))
        _RUNNING[key] = task
        task.add_done_callback(partial(_forget, key))
        return Slot.OWNED, task


async def run_stamp(
    store: WorkflowStore, request: ActRequest, session_id: str, key: str, commit: Callable[[], Awaitable[str]]
) -> str:
    """Perform a stamp so that at most one stamp's gates run on an item, and every repeat observes its result.

    The slot is item-wide and re-checks the phase and the holder where it is taken. The running work is a
    task independent of the request that started it: a request that ends does not release the slot or stop
    the gates, and a repeat of the same invocation attaches to the running one until it records. An
    invocation counts as running until its gate thread has ended, not only while its task is alive.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ATTACH_DEADLINE_SECONDS
    while True:
        slot, task = await _acquire(store, request, session_id, key, commit)
        if slot is Slot.RECORDED:
            return key
        if task is not None:
            return await asyncio.shield(task)
        if loop.time() >= deadline:
            raise ActRefused(Refusal.STAMP_IN_FLIGHT.value.format(act=request.act.value))
        await asyncio.sleep(ATTACH_POLL_SECONDS)
