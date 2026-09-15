"""Range-based deterministic maintenance at canonical-main boundaries."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import load_checkpoint_model, main_only_action_ids_for_files
from teleclaude.constants import CheckpointAction
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_root import resolve_project_root
from teleclaude.runtime.command_runner import CommandResult, run_process_group_command

logger = get_logger(__name__)

_GIT_NAME_ONLY_ARGUMENT = "--name-only"
_COMMAND_FAILURE_EXIT_CODE = 127
_MAINTENANCE_ACTION_FINISHED_EVENT = "post_commit_maintenance_action_finished"
_MAINTENANCE_ACTION_STARTED_EVENT = "post_commit_maintenance_action_started"
_MAINTENANCE_RESOLVED_EVENT = "post_commit_maintenance_resolved"
_MAINTENANCE_SKIPPED_EVENT = "post_commit_maintenance_skipped"
_SKIP_GIT_UNAVAILABLE = "git_unavailable"
_SKIP_INELIGIBLE_LOCATION = "ineligible_location"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, ValueError)


@dataclass(frozen=True)
class MaintenanceActionOutcome:
    """One terminal maintenance outcome."""

    action_id: str
    result: CommandResult


@dataclass(frozen=True)
class PostCommitMaintenanceOutcome:
    """The ordered result of one canonical-main range."""

    commit_range: str
    action_ids: tuple[str, ...]
    action_outcomes: tuple[MaintenanceActionOutcome, ...]
    skip_reason: str | None


def run_post_commit_maintenance(project_root: Path, commit_range: str) -> PostCommitMaintenanceOutcome:
    """Execute executable main-only actions owed by one canonical-main range."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return _skipped_outcome(commit_range, _SKIP_INELIGIBLE_LOCATION, root)
    try:
        changed_files = tuple(Repo(str(root)).git.diff(_GIT_NAME_ONLY_ARGUMENT, commit_range).splitlines())
    except _GIT_FAILURES as exc:
        logger.warning(
            _MAINTENANCE_SKIPPED_EVENT, reason=_SKIP_GIT_UNAVAILABLE, commit_range=commit_range, error=str(exc)
        )
        return PostCommitMaintenanceOutcome(commit_range, (), (), _SKIP_GIT_UNAVAILABLE)

    model = load_checkpoint_model(str(root))
    action_ids = tuple(
        action_id
        for action_id in main_only_action_ids_for_files(list(changed_files), root)
        if model.actions[action_id].command
    )
    logger.info(
        _MAINTENANCE_RESOLVED_EVENT, commit_range=commit_range, action_ids=action_ids, changed_files=changed_files
    )
    outcomes: list[MaintenanceActionOutcome] = []
    for wave in _precedence_waves(action_ids, model.actions):
        for action_id in wave:
            logger.info(_MAINTENANCE_ACTION_STARTED_EVENT, commit_range=commit_range, action_id=action_id)
        with ThreadPoolExecutor(max_workers=len(wave)) as executor:
            futures = {
                action_id: executor.submit(_run_action, model.actions[action_id].command, root) for action_id in wave
            }
            for action_id in wave:
                result = futures[action_id].result()
                logger.info(
                    _MAINTENANCE_ACTION_FINISHED_EVENT,
                    commit_range=commit_range,
                    action_id=action_id,
                    exit_code=result.exit_code,
                )
                outcomes.append(MaintenanceActionOutcome(action_id, result))
    return PostCommitMaintenanceOutcome(commit_range, action_ids, tuple(outcomes), None)


def _precedence_waves(action_ids: tuple[str, ...], actions: dict[str, CheckpointAction]) -> tuple[tuple[str, ...], ...]:
    """Group stable action ids by their declared precedence."""
    grouped: dict[int, list[str]] = {}
    for action_id in action_ids:
        precedence = actions[action_id].precedence
        grouped.setdefault(precedence, []).append(action_id)
    return tuple(tuple(sorted(grouped[precedence])) for precedence in sorted(grouped))


def _run_action(command: tuple[str, ...], root: Path) -> CommandResult:
    """Return a terminal status when an executable action cannot start."""
    try:
        return run_process_group_command(list(command), root)
    except OSError:
        return CommandResult(_COMMAND_FAILURE_EXIT_CODE)


def _skipped_outcome(commit_range: str, reason: str, root: Path) -> PostCommitMaintenanceOutcome:
    """Record a non-executing range outcome."""
    logger.info(_MAINTENANCE_SKIPPED_EVENT, commit_range=commit_range, reason=reason, project_root=str(root))
    return PostCommitMaintenanceOutcome(commit_range, (), (), reason)
