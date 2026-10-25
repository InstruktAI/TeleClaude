"""Publish a todo's slug branch to origin and report what happened as a typed outcome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.git import GIT_EXECUTABLE, GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.project_root import is_slug_worktree

logger = get_logger(__name__)

_PUSH_TIMEOUT_SECONDS = 30
_GIT_ABBREV_REF = "--abbrev-ref"
_GIT_HEAD = "HEAD"
_GIT_PUSH = "push"
_GIT_PUSH_PORCELAIN = "--porcelain"
_GIT_FORCE_WITH_LEASE = "--force-with-lease"
_GIT_FORCE_IF_INCLUDES = "--force-if-includes"
_ORIGIN = "origin"
_BRANCH_REF_TEMPLATE = "HEAD:refs/heads/{branch}"
_STATUS_SEPARATOR = "\n"
_EMPTY_TEXT = ""
_PUBLISH_SKIPPED_EVENT = "todo_branch_publish_skipped"
_PUBLISHED_EVENT = "todo_branch_published"
_PUBLISH_FAILED_EVENT = "todo_branch_publish_failed"


class BranchPublishStatus(StrEnum):
    """How a publication attempt ended."""

    PUBLISHED = "published"
    SKIPPED = "skipped"
    FAILED = "failed"


class BranchPublishSkip(StrEnum):
    """Why a publication attempt did nothing."""

    NOT_SLUG_WORKTREE = "not_slug_worktree"
    BRANCH_MISMATCH = "branch_mismatch"
    ORIGIN_MISSING = "origin_missing"


@dataclass(frozen=True)
class BranchPublishOutcome:
    """Result of one publication attempt; `detail` carries git's status text on failure."""

    status: BranchPublishStatus
    branch: str = _EMPTY_TEXT
    sha: str = _EMPTY_TEXT
    skip_reason: BranchPublishSkip | None = None
    detail: str = _EMPTY_TEXT


def publish_todo_branch(worktree_root: Path) -> BranchPublishOutcome:
    """Publish the slug worktree's branch to origin; never raise for a publication failure."""
    if not is_slug_worktree(worktree_root):
        return BranchPublishOutcome(BranchPublishStatus.SKIPPED, skip_reason=BranchPublishSkip.NOT_SLUG_WORKTREE)

    expected_branch = worktree_root.name
    try:
        repo = Repo(str(worktree_root))
        current_branch = repo.git.rev_parse(_GIT_ABBREV_REF, _GIT_HEAD).strip()
        if current_branch != expected_branch:
            return BranchPublishOutcome(
                BranchPublishStatus.SKIPPED, branch=expected_branch, skip_reason=BranchPublishSkip.BRANCH_MISMATCH
            )

        if not any(remote.name == _ORIGIN for remote in repo.remotes):
            logger.debug(_PUBLISH_SKIPPED_EVENT, branch=expected_branch, reason=BranchPublishSkip.ORIGIN_MISSING)
            return BranchPublishOutcome(
                BranchPublishStatus.SKIPPED, branch=expected_branch, skip_reason=BranchPublishSkip.ORIGIN_MISSING
            )

        head_sha = repo.git.rev_parse(_GIT_HEAD).strip()
        args = [
            GIT_EXECUTABLE,
            _GIT_PUSH,
            _GIT_PUSH_PORCELAIN,
            _GIT_FORCE_WITH_LEASE,
            _GIT_FORCE_IF_INCLUDES,
            _ORIGIN,
            _BRANCH_REF_TEMPLATE.format(branch=expected_branch),
        ]
        execute = cast(Callable[..., object], repo.git.execute)
        execute(args, kill_after_timeout=_PUSH_TIMEOUT_SECONDS)
    except GitCommandError as exc:
        status = _STATUS_SEPARATOR.join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if not status:
            status = str(exc).strip()
        return _failed(expected_branch, status)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        return _failed(expected_branch, str(exc).strip())

    logger.info(_PUBLISHED_EVENT, branch=expected_branch, sha=head_sha)
    return BranchPublishOutcome(BranchPublishStatus.PUBLISHED, branch=expected_branch, sha=head_sha)


def _failed(branch: str, status: str) -> BranchPublishOutcome:
    logger.warning(_PUBLISH_FAILED_EVENT, branch=branch, status=status)
    return BranchPublishOutcome(BranchPublishStatus.FAILED, branch=branch, detail=status)
