"""Serialize checkout association with source-work admission and inspect blockers."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.constants import WORKTREE_DIR
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, Repo

_LOCK_FILENAME = "checkout-transition.lock"
_STATE_DIRECTORY = ".teleclaude"
_INTEGRATION_STATE_DIRECTORY = "integration"
_INTEGRATION_STATE_FILENAME = "state.json"
_INTEGRATION_WORKTREE_NAME = "_integration"
_CHECKPOINT_PHASE_FIELD = "phase"
_CHECKPOINT_CANDIDATE_FIELD = "candidate_slug"
_UNKNOWN_CANDIDATE = "unknown"
_GIT_DIRECTORY_FILENAME = ".git"
_MERGE_HEAD_FILENAME = "MERGE_HEAD"
_GIT_DIR_SEPARATOR = ":"
_UTF8 = "utf-8"
_APPEND_MODE = "a"
_IN_FLIGHT_INTEGRATION_RECOVERY = "finish or recover the in-flight integration before association"
_UNFINISHED_INTEGRATION_RECOVERY = "finish or recover the unfinished integration before association"
_UNPUBLISHED_COMMIT_RECOVERY = "publish this commit or move its work to the development checkout"
_TRACKED_CHANGE_RECOVERY = "commit the change through the development checkout or its stranded-path owner"
_UNTRACKED_CHANGE_RECOVERY = "move the untracked source into the development checkout before association"
_CHECKPOINT_SUBJECT_TEMPLATE = "{path} ({phase}, candidate={candidate})"
_CHECKPOINT_REQUIRED_SUBJECT_TEMPLATE = "{kind} {subject}: {recovery}"
_BLOCKER_DETAIL_SEPARATOR = "; "
_INTEGRATION_IDLE_PHASES = frozenset({"idle", "completed"})
_PORCELAIN_SOURCE_ARGUMENTS = ("status", "--porcelain=v1", "--untracked-files=all")
_UNPUBLISHED_COMMIT_ARGUMENTS = ("rev-list", "origin/main..refs/heads/main")
_MISSING_BASELINE = "origin/main is unavailable"
_CHECKPOINT_INVALID = "integration checkpoint is unreadable or invalid"


class CheckoutTransitionBlockerKind(StrEnum):
    """Closed identities for source-transition blockers."""

    INTEGRATION_CHECKPOINT = "integration_checkpoint"
    INTEGRATION_WORKTREE = "integration_worktree"
    UNPUBLISHED_MAIN_COMMIT = "unpublished_main_commit"
    TRACKED_MODIFICATION = "tracked_modification"
    UNTRACKED_SOURCE = "untracked_source"
    SOURCE_INSPECTION = "source_inspection"


@dataclass(frozen=True)
class CheckoutTransitionBlocker:
    """One exact source object that prevents an installed checkout transition."""

    kind: CheckoutTransitionBlockerKind
    subject: str
    recovery: str


@contextmanager
def checkout_transition_lock(installed_root: Path) -> Iterator[None]:
    """Serialize source creation, integration admission and association publication."""
    lock_path = installed_root / _STATE_DIRECTORY / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open(_APPEND_MODE, encoding=_UTF8) as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def source_transition_blockers(installed_root: Path) -> tuple[CheckoutTransitionBlocker, ...]:
    """Report integration, unpublished-main and tracked-work blockers by object."""
    root = installed_root.expanduser().resolve()
    blockers: list[CheckoutTransitionBlocker] = []
    checkpoint = root / _STATE_DIRECTORY / _INTEGRATION_STATE_DIRECTORY / _INTEGRATION_STATE_FILENAME
    if checkpoint.exists():
        try:
            payload = json.loads(checkpoint.read_text(encoding=_UTF8))
            phase = payload.get(_CHECKPOINT_PHASE_FIELD) if isinstance(payload, dict) else None
            candidate = payload.get(_CHECKPOINT_CANDIDATE_FIELD) if isinstance(payload, dict) else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            phase = None
            candidate = None
        if not isinstance(phase, str):
            blockers.append(
                CheckoutTransitionBlocker(
                    CheckoutTransitionBlockerKind.INTEGRATION_CHECKPOINT,
                    str(checkpoint),
                    _CHECKPOINT_INVALID,
                )
            )
        elif phase not in _INTEGRATION_IDLE_PHASES:
            blockers.append(
                CheckoutTransitionBlocker(
                    CheckoutTransitionBlockerKind.INTEGRATION_CHECKPOINT,
                    _CHECKPOINT_SUBJECT_TEMPLATE.format(
                        path=checkpoint,
                        phase=phase,
                        candidate=candidate or _UNKNOWN_CANDIDATE,
                    ),
                    _IN_FLIGHT_INTEGRATION_RECOVERY,
                )
            )

    integration_worktree = root / WORKTREE_DIR / _INTEGRATION_WORKTREE_NAME
    if integration_worktree.is_dir():
        merge_head = integration_worktree / _GIT_DIRECTORY_FILENAME
        if merge_head.is_file():
            try:
                git_dir_value = merge_head.read_text(encoding=_UTF8).strip().split(_GIT_DIR_SEPARATOR, 1)[-1].strip()
                git_dir = (integration_worktree / git_dir_value).resolve()
                merge_in_progress = (git_dir / _MERGE_HEAD_FILENAME).is_file()
            except (OSError, UnicodeError):
                merge_in_progress = True
            if merge_in_progress and not any(
                item.kind is CheckoutTransitionBlockerKind.INTEGRATION_CHECKPOINT for item in blockers
            ):
                blockers.append(
                    CheckoutTransitionBlocker(
                        CheckoutTransitionBlockerKind.INTEGRATION_WORKTREE,
                        str(integration_worktree),
                        _UNFINISHED_INTEGRATION_RECOVERY,
                    )
                )

    try:
        repository = Repo(str(root))
        try:
            unpublished = repository.git.rev_list(*_UNPUBLISHED_COMMIT_ARGUMENTS).splitlines()
        except GitCommandError as exc:
            raise RuntimeError(_MISSING_BASELINE) from exc
        for commit in unpublished:
            blockers.append(
                CheckoutTransitionBlocker(
                    CheckoutTransitionBlockerKind.UNPUBLISHED_MAIN_COMMIT,
                    commit,
                    _UNPUBLISHED_COMMIT_RECOVERY,
                )
            )
        dirty = repository.git.status(*_PORCELAIN_SOURCE_ARGUMENTS[1:]).splitlines()
    except (GitCommandError, InvalidGitRepositoryError, OSError, RuntimeError) as exc:
        blockers.append(
            CheckoutTransitionBlocker(
                CheckoutTransitionBlockerKind.SOURCE_INSPECTION,
                str(root),
                str(exc) or _MISSING_BASELINE,
            )
        )
    else:
        for entry in dirty:
            is_untracked = entry.startswith("??")
            blockers.append(
                CheckoutTransitionBlocker(
                    (
                        CheckoutTransitionBlockerKind.UNTRACKED_SOURCE
                        if is_untracked
                        else CheckoutTransitionBlockerKind.TRACKED_MODIFICATION
                    ),
                    entry[3:] if is_untracked else entry,
                    _UNTRACKED_CHANGE_RECOVERY if is_untracked else _TRACKED_CHANGE_RECOVERY,
                )
            )
    return tuple(blockers)
