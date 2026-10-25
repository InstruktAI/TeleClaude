"""Publish a committed todo branch without making publication part of commit success."""

from __future__ import annotations

import sys
from pathlib import Path

from teleclaude.core.next_machine.branch_publish import BranchPublishSkip, BranchPublishStatus, publish_todo_branch

_BRANCH_MISMATCH_MESSAGE = "Commit recorded; branch was not published because it is not the todo's branch."
_FAILURE_WITH_DETAIL_TEMPLATE = "{}\n{}"
_PUBLISH_FAILURE_MESSAGE = (
    "Commit is recorded, but publishing the todo branch to origin failed; the next commit will publish it again."
)


def publish_committed_todo_branch(repository_root: Path) -> None:
    """Publish the current todo branch to origin; report failures without failing the commit."""
    outcome = publish_todo_branch(repository_root)
    if outcome.status == BranchPublishStatus.FAILED:
        print(_FAILURE_WITH_DETAIL_TEMPLATE.format(_PUBLISH_FAILURE_MESSAGE, outcome.detail), file=sys.stderr)
    elif outcome.skip_reason == BranchPublishSkip.BRANCH_MISMATCH:
        print(_BRANCH_MISMATCH_MESSAGE, file=sys.stderr)
