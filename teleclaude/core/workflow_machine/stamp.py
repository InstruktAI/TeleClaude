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

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.next_machine.build_gates import run_build_gates
from teleclaude.core.next_machine.git_ops import (
    get_head_commit,
    get_remote_branch_head,
    has_build_commits_beyond_main,
    has_uncommitted_changes,
)
from teleclaude.core.workflow_machine.act_types import ActRefused


class StampRefusal(StrEnum):
    """Why a stamp is refused; each names the disagreeing references or the failing gate."""

    NOT_HEAD = "stamp: {sha} is not the integration head ({head})"
    WORKTREE_HEAD = "stamp: the worktree branch head {worktree} differs from {sha}"
    UNCLEAN = "stamp: the worktree has uncommitted changes"
    NO_BUILD_COMMITS = "stamp: the worktree carries no file-changing commit beyond the shared branch"
    GATE_FAILED = "stamp: {output}"
    HEAD_UNKNOWN = "stamp: the integration head of {item} cannot be read"


NO_HEAD: Final = ""


def worktree_path(project_root: str, item: str) -> Path:
    """The item's worktree, whose name derives from the item identity."""
    return Path(project_root) / WORKTREE_DIR / item


async def integration_head(project_root: str, item: str) -> str:
    """The commit the item's integration ref carries now; empty when it cannot be read."""
    return await asyncio.to_thread(get_remote_branch_head, project_root, item)


async def check_refs(project_root: str, item: str, sha: str) -> None:
    """Refuse when the integration head, the worktree head and the stamped commit disagree, or the worktree is dirty."""
    head = await integration_head(project_root, item)
    if not head:
        raise ActRefused(StampRefusal.HEAD_UNKNOWN.value.format(item=item))
    if head != sha:
        raise ActRefused(StampRefusal.NOT_HEAD.value.format(sha=sha, head=head))
    worktree = await asyncio.to_thread(get_head_commit, str(worktree_path(project_root, item)))
    if worktree != sha:
        raise ActRefused(StampRefusal.WORKTREE_HEAD.value.format(worktree=worktree or NO_HEAD, sha=sha))
    if await asyncio.to_thread(has_uncommitted_changes, project_root, item):
        raise ActRefused(StampRefusal.UNCLEAN.value)


async def run_gates(project_root: str, item: str) -> None:
    """Refuse unless the worktree carries build commits and the project's native test target passes."""
    worktree = str(worktree_path(project_root, item))
    if not await asyncio.to_thread(has_build_commits_beyond_main, worktree):
        raise ActRefused(StampRefusal.NO_BUILD_COMMITS.value)
    passed, output = await asyncio.to_thread(run_build_gates, worktree, item)
    if not passed:
        raise ActRefused(StampRefusal.GATE_FAILED.value.format(output=output))
