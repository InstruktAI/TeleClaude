"""The stamp's pre-commit work: the reference checks and the build gates, each run once per invocation.

``local/projects/teleclaude/spec/feature/workflow/work-review-cycle`` is the contract. A stamp at commit
H is accepted only while H is the integration head, the item's worktree branch head and H agree, the
worktree is clean, the worktree carries file-changing commits beyond the shared branch, and the
project's native test target passes. The references are read again after the gates ran.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Final

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.gate_runner import GateOutcome
from teleclaude.core.next_machine.git_ops import (
    get_head_commit,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
)
from teleclaude.core.workflow_machine.act_types import ActRefused, ActRequest, Refusal
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


def _runner_identity(pid: int) -> float:
    """The start time of a process, which with its pid names it for as long as it lives."""
    try:
        created: float = psutil.Process(pid).create_time()
    except psutil.Error:
        return NO_START
    return created


def _is_runner_alive(pid: int, started: float) -> bool:
    """Whether the recorded process still lives: the same pid with the same start time, and not a zombie."""
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        created: float = process.create_time()
        status: str = process.status()
    except psutil.Error:
        return False
    return abs(created - started) < START_TOLERANCE and status != psutil.STATUS_ZOMBIE


def _is_token_alive(key: str) -> bool:
    """Whether any process carries the invocation's token in its environment: the runner or anything it started."""
    for process in psutil.process_iter():
        try:
            if process.environ().get(GATE_TOKEN_ENV) == key and process.status() != psutil.STATUS_ZOMBIE:
                return True
        except psutil.Error:
            continue
    return False


def _gate_thread(worktree: str, item: str, key: str, on_runner: Callable[[int, float], None]) -> GateOutcome:
    """Run the gates in a runner process of their own and wait for it, marking the thread until it really ends."""
    try:
        runner = subprocess.Popen(
            [sys.executable, "-m", GATE_RUNNER_MODULE, worktree, item],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            # guard: direct-env-read - allowed: child-process environment construction
            env={**os.environ, GATE_TOKEN_ENV: key},
        )
        on_runner(runner.pid, _runner_identity(runner.pid))
        stdout, stderr = runner.communicate()
        if runner.returncode != 0:
            return GateOutcome(
                passed=False, output=RUNNER_FAILED_TEMPLATE.format(code=runner.returncode, tail=stderr[-STDERR_TAIL:])
            )
        return GateOutcome.model_validate_json(stdout)
    finally:
        with _THREADS_LOCK:
            _GATE_THREADS.discard(key)


async def run_gates(
    project_root: str, item: str, key: str, record_runner: Callable[[int, float], Coroutine[None, None, None]]
) -> None:
    """Refuse unless the worktree carries build commits and the project's native test target passes.

    The gates run in a process that enforces its own time limit and outlives this one. The invocation stays
    marked as running until that process has ended, whatever happens to the task awaiting it.
    """
    worktree = str(worktree_path(project_root, item))
    if not await asyncio.to_thread(has_build_commits_beyond_main, worktree):
        raise ActRefused(StampRefusal.NO_BUILD_COMMITS.value)
    loop = asyncio.get_running_loop()

    def on_runner(pid: int, started: float) -> None:
        try:
            asyncio.run_coroutine_threadsafe(record_runner(pid, started), loop).result(RECORD_RUNNER_TIMEOUT_SECONDS)
        except Exception:  # the token scan still finds the runner; recording its pid must never fail the gate
            logger.warning(RECORD_RUNNER_FAILED_LOG, item=item, exc_info=True)

    with _THREADS_LOCK:
        _GATE_THREADS.add(key)
    outcome = await asyncio.to_thread(_gate_thread, worktree, item, key, on_runner)
    if not outcome.passed:
        raise ActRefused(StampRefusal.GATE_FAILED.value.format(output=outcome.output))


PROCESS_INSTANCE: Final = uuid.uuid4().hex
GATE_RUNNER_MODULE: Final = "teleclaude.core.next_machine.gate_runner"
GATE_TOKEN_ENV: Final = "TELECLAUDE_STAMP_GATE"
NO_START: Final = 0.0
START_TOLERANCE: Final = 0.5
RUNNER_LIFETIME_BOUND_SECONDS: Final = 900
STDERR_TAIL: Final = 500
RECORD_RUNNER_TIMEOUT_SECONDS: Final = 10
RECORD_RUNNER_FAILED_LOG: Final = "the gate runner's identity could not be recorded"
RUNNER_FAILED_TEMPLATE: Final = "the gate runner ended with exit {code}: {tail}"
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

    The work itself says so: a task or gate thread of this process, the recorded runner process (the same pid
    with the same start time), or any process still carrying the invocation's token (a scan that the host may
    restrict, so it backs the recorded identity and never replaces it). A flight whose runner identity was
    never recorded cannot be proven settled, so it counts as live for the lifetime the runner itself enforces,
    after which the runner has ended whatever became of the record.
    """
    task = _RUNNING.get(flight.key)
    if (task is not None and not task.done()) or flight.key in _GATE_THREADS:
        return True
    if _is_runner_alive(flight.runner_pid, flight.runner_started) or _is_token_alive(flight.key):
        return True
    if flight.runner_pid:
        return False
    age = (datetime.now(UTC) - datetime.fromisoformat(flight.started_at)).total_seconds()
    return age < RUNNER_LIFETIME_BOUND_SECONDS


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


async def _record_runner(store: WorkflowStore, item: str, session_id: str, key: str, pid: int, started: float) -> None:
    """Record the runner's identity on the flight, so a later process can tell whether the gates still run."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        if current is None:
            return None
        record = workflow_record_of(current)
        flight = record.stamp_in_flight
        if flight is None or flight.key != key:
            return None
        updated = record.model_copy(deep=True)
        updated.stamp_in_flight = flight.model_copy(update={"runner_pid": pid, "runner_started": started})
        return ItemChange(state={**current, WORKFLOW_STATE_KEY: updated.to_state()})

    await store.commit_item_change(item, expect_digests={}, mutate=mutate, updated_by=session_id)


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
            request.project_root, request.item, key, partial(_record_runner, store, request.item, session_id, key)
        )
        await check_refs(request.project_root, request.item, request.sha)
        return await commit()
    except Exception:
        await store.commit_item_change(request.item, expect_digests={}, mutate=_release(key), updated_by=session_id)
        raise


async def _acquire(
    store: WorkflowStore, request: ActRequest, session_id: str, key: str, commit: Callable[[], Awaitable[str]]
) -> tuple[Slot, asyncio.Task[str] | None]:
    """Take the slot and, when owned, start the running task, with no other stamp of this item in between.

    The lock makes the durable acquisition and the in-process registration one step for every stamp of the
    item in this process, so no submission can find the slot owned here without finding it running.
    """
    lock = _SLOT_LOCKS.setdefault(f"{request.project_root}:{request.item}", asyncio.Lock())
    async with lock:
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
