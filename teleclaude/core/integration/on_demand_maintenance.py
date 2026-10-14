"""On-demand maintenance: ``telec sync`` performs a root's maintenance steps now, as the manual fallback.

The steps are every maintenance action the root's committed declaration (platform base merged
with the project overlay) declares, except an action only an event binding names, which has no
event to act on here. They run through the commit-boundary executor under its lock, one by one
with each outcome reported as it completes. A root that declares daemon replacement runs every
selected step inside the same stopped-daemon window as commit-boundary maintenance.
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
from teleclaude.constants import RESTART_MAINTENANCE_ACTION_ID, MaintenanceAction, OnDemandDisposition
from teleclaude.core.dirty_path_owners import DirtyPathOwner, resolve_dirty_path_owners
from teleclaude.core.integration._maintenance_records import (
    EventActivation,
    MaintenanceActionRecord,
    MaintenanceRecordState,
    maintenance_activation_registration_lock,
    maintenance_drain_lock,
    read_activation_registration,
    read_records,
)
from teleclaude.core.integration.activation_registration import resolve_current_tip_activation_range
from teleclaude.core.integration.daemon_window import WindowCloseResult, WindowOpenResult, close_window, open_window
from teleclaude.core.integration.maintenance_trigger import (
    DRAIN_HELD_ENV,
    DRAIN_HELD_VALUE,
    ON_DEMAND_TRIGGER_ENV,
    MaintenanceTrigger,
)
from teleclaude.core.integration.post_commit_maintenance import (
    ActivationRefused,
    eligible_maintenance_root,
    record_activation,
    replay_command,
    run_maintenance_waves,
    start_drain_contender,
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
_LISTED_WINDOWED = "{action_id}: replace the daemon around the run"
_LISTED_REPORTED = "{action_id}: report only (never performed on demand)"
_WINDOW_OPENING = "daemon window: opening"
_WINDOW_OPENED = "daemon window: opened"
_WINDOW_REFUSED = "daemon window: refused ({reason})"
_WINDOW_CLOSING_VERIFIED = "daemon window: closed and verified"
_WINDOW_CLOSING_FAILED = "daemon window: start not verified ({reason})"
_WINDOW_HANDOFF = "daemon window: handing activation {after_sha} to the commit-boundary drain"
_WINDOW_DRAIN_LAUNCH_FAILED = "could not start the commit-boundary drain; recover with: telec code maintenance drain"
_WINDOW_HANDOFF_FAILED = "{handoff}; {launch_failure}"
_WINDOW_TIP_REGISTRATION_REFUSED = "daemon window: refused to register checkout tip ({reason})"
_WINDOW_REOPEN_FAILED = "daemon window: could not stop the daemon for activation {after_sha} ({reason})"
_UNKNOWN_WINDOW_REFUSAL = "maintenance window opening was refused"
_UNKNOWN_WINDOW_CLOSE = "maintenance window start was not verified"
_SHORT_COMMIT_LENGTH = 12


@dataclass(frozen=True)
class StepOutcome:
    """One performed step and the exit code it ended with."""

    action_id: str
    exit_code: int


@dataclass(frozen=True)
class OnDemandRunResult:
    """The outcome of one on-demand run, including a refused or unverified daemon window."""

    refusal: str | None = None
    steps: tuple[StepOutcome, ...] = ()
    window_failure: str | None = None

    @property
    def exit_code(self) -> int:
        """Non-zero exactly when the window refused or failed verification, or any step failed."""
        if (
            self.refusal is not None
            or self.window_failure is not None
            or any(step.exit_code != _SUCCEEDED for step in self.steps)
        ):
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
class _ProbeAnswer:
    """What a deferred action's probe said: the reasons it is owed, and why it could not tell."""

    reasons: tuple[str, ...]
    undetermined: str | None


@dataclass(frozen=True)
class _WindowTipState:
    """New actionable commit work found at the on-demand window boundary."""

    activation: ActivationRange | None = None
    action_ids: tuple[str, ...] = ()
    refusal: str | None = None

    @property
    def restart_owed(self) -> bool:
        """Whether this newly actionable activation requires the daemon replacement window."""
        return RESTART_MAINTENANCE_ACTION_ID in self.action_ids


@dataclass(frozen=True)
class _OnDemandWindowClose:
    """The start result and any commit-boundary work found around it."""

    tip_state: _WindowTipState
    close_result: WindowCloseResult | None = None
    reopened: WindowOpenResult | None = None


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
    window_required = RESTART_MAINTENANCE_ACTION_ID in target.maintenance
    performed = tuple(
        action_id
        for action_id in _ordered(target.maintenance, OnDemandDisposition.RUN)
        if action_id != RESTART_MAINTENANCE_ACTION_ID
    )
    deferred = tuple(
        action_id
        for action_id in _ordered(target.maintenance, OnDemandDisposition.DEFER)
        if action_id != RESTART_MAINTENANCE_ACTION_ID
    )
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
    refusal: str | None = None
    window_failure: str | None = None

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

    with maintenance_drain_lock(root, lambda: emit(_WAITING_FOR_LOCK)):
        window_open = False
        with maintenance_activation_registration_lock(root):
            baseline_activation_shas = frozenset(
                record.activation.after_sha
                for record in read_records(root)
                if isinstance(record.activation, ActivationRange)
            )
        if window_required:
            emit(_WINDOW_OPENING)
            opened = open_window(root, activation)
            if not opened.opened:
                refusal = opened.reason or _UNKNOWN_WINDOW_REFUSAL
                emit(_WINDOW_REFUSED.format(reason=refusal))
            else:
                window_open = True
                emit(_WINDOW_OPENED)
        if refusal is None:
            run_maintenance_waves(
                root,
                activation,
                MaintenanceTrigger.ON_DEMAND,
                performed,
                target.maintenance,
                fill,
                child_env,
                start_step,
                finish_step,
                capture_output=False,
            )
            if window_open:
                boundary = _close_on_demand_window(root, target.tip, baseline_activation_shas, activation)
                tip_state = boundary.tip_state
                if boundary.close_result is not None and boundary.close_result.verified:
                    emit(_WINDOW_CLOSING_VERIFIED)
                elif boundary.close_result is not None:
                    window_failure = boundary.close_result.reason or _UNKNOWN_WINDOW_CLOSE
                    emit(_WINDOW_CLOSING_FAILED.format(reason=window_failure))
                if tip_state.refusal is not None:
                    refusal = tip_state.refusal
                    emit(_WINDOW_TIP_REGISTRATION_REFUSED.format(reason=refusal))
                    if boundary.reopened is not None:
                        if boundary.reopened.opened:
                            start_drain_contender(root)
                        else:
                            window_failure = boundary.reopened.reason or _UNKNOWN_WINDOW_REFUSAL
                            start_drain_contender(root)
                elif tip_state.restart_owed:
                    if boundary.reopened is not None and not boundary.reopened.opened:
                        reason = boundary.reopened.reason or _UNKNOWN_WINDOW_REFUSAL
                        window_failure = reason
                        refusal = _WINDOW_REOPEN_FAILED.format(
                            after_sha=tip_state.activation.after_sha if tip_state.activation else target.tip,
                            reason=reason,
                        )
                        start_drain_contender(root)
                    else:
                        refusal = _handoff_to_commit_boundary(root, tip_state, emit)
                if tip_state.action_ids and not tip_state.restart_owed:
                    start_drain_contender(root)
        if refusal is None:
            _report_earlier_failures(root, emit)
            _report_owed(root, target, deferred, fill, child_env, emit)

    result = OnDemandRunResult(refusal=refusal, steps=tuple(outcomes), window_failure=window_failure)
    logger.info(
        _RUN_FINISHED_EVENT,
        project_root=str(root),
        tip=target.tip,
        step_count=len(outcomes),
        failed_step_count=sum(step.exit_code != _SUCCEEDED for step in outcomes),
        exit_code=result.exit_code,
    )
    return result


def _find_new_window_tip_state(root: Path, baseline_activation_shas: frozenset[str]) -> _WindowTipState:
    """Return the first newly actionable commit activation and its resolved action set."""
    records = read_records(root)
    activation = next(
        (
            record.activation
            for record in records
            if isinstance(record.activation, ActivationRange)
            and record.activation.after_sha not in baseline_activation_shas
            and record.action_id == RESTART_MAINTENANCE_ACTION_ID
            and record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
        ),
        None,
    )
    if activation is None:
        activation = next(
            (
                record.activation
                for record in records
                if isinstance(record.activation, ActivationRange)
                and record.activation.after_sha not in baseline_activation_shas
                and record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
            ),
            None,
        )
    if activation is None:
        return _WindowTipState()
    action_ids = tuple(
        record.action_id
        for record in records
        if record.activation == activation
        and record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
    )
    return _WindowTipState(activation=activation, action_ids=action_ids)


def _close_on_demand_window(
    root: Path,
    run_tip: str,
    baseline_activation_shas: frozenset[str],
    activation: ActivationRange,
) -> _OnDemandWindowClose:
    """Check registration on both sides of the start while excluding commit-boundary writers."""
    close_result: WindowCloseResult | None = None
    started = False
    while True:
        unregistered_tip: str | None = None
        reopen_activation: ActivationRange | None = None
        tip_state: _WindowTipState | None = None
        with maintenance_activation_registration_lock(root):
            current_tip = Repo(str(root)).head.commit.hexsha
            if current_tip != run_tip and read_activation_registration(root, current_tip) is None:
                unregistered_tip = current_tip
            else:
                tip_state = _find_new_window_tip_state(root, baseline_activation_shas)
                if tip_state.restart_owed and not started:
                    return _OnDemandWindowClose(tip_state=tip_state)
                if started:
                    if tip_state.restart_owed and tip_state.activation is not None:
                        reopen_activation = tip_state.activation
                    else:
                        return _OnDemandWindowClose(tip_state, close_result)
                else:
                    close_result = close_window(
                        root,
                        current_tip,
                        (activation,),
                        current_tip=lambda: Repo(str(root)).head.commit.hexsha,
                    )
                    started = True
                    continue

        if reopen_activation is not None:
            if tip_state is None:
                continue
            reopened = open_window(root, reopen_activation)
            return _OnDemandWindowClose(tip_state, close_result, reopened)

        activation_range = resolve_current_tip_activation_range(root, unregistered_tip)
        recording = record_activation(root, activation_range)
        if isinstance(recording, ActivationRefused):
            tip_state = _WindowTipState(activation=activation_range, refusal=recording.detail)
            if started:
                reopened = open_window(root, activation_range)
                return _OnDemandWindowClose(tip_state, close_result, reopened)
            return _OnDemandWindowClose(tip_state)


def _handoff_to_commit_boundary(root: Path, tip_state: _WindowTipState, emit: Callable[[str], None]) -> str:
    """Leave a restart-owing activation for the drain and start its contender before releasing the lock."""
    activation = tip_state.activation
    if activation is None:
        return _UNKNOWN_WINDOW_REFUSAL
    handoff = _WINDOW_HANDOFF.format(after_sha=activation.after_sha[:_SHORT_COMMIT_LENGTH])
    emit(handoff)
    if start_drain_contender(root):
        return handoff
    failure = _WINDOW_DRAIN_LAUNCH_FAILED
    emit(failure)
    return _WINDOW_HANDOFF_FAILED.format(handoff=handoff, launch_failure=failure)


def list_on_demand(invocation_directory: Path, emit: Callable[[str], None]) -> OnDemandListing:
    """Name every declared step in order, and what a run does with it. Takes no lock and changes nothing."""
    try:
        target = _resolve_target(invocation_directory)
    except _Refused as refusal:
        return OnDemandListing(refusal=str(refusal))
    steps = tuple(
        ListedStep(
            action_id=action_id,
            performed=(
                target.maintenance[action_id].on_demand is OnDemandDisposition.RUN
                or action_id == RESTART_MAINTENANCE_ACTION_ID
            ),
        )
        for action_id in _ordered(target.maintenance, None)
    )
    for step in steps:
        if step.action_id == RESTART_MAINTENANCE_ACTION_ID:
            emit(_LISTED_WINDOWED.format(action_id=step.action_id))
        else:
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
