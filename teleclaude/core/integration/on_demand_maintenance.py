"""On-demand maintenance: ``telec sync`` performs a root's maintenance steps now, as the manual fallback.

The steps are every maintenance action the root's committed declaration (platform base merged
with the project overlay) declares, except an action only an event binding names, which has no
event to act on here. They run through the commit-boundary executor under its lock, one by one
with each outcome reported as it completes.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import (
    ActivationRange,
    event_only_action_ids,
    fill_on_demand,
    load_committed_checkpoint_model,
)
from teleclaude.constants import MaintenanceAction, OnDemandDisposition
from teleclaude.core.dirty_path_owners import DirtyPathOwner, resolve_dirty_path_owners
from teleclaude.core.integration._maintenance_records import (
    EventActivation,
    MaintenanceActionRecord,
    MaintenanceRecordState,
    maintenance_drain_lock,
    read_records,
)
from teleclaude.core.integration.maintenance_trigger import (
    DRAIN_HELD_ENV,
    DRAIN_HELD_VALUE,
    ON_DEMAND_TRIGGER_ENV,
    MaintenanceTrigger,
)
from teleclaude.core.integration.post_commit_maintenance import (
    eligible_maintenance_root,
    replay_command,
    run_maintenance_waves,
)
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo, hook_free_environment
from teleclaude.paths import ConfigFileName
from teleclaude.project_root import resolve_git_root
from teleclaude.quality.scope import resolve_dirty_paths
from teleclaude.runtime.command_runner import CommandResult

logger = get_logger(__name__)

__all__ = [
    "ListedStep",
    "OnDemandListing",
    "OnDemandRunResult",
    "StepOutcome",
    "list_on_demand",
    "run_on_demand",
]

_RUN_STARTED_EVENT = "on_demand_maintenance_run_started"
_RUN_FINISHED_EVENT = "on_demand_maintenance_run_finished"
_DIRTY_OWNERS_UNRESOLVED_EVENT = "on_demand_maintenance_dirty_owners_unresolved"
_PROBE_TIMEOUT_SECONDS = 120
_SUCCEEDED = 0
_FAILED = 1
_HOME_REQUIRED = "telec sync runs only from a directory holding its own teleclaude.yml: {directory}"
_NO_PROJECT = "telec sync found no project that owns {directory}: {error}"
_LOCATION_REFUSED = "telec sync runs only from the canonical checkout on its main branch. Run it from: {directory}"
_NO_CANONICAL_CHECKOUT = "no checkout owns this directory"
_WAITING_FOR_LOCK = "Commit-boundary maintenance is still running; waiting for it to finish before running any step."
_DIRTY_HEADING = (
    "Uncommitted changes in this checkout. Publication reads committed state only; "
    "the other steps read the checkout as it stands:"
)
_DIRTY_PATH_LINE = "  {path}"
_DIRTY_PATH_OWNED_LINE = "  {path} (held by {owners})"
_DIRTY_OWNER = "{title} [{session_uuid}]"
_DIRTY_OWNER_SEPARATOR = ", "
_STEP_RUNNING = "{action_id}: running"
_STEP_SUCCEEDED = "{action_id}: succeeded"
_STEP_FAILED = "{action_id}: failed (exit code {exit_code})"
_EARLIER_FAILURE = (
    "{action_id} failed in an earlier commit-boundary run ({after_sha}). Replay it for its original range with: "
    "{command}. The standing integrator owns that replay."
)
_EARLIER_EVENT_FAILURE = (
    "{action_id} failed in an earlier run for the {event_type} event {event_id}. Replay it for that event with: "
    "{command}. The standing integrator owns that replay."
)
_OWED = "{action_id} is owed: {reason}"
_OWED_RUN = "  Run: {command}"
_UNDETERMINED = "Cannot tell whether {action_id} is owed: {detail}"
_UNDETERMINED_RUN = "  If it is owed, run: {command}"
_NO_PROBE = "the action declares no probe"
_PROBE_FAILED = "its probe exited with code {exit_code}"
_PROBE_UNREACHABLE = "its probe could not run: {error}"
_LISTED_PERFORMED = "{action_id}: perform"
_LISTED_REPORTED = "{action_id}: report only (never performed on demand)"
_SHORT_COMMIT_LENGTH = 12


@dataclass(frozen=True)
class StepOutcome:
    """One performed step and the exit code it ended with."""

    action_id: str
    exit_code: int


@dataclass(frozen=True)
class OnDemandRunResult:
    """The outcome of one on-demand run, or the refusal that stopped it."""

    refusal: str | None = None
    steps: tuple[StepOutcome, ...] = ()

    @property
    def exit_code(self) -> int:
        """Non-zero exactly when the run was refused or any step failed."""
        if self.refusal is not None or any(step.exit_code != _SUCCEEDED for step in self.steps):
            return _FAILED
        return _SUCCEEDED


@dataclass(frozen=True)
class ListedStep:
    """One declared step and whether a run performs it or only reports whether it is owed."""

    action_id: str
    performed: bool


@dataclass(frozen=True)
class OnDemandListing:
    """The steps a run would perform in a root, or the refusal that stops a run there."""

    refusal: str | None = None
    steps: tuple[ListedStep, ...] = ()

    @property
    def exit_code(self) -> int:
        """Non-zero exactly when the listing refused."""
        return _FAILED if self.refusal is not None else _SUCCEEDED


@dataclass(frozen=True)
class _Target:
    """A root eligible for an on-demand run, the invocation home within it, and the tip a run converges to."""

    root: Path
    home: Path
    tip: str
    maintenance: dict[str, MaintenanceAction]


@dataclass(frozen=True)
class _RunContext:
    """Inputs and callbacks used while the on-demand maintenance lock is held."""

    root: Path
    target: _Target
    activation: ActivationRange
    performed: tuple[str, ...]
    deferred: tuple[str, ...]
    child_env: dict[str, str]
    outcomes: list[StepOutcome]
    emit: Callable[[str], None]
    start_step: Callable[[str], None]
    finish_step: Callable[[str, CommandResult, str], None]
    fill: Callable[[tuple[str, ...]], tuple[str, ...]]


@dataclass(frozen=True)
class _ProbeAnswer:
    """What a deferred action's probe said: the reasons it is owed, and why it could not tell."""

    reasons: tuple[str, ...]
    undetermined: str | None


class _Refused(Exception):
    """The invocation is not a location an on-demand run may act from."""


def run_on_demand(invocation_directory: Path, emit: Callable[[str], None]) -> OnDemandRunResult:
    """Perform the invocation root's maintenance steps, reporting through ``emit`` in report order."""
    try:
        target = _resolve_target(invocation_directory)
    except _Refused as resolution_refusal:
        return OnDemandRunResult(refusal=str(resolution_refusal))

    root = target.root
    activation = ActivationRange(before_sha=None, after_sha=target.tip)
    performed = _ordered(target.maintenance, OnDemandDisposition.RUN)
    deferred = _ordered(target.maintenance, OnDemandDisposition.DEFER)
    dirty_count = _report_uncommitted_edits(root, emit)
    logger.info(
        _RUN_STARTED_EVENT,
        project_root=str(root),
        tip=target.tip,
        step_count=len(performed),
        deferred_count=len(deferred),
        dirty_path_count=dirty_count,
    )
    interpreter = sys.executable
    child_env = {
        **hook_free_environment(root),
        ON_DEMAND_TRIGGER_ENV: MaintenanceTrigger.ON_DEMAND.value,
        DRAIN_HELD_ENV: DRAIN_HELD_VALUE,
    }
    outcomes: list[StepOutcome] = []

    def start_step(action_id: str) -> None:
        emit(_STEP_RUNNING.format(action_id=action_id))

    def finish_step(action_id: str, result: CommandResult, _: str) -> None:
        outcomes.append(StepOutcome(action_id=action_id, exit_code=result.exit_code))
        if result.exit_code == _SUCCEEDED:
            emit(_STEP_SUCCEEDED.format(action_id=action_id))
        else:
            emit(_STEP_FAILED.format(action_id=action_id, exit_code=result.exit_code))

    def fill(command: tuple[str, ...]) -> tuple[str, ...]:
        return fill_on_demand(command, target.tip, target.home.as_posix(), interpreter=interpreter)

    context = _RunContext(
        root=root,
        target=target,
        activation=activation,
        performed=performed,
        deferred=deferred,
        child_env=child_env,
        outcomes=outcomes,
        emit=emit,
        start_step=start_step,
        finish_step=finish_step,
        fill=fill,
    )
    with maintenance_drain_lock(root, lambda: emit(_WAITING_FOR_LOCK)):
        _perform_on_demand_steps(context)

    result = OnDemandRunResult(steps=tuple(outcomes))
    logger.info(
        _RUN_FINISHED_EVENT,
        project_root=str(root),
        tip=target.tip,
        step_count=len(outcomes),
        failed_step_count=sum(step.exit_code != _SUCCEEDED for step in outcomes),
        exit_code=result.exit_code,
    )
    return result


def _perform_on_demand_steps(context: _RunContext) -> None:
    """Run the declared steps in order under the lock, then name earlier failures and what is still owed."""
    root = context.root
    run_maintenance_waves(
        root,
        context.activation,
        MaintenanceTrigger.ON_DEMAND,
        context.performed,
        context.target.maintenance,
        context.fill,
        context.child_env,
        context.start_step,
        context.finish_step,
        capture_output=False,
    )
    _report_earlier_failures(root, context.emit)
    _report_owed(root, context.target, context.deferred, context.fill, context.child_env, context.emit)


def list_on_demand(invocation_directory: Path, emit: Callable[[str], None]) -> OnDemandListing:
    """Name every declared step in order, and what a run does with it. Takes no lock and changes nothing."""
    try:
        target = _resolve_target(invocation_directory)
    except _Refused as refusal:
        return OnDemandListing(refusal=str(refusal))
    steps = tuple(
        ListedStep(
            action_id=action_id,
            performed=target.maintenance[action_id].on_demand is OnDemandDisposition.RUN,
        )
        for action_id in _ordered(target.maintenance, None)
    )
    for step in steps:
        emit((_LISTED_PERFORMED if step.performed else _LISTED_REPORTED).format(action_id=step.action_id))
    return OnDemandListing(steps=steps)


def _resolve_target(invocation_directory: Path) -> _Target:
    """Resolve the eligible root, the invocation home, the converged tip and the committed step set."""
    directory = invocation_directory.expanduser().resolve()
    if not (directory / ConfigFileName.OVERLAY).is_file():
        raise _Refused(_HOME_REQUIRED.format(directory=directory))
    try:
        repository_root = resolve_git_root(directory)
        home = directory.relative_to(repository_root)
        root = eligible_maintenance_root(repository_root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise _Refused(_NO_PROJECT.format(directory=directory, error=exc)) from exc
    if root is None:
        raise _Refused(_LOCATION_REFUSED.format(directory=_canonical_directory(repository_root, home)))
    try:
        tip = Repo(str(root)).head.commit.hexsha
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError) as exc:
        raise _Refused(_NO_PROJECT.format(directory=directory, error=exc)) from exc
    model = load_committed_checkpoint_model(root, tip)
    event_only = event_only_action_ids(model)
    return _Target(
        root=root,
        home=home,
        tip=tip,
        maintenance={
            action_id: action for action_id, action in model.maintenance.items() if action_id not in event_only
        },
    )


def _canonical_directory(repository_root: Path, home: Path) -> Path | str:
    """The directory to run from instead: the invocation's place in the canonical checkout."""
    try:
        canonical = resolve_owning_checkout(repository_root)
    except (FileNotFoundError, OSError):
        canonical = None
    return canonical / home if canonical is not None else _NO_CANONICAL_CHECKOUT


def _ordered(maintenance: dict[str, MaintenanceAction], disposition: OnDemandDisposition | None) -> tuple[str, ...]:
    """Action ids in declared order: precedence, then id; every action, or only those with ``disposition``."""
    return tuple(
        action_id
        for action_id, action in sorted(maintenance.items(), key=lambda item: (item[1].precedence, item[0]))
        if disposition is None or action.on_demand is disposition
    )


def _report_uncommitted_edits(root: Path, emit: Callable[[str], None]) -> int:
    """Name the checkout's uncommitted paths, and the sessions holding them where that can be told."""
    dirty_paths = tuple(sorted(dirty.path for dirty in resolve_dirty_paths(root)))
    if not dirty_paths:
        return 0
    try:
        owners = dict(asyncio.run(resolve_dirty_path_owners(root)).owners)
    except Exception:
        logger.warning(_DIRTY_OWNERS_UNRESOLVED_EVENT, project_root=str(root), exc_info=True)
        owners = {}
    emit(_DIRTY_HEADING)
    for path in dirty_paths:
        emit(_dirty_line(path, owners.get(path, ())))
    return len(dirty_paths)


def _dirty_line(path: str, owners: tuple[DirtyPathOwner, ...]) -> str:
    """One uncommitted path, with its holders when any live session declared it."""
    if not owners:
        return _DIRTY_PATH_LINE.format(path=path)
    held_by = _DIRTY_OWNER_SEPARATOR.join(
        _DIRTY_OWNER.format(title=owner.title, session_uuid=owner.session_uuid) for owner in owners
    )
    return _DIRTY_PATH_OWNED_LINE.format(path=path, owners=held_by)


def _report_earlier_failures(root: Path, emit: Callable[[str], None]) -> None:
    """Name each action an earlier commit-boundary run recorded as failed, with its replay. Records are only read."""
    failed: tuple[MaintenanceActionRecord, ...] = tuple(
        record for record in read_records(root) if record.state is MaintenanceRecordState.FAILED
    )
    for record in failed:
        activation = record.activation
        command = replay_command(activation, record.action_id)
        if isinstance(activation, EventActivation):
            emit(
                _EARLIER_EVENT_FAILURE.format(
                    action_id=record.action_id,
                    event_type=activation.event_type,
                    event_id=activation.event_id,
                    command=command,
                )
            )
        else:
            emit(
                _EARLIER_FAILURE.format(
                    action_id=record.action_id,
                    after_sha=activation.after_sha[:_SHORT_COMMIT_LENGTH],
                    command=command,
                )
            )


def _report_owed(
    root: Path,
    target: _Target,
    deferred: tuple[str, ...],
    fill: Callable[[tuple[str, ...]], tuple[str, ...]],
    child_env: dict[str, str],
    emit: Callable[[str], None],
) -> None:
    """Ask each deferred action's probe whether it is owed, and say so; a probe with nothing to report adds nothing."""
    for action_id in deferred:
        action = target.maintenance[action_id]
        command = shlex.join(fill(action.command))
        answer = _ask_probe(root, action, fill, child_env)
        for reason in answer.reasons:
            emit(_OWED.format(action_id=action_id, reason=reason))
        if answer.reasons:
            emit(_OWED_RUN.format(command=command))
        if answer.undetermined is not None:
            emit(_UNDETERMINED.format(action_id=action_id, detail=answer.undetermined))
            emit(_UNDETERMINED_RUN.format(command=command))


def _ask_probe(
    root: Path,
    action: MaintenanceAction,
    fill: Callable[[tuple[str, ...]], tuple[str, ...]],
    child_env: dict[str, str],
) -> _ProbeAnswer:
    """Run the action's owed probe: each line it prints is a reason, and a non-zero exit is a cannot-tell."""
    if action.owed_probe is None:
        return _ProbeAnswer(reasons=(), undetermined=_NO_PROBE)
    try:
        # The probe is the declared argument vector of the root's own registry; capturing its lines needs a process.
        completed = subprocess.run(
            list(fill(action.owed_probe)),
            cwd=str(root),
            env=child_env,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _ProbeAnswer(reasons=(), undetermined=_PROBE_UNREACHABLE.format(error=exc))
    reasons = tuple(line for line in completed.stdout.splitlines() if line.strip())
    if completed.returncode == _SUCCEEDED:
        return _ProbeAnswer(reasons=reasons, undetermined=None)
    detail = completed.stderr.strip() or _PROBE_FAILED.format(exit_code=completed.returncode)
    return _ProbeAnswer(reasons=reasons, undetermined=detail)
