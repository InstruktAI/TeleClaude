"""Range-based deterministic maintenance at canonical-main boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import (
    ActivationRange,
    fill_activation_range,
    load_checkpoint_model,
    main_only_maintenance_action_ids_for_files,
)
from teleclaude.constants import MaintenanceAction
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_root import resolve_project_root
from teleclaude.runtime.command_runner import CommandResult, run_process_group_commands

logger = get_logger(__name__)

_GIT_NAME_ONLY_ARGUMENT = "--name-only"
_GIT_DIFF_TREE_ARGUMENTS = ("--root", "--no-commit-id", _GIT_NAME_ONLY_ARGUMENT, "-r")
_FULL_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_SYNC_ACTION_ID = "sync"
_MAIN_BRANCH_NAME = "main"
_GIT_HEAD_REFERENCE = "HEAD"
_GIT_ORIGINAL_HEAD_REFERENCE = "ORIG_HEAD"
_MAINTENANCE_ACTION_FINISHED_EVENT = "post_commit_maintenance_action_finished"
_MAINTENANCE_ACTION_STARTED_EVENT = "post_commit_maintenance_action_started"
_MAINTENANCE_RESOLVED_EVENT = "post_commit_maintenance_resolved"
_MAINTENANCE_SKIPPED_EVENT = "post_commit_maintenance_skipped"
_SKIP_GIT_UNAVAILABLE = "git_unavailable"
_SKIP_INELIGIBLE_LOCATION = "ineligible_location"
_GIT_FAILURES = (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError, TypeError, ValueError)


@dataclass(frozen=True)
class MaintenanceActionOutcome:
    """One terminal maintenance outcome."""

    action_id: str
    result: CommandResult


@dataclass(frozen=True)
class PostCommitMaintenanceOutcome:
    """The ordered result of one canonical-main range."""

    activation_range: ActivationRange
    action_ids: tuple[str, ...]
    action_outcomes: tuple[MaintenanceActionOutcome, ...]
    skip_reason: str | None


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


def activation_range_owes_action(project_root: Path, activation_range: ActivationRange, action_id: str) -> bool:
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
        changed_files = _changed_files(repository, activation_range)
        action_ids = main_only_maintenance_action_ids_for_files(list(changed_files), root)
    except _GIT_FAILURES:
        return False
    return action_id in action_ids


def run_post_commit_maintenance(project_root: Path, activation_range: ActivationRange) -> PostCommitMaintenanceOutcome:
    """Execute executable main-only actions owed by one canonical-main range."""
    root = project_root.resolve()
    if root != resolve_project_root(root):
        return _skipped_outcome(activation_range, _SKIP_INELIGIBLE_LOCATION, root)
    try:
        repository = Repo(str(root))
        if repository.head.is_detached or repository.active_branch.name != _MAIN_BRANCH_NAME:
            return _skipped_outcome(activation_range, _SKIP_INELIGIBLE_LOCATION, root)
        if not _is_literal_range(repository, activation_range):
            return _skipped_outcome(activation_range, _SKIP_GIT_UNAVAILABLE, root)
        changed_files = _changed_files(repository, activation_range)
    except _GIT_FAILURES as exc:
        logger.warning(
            _MAINTENANCE_SKIPPED_EVENT,
            reason=_SKIP_GIT_UNAVAILABLE,
            before_sha=activation_range.before_sha,
            after_sha=activation_range.after_sha,
            error=str(exc),
        )
        return PostCommitMaintenanceOutcome(activation_range, (), (), _SKIP_GIT_UNAVAILABLE)

    model = load_checkpoint_model(str(root))
    action_ids = tuple(main_only_maintenance_action_ids_for_files(list(changed_files), root))
    logger.info(
        _MAINTENANCE_RESOLVED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        action_ids=action_ids,
        changed_files=changed_files,
    )
    outcomes: list[MaintenanceActionOutcome] = []
    for wave in _precedence_waves(action_ids, model.maintenance):
        for action_id in wave:
            logger.info(
                _MAINTENANCE_ACTION_STARTED_EVENT,
                before_sha=activation_range.before_sha,
                after_sha=activation_range.after_sha,
                action_id=action_id,
            )
        commands = tuple(
            fill_activation_range(model.maintenance[action_id].command, activation_range) for action_id in wave
        )
        results = run_process_group_commands(commands, root)
        for action_id, result in zip(wave, results, strict=True):
            logger.info(
                _MAINTENANCE_ACTION_FINISHED_EVENT,
                before_sha=activation_range.before_sha,
                after_sha=activation_range.after_sha,
                action_id=action_id,
                exit_code=result.exit_code,
            )
            outcomes.append(MaintenanceActionOutcome(action_id, result))
    return PostCommitMaintenanceOutcome(activation_range, action_ids, tuple(outcomes), None)


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


def _precedence_waves(
    action_ids: tuple[str, ...], actions: dict[str, MaintenanceAction]
) -> tuple[tuple[str, ...], ...]:
    """Group stable action ids by their declared precedence."""
    grouped: dict[int, list[str]] = {}
    for action_id in action_ids:
        precedence = actions[action_id].precedence
        grouped.setdefault(precedence, []).append(action_id)
    return tuple(tuple(sorted(grouped[precedence])) for precedence in sorted(grouped))


def _skipped_outcome(activation_range: ActivationRange, reason: str, root: Path) -> PostCommitMaintenanceOutcome:
    """Record a non-executing range outcome."""
    logger.info(
        _MAINTENANCE_SKIPPED_EVENT,
        before_sha=activation_range.before_sha,
        after_sha=activation_range.after_sha,
        reason=reason,
        project_root=str(root),
    )
    return PostCommitMaintenanceOutcome(activation_range, (), (), reason)
