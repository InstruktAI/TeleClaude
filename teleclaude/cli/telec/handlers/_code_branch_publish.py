"""Publish a committed todo branch without making publication part of commit success."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo
from teleclaude.project_root import is_slug_worktree

logger = get_logger(__name__)

_BRANCH_MISMATCH_MESSAGE = "Commit recorded; branch was not published because it is not the todo's branch."
_PUBLISH_FAILURE_MESSAGE = (
    "Commit is recorded, but publishing the todo branch to origin failed; the next commit will publish it again."
)
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


def publish_todo_branch(repository_root: Path) -> None:
    """Publish the current todo branch to origin; report failures without failing the commit."""
    if not is_slug_worktree(repository_root):
        return

    repo = Repo(str(repository_root))
    expected_branch = repository_root.name
    current_branch = repo.git.rev_parse(_GIT_ABBREV_REF, _GIT_HEAD).strip()
    if current_branch != expected_branch:
        print(_BRANCH_MISMATCH_MESSAGE, file=sys.stderr)
        return

    if not any(remote.name == _ORIGIN for remote in repo.remotes):
        logger.debug("code_commit.branch_publish_skipped", branch=expected_branch, reason="origin_missing")
        return

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
    try:
        execute(args, kill_after_timeout=_PUSH_TIMEOUT_SECONDS)
    except GitCommandError as exc:
        status = _STATUS_SEPARATOR.join(part.strip() for part in (exc.stdout, exc.stderr) if part and part.strip())
        if not status:
            status = str(exc).strip()
        print(f"{_PUBLISH_FAILURE_MESSAGE}\n{status}", file=sys.stderr)
        logger.warning(
            "code_commit.branch_publish_failed",
            branch=expected_branch,
            sha=head_sha,
            status=status,
        )
        return

    logger.info("code_commit.branch_published", branch=expected_branch, sha=head_sha)
