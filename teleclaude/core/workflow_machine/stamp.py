"""The stamp's pre-commit work: the reference checks and the build gates, each run once per invocation.

``local/projects/teleclaude/spec/feature/workflow/work-review-cycle`` is the contract. A stamp at commit
H is accepted only while H is the integration head, the item's worktree branch head and H agree, the
worktree is clean, the worktree carries file-changing commits beyond the shared branch, and the
project's native test target passes. The references are read again after the gates ran.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.git_ops import get_head_commit, has_uncommitted_changes
from teleclaude.core.workflow_machine.act_types import ActRefused
from teleclaude.git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = get_logger(__name__)


class StampRefusal(StrEnum):
    """Why a stamp is refused; each names the disagreeing references or the failing gate."""

    NOT_HEAD = "stamp: {sha} is not the integration head ({head})"
    WORKTREE_HEAD = "stamp: the worktree branch head {worktree} differs from {sha}"
    UNCLEAN = "stamp: the worktree has uncommitted changes"
    NO_BUILD_COMMITS = "stamp: the worktree carries no file-changing commit beyond the shared branch"
    GATE_FAILED = "stamp: {output}"
    UNKNOWN_UNIT = "stamp: processes of an earlier stamp of this item may still run in group {pgid}; nothing was signalled or replaced"
    UNIT_STARTED_ELSEWHERE = "stamp: an earlier stamp of this item was started on {host}, which alone can classify it"
    ROW_EXISTS = "stamp: the registry already holds a unit for this item that has not been classified"
    NOT_STARTED = "stamp: the gate runner could not be started: {reason}"
    UNSETTLED = "stamp: the gate's processes could not be shown to have ended"
    HEAD_UNKNOWN = "stamp: the integration head of {item} cannot be read"


NO_HEAD: Final = ""
ORIGIN: Final = "origin"
BRANCH_REF_TEMPLATE: Final = "refs/heads/{branch}"
REMOTE_READ_TIMEOUT_SECONDS: Final = 10
REMOTE_READ_FAILED_TEMPLATE: Final = "the integration ref of {item} cannot be read: {reason}"


def worktree_path(project_root: str, item: str) -> Path:
    """The item's worktree, whose name derives from the item identity."""
    return Path(project_root) / WORKTREE_DIR / item


class RemoteReadFailed(Exception):
    """The branch on origin could not be observed; distinct from observing that it does not exist."""


def _read_remote_head(project_root: str, item: str) -> str:
    """One bounded read of the branch on origin; empty only when the remote answered and has no such branch."""
    try:
        output = Repo(project_root).git.ls_remote(
            ORIGIN, BRANCH_REF_TEMPLATE.format(branch=item), kill_after_timeout=REMOTE_READ_TIMEOUT_SECONDS
        )
    except (GitCommandError, InvalidGitRepositoryError, NoSuchPathError, OSError) as exc:
        raise RemoteReadFailed(REMOTE_READ_FAILED_TEMPLATE.format(item=item, reason=str(exc).strip())) from exc
    parts = output.strip().split()
    return parts[0] if parts else NO_HEAD


async def integration_head(project_root: str, item: str) -> str:
    """The commit the item's integration ref carries now; empty when it does not exist.

    Raises ``RemoteReadFailed`` when the remote cannot be read within the bound.
    """
    return await asyncio.to_thread(_read_remote_head, project_root, item)


async def check_refs(project_root: str, item: str, sha: str) -> None:
    """Refuse when the integration head, the worktree head and the stamped commit disagree, or the worktree is dirty."""
    try:
        head = await integration_head(project_root, item)
    except RemoteReadFailed as failure:
        raise ActRefused(str(failure)) from failure
    if not head:
        raise ActRefused(StampRefusal.HEAD_UNKNOWN.value.format(item=item))
    if head != sha:
        raise ActRefused(StampRefusal.NOT_HEAD.value.format(sha=sha, head=head))
    worktree = await asyncio.to_thread(get_head_commit, str(worktree_path(project_root, item)))
    if worktree != sha:
        raise ActRefused(StampRefusal.WORKTREE_HEAD.value.format(worktree=worktree or NO_HEAD, sha=sha))
    if await asyncio.to_thread(has_uncommitted_changes, project_root, item):
        raise ActRefused(StampRefusal.UNCLEAN.value)
