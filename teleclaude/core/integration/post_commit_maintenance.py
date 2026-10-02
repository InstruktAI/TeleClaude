"""Range-based deterministic maintenance at canonical-main boundaries."""

from __future__ import annotations

import re
import subprocess
import sys
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
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo, hook_free_environment
from teleclaude.hooks.integrator_judgment_marker import (
    IntegratorJudgmentMarker,
    mark_integrator_judgment_ready,
    read_integrator_judgment_marker,
    record_integrator_judgment_activation,
)
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


def activation_range_owes_action(
    project_root: Path,
    activation_range: ActivationRange,
    action_id: str,
    *,
    changed_paths: tuple[str, ...] | None = None,
) -> bool:
    """Check that one literal range is on canonical main and owes the named action."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return False
    try:
        repository = Repo(str(root))
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            return False
        if not _is_literal_range(repository, activation_range):
            return False
        changed_files = changed_paths if changed_paths is not None else _changed_files(repository, activation_range)
        action_ids = main_only_maintenance_action_ids_for_files(list(changed_files), root)
    except _GIT_FAILURES:
        return False
    return action_id in action_ids


def activation_range_changed_paths(project_root: Path, activation_range: ActivationRange) -> tuple[str, ...] | None:
    """Return changed paths for one literal canonical-main activation range."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return None
    try:
        repository = Repo(str(root))
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            return None
        if not _is_literal_range(repository, activation_range):
            return None
        return _changed_files(repository, activation_range)
    except _GIT_FAILURES:
        return None


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
    root = _eligible_main_root(project_root)
    if root is None:
        return False
    with maintenance_drain_lock(root):
        _drain_locked(root)
    return not any(record.state is MaintenanceRecordState.FAILED for record in read_records(root))


def main() -> int:
    """Drain maintenance for the current canonical checkout."""
    return 0 if drain_maintenance(Path.cwd()) else 1


def retry_failed_action(project_root: Path, after_sha: str, action_id: str) -> bool:
    """Reset one terminal failure and drain it under the shared lock."""
    root = _eligible_main_root(project_root)
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
            replace(record, state=MaintenanceRecordState.PENDING, exit_code=None, finished_at=None),
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


def _eligible_main_root(project_root: Path) -> Path | None:
    """Require invocation from the canonical checkout's main branch."""
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
        known_records = tuple(record for record in activation_records if record.action_id in model.maintenance)
        unknown_records = tuple(record for record in activation_records if record not in known_records)
        for record in unknown_records:
            _finish_unknown_action(root, record)
        action_ids = tuple(record.action_id for record in known_records)
        for wave in _precedence_waves(action_ids, model.maintenance):
            wave_records = tuple(record for record in known_records if record.action_id in wave)
            commands: list[tuple[str, ...]] = []
            for record in wave_records:
                path = record_path(root, record.after_sha, record.action_id)
                current = read_record(path)
                if current.state is MaintenanceRecordState.RUNNING:
                    logger.warning(
                        _MAINTENANCE_ACTION_INTERRUPTED_EVENT,
                        after_sha=current.after_sha,
                        action_id=current.action_id,
                    )
                write_record(path, replace(current, state=MaintenanceRecordState.RUNNING))
                logger.info(
                    _MAINTENANCE_ACTION_STARTED_EVENT,
                    before_sha=record.before_sha,
                    after_sha=record.after_sha,
                    action_id=record.action_id,
                )
                command = fill_activation_range(
                    model.maintenance[record.action_id].command,
                    _range_for(record),
                    interpreter=sys.executable,
                )
                commands.append(command)
            results = run_process_group_commands(commands, root)
            for record, result in zip(wave_records, results, strict=True):
                _finish_action(root, record, result)

    ready_at = datetime.now(UTC).isoformat()
    mark_integrator_judgment_ready(root, lambda after_sha: activation_has_records(root, after_sha), ready_at)
    remaining = read_records(root)
    logger.info(
        _MAINTENANCE_DRAIN_FINISHED_EVENT,
        project_root=str(root),
        failed_action_count=sum(record.state is MaintenanceRecordState.FAILED for record in remaining),
        pending_action_count=sum(record.state is MaintenanceRecordState.PENDING for record in remaining),
    )


def _activation_order(repository: Repo, record: MaintenanceActionRecord) -> tuple[int, str, str]:
    """Order activations by reachable ancestry depth, then queue time and id."""
    count = int(str(repository.git.rev_list(_GIT_COUNT_FLAG, record.after_sha)).strip())
    return (count, record.queued_at, record.after_sha)


def _range_for(record: MaintenanceActionRecord) -> ActivationRange:
    """Reconstruct the immutable range attached to one action record."""
    return ActivationRange(before_sha=record.before_sha, after_sha=record.after_sha)


def _finish_action(project_root: Path, record: MaintenanceActionRecord, result: CommandResult) -> None:
    """Remove success or retain a terminal failure with its structured outcome."""
    path = record_path(project_root, record.after_sha, record.action_id)
    finished_at = datetime.now(UTC).isoformat()
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
            ),
        )
    logger.info(
        _MAINTENANCE_ACTION_FINISHED_EVENT,
        before_sha=record.before_sha,
        after_sha=record.after_sha,
        action_id=record.action_id,
        exit_code=result.exit_code,
        outcome=MaintenanceRecordState.FAILED if result.exit_code else _SUCCESS_OUTCOME,
        finished_at=finished_at,
    )


def _finish_unknown_action(project_root: Path, record: MaintenanceActionRecord) -> None:
    """Keep an unresolvable persisted action visible as a terminal failure."""
    _finish_action(project_root, record, CommandResult(_UNKNOWN_ACTION_EXIT_CODE))


def _precedence_waves(
    action_ids: tuple[str, ...], actions: dict[str, MaintenanceAction]
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
