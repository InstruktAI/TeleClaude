"""Range-based deterministic maintenance at canonical-main boundaries."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import (
    ActivationRange,
    fill_activation_range,
    load_checkpoint_model,
    main_only_judgment_action_ids_for_files,
    main_only_maintenance_action_ids_for_files,
)
from teleclaude.config.errors import ConfigLoadError, describe_load_error
from teleclaude.config.secret_masking import declared_secret_values, mask_secret_values
from teleclaude.constants import LOG_CHECK_ACTION_ID, MaintenanceAction
from teleclaude.core.integration._maintenance_records import (
    MaintenanceActionRecord,
    MaintenanceRecordState,
    activation_has_records,
    maintenance_drain_lock,
    read_record,
    read_records,
    record_path,
    remove_record,
    write_record,
)
from teleclaude.core.integration.maintenance_trigger import MaintenanceTrigger
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo, hook_free_environment
from teleclaude.hooks.integrator_judgment_marker import (
    IntegratorJudgmentMarker,
    mark_integrator_judgment_ready,
    read_integrator_judgment_marker,
    record_integrator_judgment_activation,
)
from teleclaude.logging_config import setup_logging
from teleclaude.project_root import resolve_project_root
from teleclaude.runtime.command_runner import CommandResult, run_process_group_commands

logger = get_logger(__name__)

_GIT_NAME_ONLY_ARGUMENT = "--name-only"
_GIT_DIFF_TREE_ARGUMENTS = ("--root", "--no-commit-id", _GIT_NAME_ONLY_ARGUMENT, "-r")
_SYNC_ACTION_ID = "sync"
_FULL_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_MAIN_BRANCH_NAME = "main"
_GIT_HEAD_REFERENCE = "HEAD"
_GIT_ORIGINAL_HEAD_REFERENCE = "ORIG_HEAD"
_GIT_COUNT_FLAG = "--count"
_PUBLISHER_MODULE = "teleclaude.core.integration.post_commit_maintenance"
_MAINTENANCE_RECORDED_EVENT = "post_commit_maintenance_recorded"
_MAINTENANCE_CONTENDER_STARTED_EVENT = "post_commit_maintenance_contender_started"
_MAINTENANCE_CONTENDER_FAILED_EVENT = "post_commit_maintenance_contender_spawn_failed"
_MAINTENANCE_DRAIN_STARTED_EVENT = "post_commit_maintenance_drain_started"
_MAINTENANCE_DRAIN_FINISHED_EVENT = "post_commit_maintenance_drain_finished"
_MAINTENANCE_ACTION_STARTED_EVENT = "post_commit_maintenance_action_started"
_MAINTENANCE_ACTION_FINISHED_EVENT = "post_commit_maintenance_action_finished"
_OUTPUT_WITHHELD = "output withheld: the configuration that declares its secrets does not load ({reason})"
_MAINTENANCE_ACTION_INTERRUPTED_EVENT = "post_commit_maintenance_action_interrupted"
_MAINTENANCE_ACTION_RETRIED_EVENT = "post_commit_maintenance_action_retried"
_MAINTENANCE_RESOLVED_EVENT = "post_commit_maintenance_resolved"
_MAINTENANCE_SKIPPED_EVENT = "post_commit_maintenance_skipped"
_SKIP_GIT_UNAVAILABLE = "git_unavailable"
_SKIP_INELIGIBLE_LOCATION = "ineligible_location"
_UNKNOWN_ACTION_EXIT_CODE = 127
_SUCCESS_OUTCOME = "success"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, TypeError, ValueError)


@dataclass(frozen=True)
class MaintenanceStatus:
    """Read-only maintenance records and the integrator judgment marker."""

    records: tuple[MaintenanceActionRecord, ...]
    judgment_marker: IntegratorJudgmentMarker | None


def resolve_activation_range(project_root: Path, before_ref: str | None, after_ref: str) -> ActivationRange:
    """Resolve hook refs to immutable object ids before selecting any action."""
    repository = Repo(str(project_root.resolve()))
    before_sha = repository.commit(before_ref).hexsha if before_ref is not None else None
    after_sha = repository.commit(after_ref).hexsha
    return ActivationRange(before_sha=before_sha, after_sha=after_sha)


def resolve_post_commit_activation_range(project_root: Path) -> ActivationRange:
    """Resolve the new tip and its parent, preserving an absent root parent."""
    repository = Repo(str(project_root.resolve()))
    after_commit = repository.commit(_GIT_HEAD_REFERENCE)
    before_sha = after_commit.parents[0].hexsha if after_commit.parents else None
    return ActivationRange(before_sha=before_sha, after_sha=after_commit.hexsha)


def resolve_post_merge_activation_range(project_root: Path) -> ActivationRange:
    """Resolve the pre-merge and post-merge tips before any maintenance runs."""
    return resolve_activation_range(
        project_root,
        _GIT_ORIGINAL_HEAD_REFERENCE,
        _GIT_HEAD_REFERENCE,
    )


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
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            return None
        if not _is_literal_range(repository, activation_range):
            return None
        changed_files = _changed_files(repository, activation_range)
        action_ids = main_only_maintenance_action_ids_for_files(list(changed_files), root)
    except _GIT_FAILURES:
        return None
    return changed_files if action_id in action_ids else None


def record_activation(project_root: Path, activation_range: ActivationRange) -> bool:
    """Persist the actions owed by one canonical-main activation before returning."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        _log_skipped(activation_range, _SKIP_INELIGIBLE_LOCATION, root)
        return False
    try:
        repository = Repo(str(root))
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            _log_skipped(activation_range, _SKIP_INELIGIBLE_LOCATION, root)
            return False
        if not _is_literal_range(repository, activation_range):
            _log_skipped(activation_range, _SKIP_GIT_UNAVAILABLE, root)
            return False
        changed_files = _changed_files(repository, activation_range)
    except _GIT_FAILURES as exc:
        logger.warning(
            _MAINTENANCE_SKIPPED_EVENT,
            reason=_SKIP_GIT_UNAVAILABLE,
            before_sha=activation_range.before_sha,
            after_sha=activation_range.after_sha,
            error=str(exc),
        )
        return False

    action_ids = tuple(main_only_maintenance_action_ids_for_files(list(changed_files), root))
    logger.info(
        _MAINTENANCE_RESOLVED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
        changed_files=changed_files,
    )
    if not action_ids:
        return False

    queued_at = datetime.now(UTC).isoformat()
    for action_id in action_ids:
        path = record_path(root, activation_range.after_sha, action_id)
        if path.exists():
            continue
        record = MaintenanceActionRecord(
            before_sha=activation_range.before_sha,
            after_sha=activation_range.after_sha,
            action_id=action_id,
            queued_at=queued_at,
            state=MaintenanceRecordState.PENDING,
        )
        write_record(path, record)

    judgment_action_ids = main_only_judgment_action_ids_for_files(list(changed_files), root)
    if LOG_CHECK_ACTION_ID in judgment_action_ids:
        record_integrator_judgment_activation(
            root,
            activation_range,
            [LOG_CHECK_ACTION_ID],
            queued_at,
        )
    logger.info(
        _MAINTENANCE_RECORDED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
    )
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
    root = eligible_main_root(project_root)
    if root is None:
        return False
    with maintenance_drain_lock(root):
        _drain_locked(root)
    return not any(record.state is MaintenanceRecordState.FAILED for record in read_records(root))


def main() -> int:
    """Drain maintenance for the current canonical checkout."""
    setup_logging()
    return 0 if drain_maintenance(Path.cwd()) else 1


def retry_failed_action(project_root: Path, after_sha: str, action_id: str) -> bool:
    """Reset one terminal failure and drain it under the shared lock."""
    root = eligible_main_root(project_root)
    if root is None:
        return False
    with maintenance_drain_lock(root):
        path = record_path(root, after_sha, action_id)
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
            after_sha=after_sha,
            action_id=action_id,
        )
        _drain_locked(root)
    return not record_path(root, after_sha, action_id).exists()


def maintenance_status(project_root: Path) -> MaintenanceStatus:
    """Read records and judgment state for the owning canonical checkout."""
    root = resolve_project_state_root(project_root)
    return MaintenanceStatus(
        records=read_records(root),
        judgment_marker=read_integrator_judgment_marker(root),
    )


def eligible_main_root(project_root: Path) -> Path | None:
    """Require the canonical checkout's main branch; return its root, or ``None`` for any other location."""
    root = project_root.resolve()
    canonical_root = resolve_project_state_root(root)
    if root != canonical_root:
        logger.warning(_MAINTENANCE_SKIPPED_EVENT, reason=_SKIP_INELIGIBLE_LOCATION, project_root=str(root))
        return None
    try:
        repository = Repo(str(root))
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            logger.warning(_MAINTENANCE_SKIPPED_EVENT, reason=_SKIP_INELIGIBLE_LOCATION, project_root=str(root))
            return None
    except _GIT_FAILURES as exc:
        logger.warning(_MAINTENANCE_SKIPPED_EVENT, reason=_SKIP_GIT_UNAVAILABLE, error=str(exc))
        return None
    return root


def _drain_locked(project_root: Path) -> None:
    """Run eligible action records while the caller holds the drain lock."""
    root = project_root
    logger.info(_MAINTENANCE_DRAIN_STARTED_EVENT, project_root=str(root))
    repository = Repo(str(root))
    model = load_checkpoint_model(str(root))
    while True:
        records = read_records(root)
        actionable = tuple(
            record
            for record in records
            if record.state in (MaintenanceRecordState.PENDING, MaintenanceRecordState.RUNNING)
        )
        if not actionable:
            break
        activation = min(actionable, key=lambda record: _activation_order(repository, record))
        activation_records = tuple(record for record in actionable if record.after_sha == activation.after_sha)
        known_records = {
            record.action_id: record for record in activation_records if record.action_id in model.maintenance
        }
        for record in activation_records:
            if record.action_id not in known_records:
                _finish_unknown_action(root, record)
        _run_activation(root, _range_for(activation), known_records, model.maintenance)

    ready_at = datetime.now(UTC).isoformat()
    mark_integrator_judgment_ready(root, lambda after_sha: activation_has_records(root, after_sha), ready_at)
    remaining = read_records(root)
    logger.info(
        _MAINTENANCE_DRAIN_FINISHED_EVENT,
        project_root=str(root),
        failed_action_count=sum(record.state is MaintenanceRecordState.FAILED for record in remaining),
        pending_action_count=sum(record.state is MaintenanceRecordState.PENDING for record in remaining),
    )


def _run_activation(
    root: Path,
    activation_range: ActivationRange,
    known_records: Mapping[str, MaintenanceActionRecord],
    actions: Mapping[str, MaintenanceAction],
) -> None:
    """Run one activation's recorded actions, keeping each action's record current."""

    def start_record(action_id: str) -> None:
        path = record_path(root, activation_range.after_sha, action_id)
        current = read_record(path)
        if current.state is MaintenanceRecordState.RUNNING:
            logger.warning(
                _MAINTENANCE_ACTION_INTERRUPTED_EVENT,
                after_sha=current.after_sha,
                action_id=current.action_id,
            )
        write_record(path, replace(current, state=MaintenanceRecordState.RUNNING))

    def settle_record(action_id: str, result: CommandResult, finished_at: str) -> None:
        _settle_record(root, known_records[action_id], result, finished_at)

    def fill(command: tuple[str, ...]) -> tuple[str, ...]:
        return fill_activation_range(command, activation_range, interpreter=sys.executable)

    run_maintenance_waves(
        root,
        activation_range,
        MaintenanceTrigger.COMMIT_BOUNDARY,
        tuple(known_records),
        actions,
        fill,
        None,
        start_record,
        settle_record,
        capture_output=True,
    )


def run_maintenance_waves(
    root: Path,
    activation_range: ActivationRange,
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
                before_sha=activation_range.before_sha,
                after_sha=activation_range.after_sha,
                action_id=action_id,
                trigger=trigger,
            )
            commands.append(fill(actions[action_id].command))

        def report(index: int, result: CommandResult, wave_ids: tuple[str, ...] = wave) -> None:
            action_id = wave_ids[index]
            finished_at = datetime.now(UTC).isoformat()
            on_finished(action_id, result, finished_at)
            _log_action_finished(activation_range, trigger, action_id, result, finished_at)
            completed.append((action_id, result))

        run_process_group_commands(
            commands, root, child_env, report, capture_output=_secret_masker(root) if capture_output else None
        )
    return tuple(completed)


def _secret_masker(root: Path) -> Callable[[str], str]:
    """Mask the configuration's declared secrets in captured output; withhold it when they are unknown."""
    secrets: frozenset[str] | None = None
    unknown: str | None = None

    def mask(output: str) -> str:
        nonlocal secrets, unknown
        if secrets is None and unknown is None:
            try:
                secrets = declared_secret_values(root)
            except ConfigLoadError as error:
                unknown = describe_load_error(error)
            except FileNotFoundError as error:
                unknown = str(error)
        if secrets is None:
            return _OUTPUT_WITHHELD.format(reason=unknown)
        return mask_secret_values(output, secrets)

    return mask


def _activation_order(repository: Repo, record: MaintenanceActionRecord) -> tuple[int, str, str]:
    """Order activations by reachable ancestry depth, then queue time and id."""
    count = int(str(repository.git.rev_list(_GIT_COUNT_FLAG, record.after_sha)).strip())
    return (count, record.queued_at, record.after_sha)


def _range_for(record: MaintenanceActionRecord) -> ActivationRange:
    """Reconstruct the immutable range attached to one action record."""
    return ActivationRange(before_sha=record.before_sha, after_sha=record.after_sha)


def _settle_record(
    project_root: Path, record: MaintenanceActionRecord, result: CommandResult, finished_at: str
) -> None:
    """Remove success or retain a terminal failure with its structured outcome."""
    path = record_path(project_root, record.after_sha, record.action_id)
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
    activation_range: ActivationRange,
    trigger: MaintenanceTrigger,
    action_id: str,
    result: CommandResult,
    finished_at: str,
) -> None:
    """Record one action's terminal outcome for the run that performed it; a failure carries its output."""
    if result.exit_code == 0:
        logger.info(
            _MAINTENANCE_ACTION_FINISHED_EVENT,
            before_sha=activation_range.before_sha,
            after_sha=activation_range.after_sha,
            action_id=action_id,
            exit_code=result.exit_code,
            outcome=_SUCCESS_OUTCOME,
            finished_at=finished_at,
            trigger=trigger,
        )
        return
    logger.error(
        _MAINTENANCE_ACTION_FINISHED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
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
    _log_action_finished(_range_for(record), MaintenanceTrigger.COMMIT_BOUNDARY, record.action_id, result, finished_at)


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
    """Require full object ids and keep the activated tip on canonical main."""
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


def _log_skipped(activation_range: ActivationRange, reason: str, root: Path) -> None:
    """Record a range that was not eligible to enqueue maintenance."""
    logger.info(
        _MAINTENANCE_SKIPPED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        reason=reason,
        project_root=str(root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
