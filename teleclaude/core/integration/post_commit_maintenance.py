"""Deterministic maintenance owed by canonical-main commit ranges and by platform events about a project."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import (
    ActivationRange,
    fill_activation_range,
    fill_event_activation,
    load_checkpoint_model,
    main_only_maintenance_action_ids_for_model,
)
from teleclaude.config.errors import ConfigLoadError, describe_load_error
from teleclaude.constants import (
    CheckpointActivation,
    CheckpointModel,
    MaintenanceAction,
)
from teleclaude.core.integration._maintenance_records import (
    ActivationRegistration,
    EventActivation,
    MaintenanceActionRecord,
    MaintenanceActivation,
    MaintenanceRecordState,
    PendingSettlement,
    SettlementOutcome,
    activation_has_records,
    activation_key,
    commit_activation_key,
    event_file_path,
    maintenance_activation_registration_lock,
    maintenance_drain_is_running,
    maintenance_drain_lock,
    read_activation_registration,
    read_record,
    read_records,
    record_path,
    remove_record,
    write_activation_registration,
    write_event_file,
    write_record,
)
from teleclaude.core.integration.activation_registration import write_owed_records
from teleclaude.core.integration.maintenance_output import secret_output_masker
from teleclaude.core.integration.maintenance_settlement import (
    SettlementWatch,
    deliver_pending_settlements,
    record_settlement,
)
from teleclaude.core.integration.maintenance_trigger import DRAIN_HELD_ENV, DRAIN_HELD_VALUE, MaintenanceTrigger
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo, hook_free_environment
from teleclaude.hooks.integrator_judgment_marker import (
    IntegratorJudgmentMarker,
    mark_integrator_judgment_ready,
    read_integrator_judgment_marker,
)
from teleclaude.logging_config import setup_logging
from teleclaude.project_root import resolve_project_root
from teleclaude.runtime.command_runner import CommandResult, run_process_group_commands

logger = get_logger(__name__)

_GIT_NAME_ONLY_ARGUMENT = "--name-only"
_GIT_DIFF_TREE_ARGUMENTS = ("--root", "--no-commit-id", _GIT_NAME_ONLY_ARGUMENT, "-r")
_FULL_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_MAIN_BRANCH_NAME = "main"
_CANONICAL_MAIN_REFERENCE = "refs/heads/main"
_GIT_COUNT_FLAG = "--count"
_PUBLISHER_MODULE = "teleclaude.core.integration.post_commit_maintenance"
_MAINTENANCE_RECORDED_EVENT = "post_commit_maintenance_recorded"
_MAINTENANCE_CONTENDER_STARTED_EVENT = "post_commit_maintenance_contender_started"
_MAINTENANCE_CONTENDER_FAILED_EVENT = "post_commit_maintenance_contender_spawn_failed"
_MAINTENANCE_DRAIN_STARTED_EVENT = "post_commit_maintenance_drain_started"
_MAINTENANCE_DRAIN_FINISHED_EVENT = "post_commit_maintenance_drain_finished"
_MAINTENANCE_ACTION_STARTED_EVENT = "post_commit_maintenance_action_started"
_MAINTENANCE_ACTION_FINISHED_EVENT = "post_commit_maintenance_action_finished"
_MAINTENANCE_ACTION_INTERRUPTED_EVENT = "post_commit_maintenance_action_interrupted"
_MAINTENANCE_ACTION_RETRIED_EVENT = "post_commit_maintenance_action_retried"
_MAINTENANCE_RESOLVED_EVENT = "post_commit_maintenance_resolved"
_MAINTENANCE_SKIPPED_EVENT = "post_commit_maintenance_skipped"
_INELIGIBLE_LOCATION_DETAIL = "{root} is neither the canonical checkout on main nor the installed release checkout"
_INVALID_RANGE_DETAIL = "the activation range is not a literal range of the checked-out source"
_REFUSAL_NOTICE = "Maintenance for this activation was not recorded ({reason}): {detail}. Run {command} to perform it."
_UNKNOWN_ACTION_EXIT_CODE = 127
_SUCCESS_OUTCOME = "success"
_REPLAY_COMMIT_COMMAND = "telec repo maintenance retry --after-sha {after_sha} --action {action_id}"
_REPLAY_EVENT_COMMAND = "telec repo maintenance retry --event-id {event_id} --action {action_id}"
ON_DEMAND_MAINTENANCE_COMMAND = "telec sync"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, TypeError, ValueError)


@dataclass(frozen=True)
class MaintenanceStatus:
    """Read-only maintenance records and the integrator judgment marker."""

    records: tuple[MaintenanceActionRecord, ...]
    judgment_marker: IntegratorJudgmentMarker | None


class MaintenanceObservationState(StrEnum):
    """Read-only observation of one action's outstanding maintenance state."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    ABSENT = "absent"


@dataclass(frozen=True)
class MaintenanceActionObservation:
    """Published action state and its sanctioned recovery reference, when one applies."""

    state: MaintenanceObservationState
    recovery_reference: str | None = None


class ActivationRefusal(StrEnum):
    """Why an activation's owed set could not be recorded."""

    INELIGIBLE_LOCATION = "ineligible_location"
    INVALID_RANGE = "invalid_range"
    GIT_UNAVAILABLE = "git_unavailable"
    CONFIGURATION_UNRESOLVED = "configuration_unresolved"
    RECORD_FAILED = "record_failed"


@dataclass(frozen=True)
class OwedSetRecorded:
    """The activation's owed actions are durably recorded, by this call or an earlier one."""

    action_ids: tuple[str, ...]


@dataclass(frozen=True)
class OwedSetEmpty:
    """The activation owes no maintenance action."""


@dataclass(frozen=True)
class ActivationRefused:
    """The activation's owed set could not be determined or recorded; nothing is claimed about it."""

    reason: ActivationRefusal
    detail: str


ActivationRecording = OwedSetRecorded | OwedSetEmpty | ActivationRefused


def refusal_notice(recording: ActivationRecording) -> str | None:
    """The terminal notice a refused activation owes its committer; an ordinary ineligible location owes none."""
    if not isinstance(recording, ActivationRefused) or recording.reason is ActivationRefusal.INELIGIBLE_LOCATION:
        return None
    return _REFUSAL_NOTICE.format(
        reason=recording.reason, detail=recording.detail, command=ON_DEMAND_MAINTENANCE_COMMAND
    )


def selected_maintenance_revision(project_root: Path) -> str:
    """Resolve the committed source maintenance answers to, from the owning checkout including worktree callers.

    Maintenance answers to the committed main tip of the project's own checkout; no installed release
    is a maintenance root.
    """
    root = resolve_project_state_root(project_root)
    return Repo(str(root)).commit(_CANONICAL_MAIN_REFERENCE).hexsha


def maintenance_model(project_root: Path) -> CheckpointModel:
    """The declaration a root's maintenance answers to: the checkout's working-tree declaration."""
    return load_checkpoint_model(str(project_root.resolve()))


def _holds_eligible_posture(repository: Repo) -> bool:
    """Whether the checkout may carry canonical-main maintenance: main itself, never a detached checkout."""
    return not repository.head.is_detached and repository.active_branch.name == _MAIN_BRANCH_NAME


def activation_range_action_paths(
    project_root: Path,
    activation_range: ActivationRange,
    action_id: str,
) -> tuple[str, ...] | None:
    """Return one eligible action's changed paths after validating its literal range."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return None
    try:
        repository = Repo(str(root))
        if not _holds_eligible_posture(repository):
            return None
        if not _is_literal_range(repository, activation_range):
            return None
        changed_files = _changed_files(repository, activation_range)
        action_ids = main_only_maintenance_action_ids_for_model(
            list(changed_files), CheckpointActivation.CANONICAL_MAIN, maintenance_model(root)
        )
    except _GIT_FAILURES:
        return None
    return changed_files if action_id in action_ids else None


def record_activation(project_root: Path, activation_range: ActivationRange) -> ActivationRecording:
    """Persist the actions owed by one canonical-main activation before returning.

    The outcome distinguishes a recorded owed set (including one an earlier call recorded), an
    explicitly empty owed set, and a refusal with its reason. A storage failure leaves the records
    already written in place so a replay fills the remaining set.
    """
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return _refuse(
            activation_range,
            root,
            ActivationRefusal.INELIGIBLE_LOCATION,
            _INELIGIBLE_LOCATION_DETAIL.format(root=root),
        )
    try:
        repository = Repo(str(root))
        if not _holds_eligible_posture(repository):
            return _refuse(
                activation_range,
                root,
                ActivationRefusal.INELIGIBLE_LOCATION,
                _INELIGIBLE_LOCATION_DETAIL.format(root=root),
            )
        if not _is_literal_range(repository, activation_range):
            return _refuse(activation_range, root, ActivationRefusal.INVALID_RANGE, _INVALID_RANGE_DETAIL)
        changed_files = _changed_files(repository, activation_range)
    except ConfigLoadError as exc:
        return _refuse(activation_range, root, ActivationRefusal.CONFIGURATION_UNRESOLVED, describe_load_error(exc))
    except _GIT_FAILURES as exc:
        return _refuse(activation_range, root, ActivationRefusal.GIT_UNAVAILABLE, str(exc))

    try:
        model = maintenance_model(root)
        action_ids = tuple(
            main_only_maintenance_action_ids_for_model(list(changed_files), CheckpointActivation.CANONICAL_MAIN, model)
        )
    except ConfigLoadError as exc:
        return _refuse(activation_range, root, ActivationRefusal.CONFIGURATION_UNRESOLVED, describe_load_error(exc))
    except _GIT_FAILURES as exc:
        return _refuse(activation_range, root, ActivationRefusal.CONFIGURATION_UNRESOLVED, str(exc))
    logger.info(
        _MAINTENANCE_RESOLVED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
        changed_files=changed_files,
    )
    try:
        with maintenance_activation_registration_lock(root):
            registration = read_activation_registration(root, activation_range.after_sha)
            if registration is not None:
                return _registration_outcome(registration)
            if action_ids:
                write_owed_records(root, activation_range, action_ids, changed_files)
            else:
                record_settlement(root, PendingSettlement(activation_range, SettlementOutcome.SUCCEEDED, ()))
            write_activation_registration(root, activation_range.after_sha, action_ids)
    except (OSError, ValueError) as exc:
        return _refuse(activation_range, root, ActivationRefusal.RECORD_FAILED, str(exc))
    if not action_ids:
        return OwedSetEmpty()
    logger.info(
        _MAINTENANCE_RECORDED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
    )
    return OwedSetRecorded(action_ids)


def _registration_outcome(registration: ActivationRegistration) -> ActivationRecording:
    """Return an advancement's existing outcome without re-writing any records."""
    if registration.action_ids:
        return OwedSetRecorded(registration.action_ids)
    return OwedSetEmpty()


def record_event_activation(project_root: Path, event: ReceivedEvent, action_ids: tuple[str, ...]) -> bool:
    """Persist the actions one platform event owes this checkout, and the event they answer, before returning.

    Returns whether the event's activation is recorded in this checkout, now or by an earlier call;
    an activation whose records already exist is not recorded again. A location that is not the
    canonical checkout on main records nothing and returns ``False``.
    """
    root = eligible_maintenance_root(project_root)
    if root is None:
        return False
    activation = EventActivation(event_id=event.id, event_type=event.type)
    key = activation_key(activation)
    with maintenance_activation_registration_lock(root):
        owed = tuple(action_id for action_id in action_ids if not record_path(root, key, action_id).exists())
        if not owed:
            return True
        write_event_file(root, event)
        queued_at = datetime.now(UTC).isoformat()
        for action_id in owed:
            record = MaintenanceActionRecord(
                activation=activation,
                action_id=action_id,
                queued_at=queued_at,
                state=MaintenanceRecordState.PENDING,
            )
            write_record(record_path(root, key, action_id), record)
    logger.info(_MAINTENANCE_RECORDED_EVENT, event_id=event.id, event_type=event.type, action_ids=owed)
    return True


def start_drain_contender(project_root: Path) -> bool:
    """Start one detached drain contender without making Git wait for its work."""
    root = project_root.resolve()
    command = [sys.executable, "-m", _PUBLISHER_MODULE]
    try:
        # A detached child is required because this work outlives the Git hook process.
        subprocess.Popen(
            command,
            cwd=str(root),
            env=hook_free_environment(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.warning(
            _MAINTENANCE_CONTENDER_FAILED_EVENT,
            project_root=str(root),
            error=str(exc),
        )
        return False
    logger.info(_MAINTENANCE_CONTENDER_STARTED_EVENT, project_root=str(root))
    return True


def drain_maintenance(project_root: Path) -> bool:
    """Drain every pending activation while holding the single checkout lock."""
    root = eligible_maintenance_root(project_root)
    if root is None:
        return False
    with maintenance_drain_lock(root):
        processed = _drain_locked(root)
    deliver_pending_settlements(root)
    return processed and not any(record.state is MaintenanceRecordState.FAILED for record in read_records(root))


def main() -> int:
    """Drain maintenance for the current canonical checkout."""
    setup_logging()
    return 0 if drain_maintenance(Path.cwd()) else 1


def retry_failed_action(project_root: Path, key: str, action_id: str) -> bool:
    """Reset one terminal failure of the activation named by ``key`` and drain it under the shared lock."""
    root = eligible_maintenance_root(project_root)
    if root is None:
        return False
    with maintenance_drain_lock(root):
        path = record_path(root, key, action_id)
        if not path.exists():
            return False
        record = read_record(path)
        if record.state is not MaintenanceRecordState.FAILED:
            return False
        write_record(
            path,
            replace(record, state=MaintenanceRecordState.PENDING, exit_code=None, finished_at=None, output_tail=None),
        )
        logger.info(
            _MAINTENANCE_ACTION_RETRIED_EVENT,
            **_activation_log_fields(record.activation),
            action_id=action_id,
        )
        _drain_locked(root)
    deliver_pending_settlements(root)
    return not record_path(root, key, action_id).exists()


def replay_command(activation: MaintenanceActivation, action_id: str) -> str:
    """The command that replays one failed action of an activation with the identity it first ran for."""
    if isinstance(activation, EventActivation):
        return _REPLAY_EVENT_COMMAND.format(event_id=activation.event_id, action_id=action_id)
    return _REPLAY_COMMIT_COMMAND.format(after_sha=activation.after_sha, action_id=action_id)


def maintenance_status(project_root: Path) -> MaintenanceStatus:
    """Read records and judgment state for the owning canonical checkout."""
    root = resolve_project_state_root(project_root)
    return MaintenanceStatus(
        records=read_records(root),
        judgment_marker=read_integrator_judgment_marker(root),
    )


def observe_maintenance_action(project_root: Path, action_id: str) -> MaintenanceActionObservation:
    """Observe one canonical-main action without acquiring or advancing its drain."""
    root = resolve_project_state_root(project_root)
    records = tuple(
        record
        for record in maintenance_status(root).records
        if record.action_id == action_id and isinstance(record.activation, ActivationRange)
    )
    active_records = tuple(
        record for record in records if record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
    )
    if any(record.state is MaintenanceRecordState.RUNNING for record in active_records):
        return MaintenanceActionObservation(MaintenanceObservationState.RUNNING)
    if active_records:
        return MaintenanceActionObservation(MaintenanceObservationState.PENDING)
    if maintenance_drain_is_running(root):
        return MaintenanceActionObservation(MaintenanceObservationState.RUNNING)
    failures = tuple(record for record in records if record.state is MaintenanceRecordState.FAILED)
    if failures:
        latest_failure = max(failures, key=lambda record: record.queued_at)
        return MaintenanceActionObservation(
            MaintenanceObservationState.FAILED,
            replay_command(latest_failure.activation, latest_failure.action_id),
        )
    return MaintenanceActionObservation(MaintenanceObservationState.ABSENT, ON_DEMAND_MAINTENANCE_COMMAND)


def eligible_maintenance_root(project_root: Path) -> Path | None:
    """Require the canonical checkout on main; return its root, or ``None``."""
    root = project_root.resolve()
    canonical_root = resolve_project_state_root(root)
    if root != canonical_root:
        logger.warning(_MAINTENANCE_SKIPPED_EVENT, reason=ActivationRefusal.INELIGIBLE_LOCATION, project_root=str(root))
        return None
    try:
        repository = Repo(str(root))
        if not _holds_eligible_posture(repository):
            logger.warning(
                _MAINTENANCE_SKIPPED_EVENT, reason=ActivationRefusal.INELIGIBLE_LOCATION, project_root=str(root)
            )
            return None
    except _GIT_FAILURES as exc:
        logger.warning(_MAINTENANCE_SKIPPED_EVENT, reason=ActivationRefusal.GIT_UNAVAILABLE, error=str(exc))
        return None
    return root


def _drain_locked(project_root: Path) -> bool:
    """Run every eligible action record under the drain lock, one activation at a time."""
    root = project_root
    logger.info(_MAINTENANCE_DRAIN_STARTED_EVENT, project_root=str(root))
    repository = Repo(str(root))
    settlements = SettlementWatch(replay_command)

    while True:
        with maintenance_activation_registration_lock(root):
            records = read_records(root)
            settlements.record_settled(root, records)
            actionable = tuple(
                record
                for record in records
                if record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
            )
            model = maintenance_model(root)
            if not actionable:
                # No actionable records remain; later registrations belong to another drain.
                break
            activation = _next_activation(repository, actionable)
            activation_records = tuple(record for record in actionable if record.activation == activation)
            known_records = {
                record.action_id: record for record in activation_records if record.action_id in model.maintenance
            }
            for record in activation_records:
                if record.action_id not in known_records:
                    _finish_unknown_action(root, record)
        if known_records:
            _run_activation(root, activation, known_records, model.maintenance)

    ready_at = datetime.now(UTC).isoformat()
    mark_integrator_judgment_ready(
        root, lambda after_sha: activation_has_records(root, commit_activation_key(after_sha)), ready_at
    )
    remaining = read_records(root)
    logger.info(
        _MAINTENANCE_DRAIN_FINISHED_EVENT,
        project_root=str(root),
        failed_action_count=sum(record.state is MaintenanceRecordState.FAILED for record in remaining),
        pending_action_count=sum(record.state is MaintenanceRecordState.PENDING for record in remaining),
    )
    return True


def _run_activation(
    root: Path,
    activation: MaintenanceActivation,
    known_records: Mapping[str, MaintenanceActionRecord],
    actions: Mapping[str, MaintenanceAction],
) -> None:
    """Run one activation's recorded actions, keeping each action's record current."""
    key = activation_key(activation)

    def start_record(action_id: str) -> None:
        path = record_path(root, key, action_id)
        current = read_record(path)
        if current.state is MaintenanceRecordState.RUNNING:
            logger.warning(
                _MAINTENANCE_ACTION_INTERRUPTED_EVENT,
                **_activation_log_fields(current.activation),
                action_id=current.action_id,
            )
        write_record(path, replace(current, state=MaintenanceRecordState.RUNNING))

    def settle_record(action_id: str, result: CommandResult, finished_at: str) -> None:
        _settle_record(root, known_records[action_id], result, finished_at)

    def fill(command: tuple[str, ...]) -> tuple[str, ...]:
        return _fill_for_activation(root, activation, command)

    run_maintenance_waves(
        root,
        activation,
        _trigger_for(activation),
        tuple(known_records),
        actions,
        fill,
        {**hook_free_environment(root), DRAIN_HELD_ENV: DRAIN_HELD_VALUE},
        start_record,
        settle_record,
        capture_output=True,
    )


def run_maintenance_waves(
    root: Path,
    activation: MaintenanceActivation,
    trigger: MaintenanceTrigger,
    action_ids: tuple[str, ...],
    actions: Mapping[str, MaintenanceAction],
    fill: Callable[[tuple[str, ...]], tuple[str, ...]],
    child_env: Mapping[str, str] | None,
    on_started: Callable[[str], None],
    on_finished: Callable[[str, CommandResult, str], None],
    *,
    capture_output: bool,
) -> tuple[tuple[str, CommandResult], ...]:
    """Run the actions in precedence waves and return each action's result in completion order.

    Equal-precedence actions run concurrently, the next wave waits for every prior
    terminal outcome, and a failure never cancels a later wave. Every start and finish
    is logged with the ``trigger`` that caused it; ``on_started`` and ``on_finished``
    let the caller keep whatever record it owns for the run.
    """
    completed: list[tuple[str, CommandResult]] = []
    for wave in _precedence_waves(action_ids, actions):
        commands: list[tuple[str, ...]] = []
        for action_id in wave:
            on_started(action_id)
            logger.info(
                _MAINTENANCE_ACTION_STARTED_EVENT,
                **_activation_log_fields(activation),
                action_id=action_id,
                trigger=trigger,
            )
            commands.append(fill(actions[action_id].command))

        def report(index: int, result: CommandResult, wave_ids: tuple[str, ...] = wave) -> None:
            action_id = wave_ids[index]
            finished_at = datetime.now(UTC).isoformat()
            on_finished(action_id, result, finished_at)
            _log_action_finished(activation, trigger, action_id, result, finished_at)
            completed.append((action_id, result))

        run_process_group_commands(
            commands, root, child_env, report, capture_output=secret_output_masker(root) if capture_output else None
        )
    return tuple(completed)


def _next_activation(
    repository: Repo,
    actionable: tuple[MaintenanceActionRecord, ...],
) -> MaintenanceActivation:
    """Pick the activation to run next from the records still owed.

    Commit activations keep their ancestry order among themselves and event activations are
    taken in the order they were recorded.
    """
    commit_queue = [
        (record.activation, record.queued_at) for record in actionable if isinstance(record.activation, ActivationRange)
    ]
    event_queue = [
        (record.activation, record.queued_at) for record in actionable if isinstance(record.activation, EventActivation)
    ]
    candidates: list[tuple[MaintenanceActivation, str]] = []
    if commit_queue:
        candidates.append(min(commit_queue, key=lambda queued: _commit_activation_order(repository, *queued)))
    if event_queue:
        candidates.append(min(event_queue, key=lambda queued: (_queued_time(queued[1]), queued[0].event_id)))
    return min(candidates, key=lambda queued: _queued_time(queued[1]))[0]


def _commit_activation_order(repository: Repo, activation: ActivationRange, queued_at: str) -> tuple[int, str, str]:
    """Order commit activations by reachable ancestry depth, then queue time and id."""
    count = int(str(repository.git.rev_list(_GIT_COUNT_FLAG, activation.after_sha)).strip())
    return (count, queued_at, activation.after_sha)


def _queued_time(queued_at: str) -> datetime:
    """The instant an activation was queued, from its recorded timestamp."""
    return datetime.fromisoformat(queued_at)


def _trigger_for(activation: MaintenanceActivation) -> MaintenanceTrigger:
    """What started the run that performs an activation's actions."""
    if isinstance(activation, EventActivation):
        return MaintenanceTrigger.EVENT
    return MaintenanceTrigger.COMMIT_BOUNDARY


def _activation_log_fields(activation: MaintenanceActivation) -> dict[str, str | None]:
    """The structured-record fields that identify an activation: its range, or the event it answers."""
    return asdict(activation)


def _fill_for_activation(root: Path, activation: MaintenanceActivation, command: tuple[str, ...]) -> tuple[str, ...]:
    """Fill a declared command with the identity of the activation it runs for."""
    if isinstance(activation, EventActivation):
        return fill_event_activation(
            command,
            event_file=str(event_file_path(root, activation.event_id)),
            event_type=activation.event_type,
            event_id=activation.event_id,
            interpreter=sys.executable,
        )
    return fill_activation_range(command, activation, interpreter=sys.executable)


def _settle_record(
    project_root: Path, record: MaintenanceActionRecord, result: CommandResult, finished_at: str
) -> None:
    """Remove success or retain a terminal failure with its structured outcome."""
    path = record_path(project_root, activation_key(record.activation), record.action_id)
    if result.exit_code == 0:
        remove_record(path)
    else:
        write_record(
            path,
            replace(
                record,
                state=MaintenanceRecordState.FAILED,
                exit_code=result.exit_code,
                finished_at=finished_at,
                output_tail=result.output_tail,
            ),
        )


def _log_action_finished(
    activation: MaintenanceActivation,
    trigger: MaintenanceTrigger,
    action_id: str,
    result: CommandResult,
    finished_at: str,
) -> None:
    """Record one action's terminal outcome for the run that performed it; a failure carries its output."""
    if result.exit_code == 0:
        logger.info(
            _MAINTENANCE_ACTION_FINISHED_EVENT,
            **_activation_log_fields(activation),
            action_id=action_id,
            exit_code=result.exit_code,
            outcome=_SUCCESS_OUTCOME,
            finished_at=finished_at,
            trigger=trigger,
        )
        return
    logger.error(
        _MAINTENANCE_ACTION_FINISHED_EVENT,
        **_activation_log_fields(activation),
        action_id=action_id,
        exit_code=result.exit_code,
        outcome=MaintenanceRecordState.FAILED,
        finished_at=finished_at,
        trigger=trigger,
        output_tail=result.output_tail,
    )


def _finish_unknown_action(project_root: Path, record: MaintenanceActionRecord) -> None:
    """Keep an unresolvable persisted action visible as a terminal failure."""
    result = CommandResult(_UNKNOWN_ACTION_EXIT_CODE)
    finished_at = datetime.now(UTC).isoformat()
    _settle_record(project_root, record, result, finished_at)
    _log_action_finished(record.activation, _trigger_for(record.activation), record.action_id, result, finished_at)


def _precedence_waves(
    action_ids: tuple[str, ...], actions: Mapping[str, MaintenanceAction]
) -> tuple[tuple[str, ...], ...]:
    """Group stable action ids by their declared precedence."""
    grouped: dict[int, list[str]] = {}
    for action_id in action_ids:
        precedence = actions[action_id].precedence
        grouped.setdefault(precedence, []).append(action_id)
    return tuple(tuple(sorted(grouped[precedence])) for precedence in sorted(grouped))


def _is_literal_range(repository: Repo, activation_range: ActivationRange) -> bool:
    """Require full object ids and keep the activated tip on the checked-out source."""
    for revision in (activation_range.before_sha, activation_range.after_sha):
        if revision is None:
            continue
        if _FULL_COMMIT_ID_PATTERN.fullmatch(revision) is None or repository.commit(revision).hexsha != revision:
            return False
    after_commit = repository.commit(activation_range.after_sha)
    if after_commit.hexsha != activation_range.after_sha:
        return False
    if activation_range.before_sha is None:
        if after_commit.parents:
            return False
    else:
        before_commit = repository.commit(activation_range.before_sha)
        if before_commit.hexsha != activation_range.before_sha or not repository.is_ancestor(
            before_commit, after_commit
        ):
            return False
    return repository.is_ancestor(after_commit, repository.head.commit)


def _changed_files(repository: Repo, activation_range: ActivationRange) -> tuple[str, ...]:
    """Read changed paths from the immutable range, including a root commit tree."""
    if activation_range.before_sha is None:
        paths = repository.git.diff_tree(*_GIT_DIFF_TREE_ARGUMENTS, activation_range.after_sha)
    else:
        paths = repository.git.diff(_GIT_NAME_ONLY_ARGUMENT, activation_range.before_sha, activation_range.after_sha)
    return tuple(paths.splitlines())


def _refuse(activation_range: ActivationRange, root: Path, reason: ActivationRefusal, detail: str) -> ActivationRefused:
    """Record a refused activation in the structured log and return it; only an ineligible location is routine."""
    log = logger.info if reason is ActivationRefusal.INELIGIBLE_LOCATION else logger.warning
    log(
        _MAINTENANCE_SKIPPED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        reason=reason,
        detail=detail,
        project_root=str(root),
    )
    return ActivationRefused(reason, detail)


if __name__ == "__main__":
    raise SystemExit(main())
