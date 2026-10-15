"""Publish a committed todo branch without making publication part of commit success."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from http import HTTPMethod
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger
from pydantic import ValidationError

from teleclaude.cli.tool_client import ToolAPIError, tool_api_request
from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo
from teleclaude.project_root import is_slug_worktree
from teleclaude.types.todo_head import TodoHeadApiRoute, TodoHeadRequestField, TodoIntentReceipt

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
_ORIGIN = "origin"
_LEASE_TEMPLATE = "--force-with-lease=refs/heads/{branch}:{tip}"
_SHA_REF_TEMPLATE = "{sha}:refs/heads/{branch}"
_BRANCH_HEAD_TEMPLATE = "refs/heads/{branch}"
NO_TIP = ""
_STATUS_SEPARATOR = "\n"


def _remote_tip(repo: Repo, branch: str) -> str:
    """The commit the branch carries on origin now; empty when the branch does not exist there."""
    output = repo.git.ls_remote(_ORIGIN, _BRANCH_HEAD_TEMPLATE.format(branch=branch)).strip()
    parts = output.split()
    return parts[0] if parts else NO_TIP


def _report(path: str, body: Mapping[str, str | bool]) -> object | None:
    """Send a publish report to the daemon; None when it could not be delivered, which never fails the commit."""
    try:
        return tool_api_request(HTTPMethod.POST, path, json_body=body)
    except (ToolAPIError, OSError) as exc:
        logger.debug("code_commit.publish_report_unavailable", path=path, reason=str(exc))
        return None


def _register_intent(root: Path, branch: str, sha: str, expected_tip: str) -> str | None:
    response = _report(
        TodoHeadApiRoute.INTENT_PATH,
        {
            TodoHeadRequestField.ITEM: branch,
            TodoHeadRequestField.SHA: sha,
            TodoHeadRequestField.EXPECTED_TIP: expected_tip,
            TodoHeadRequestField.CWD: str(root),
        },
    )
    if response is None:
        return None
    try:
        return TodoIntentReceipt.model_validate(response).key
    except ValidationError:
        return None


def _complete_intent(root: Path, branch: str, key: str, swapped: bool) -> None:
    _report(
        TodoHeadApiRoute.COMPLETION_PATH,
        {
            TodoHeadRequestField.ITEM: branch,
            TodoHeadRequestField.KEY: key,
            TodoHeadRequestField.SWAPPED: swapped,
            TodoHeadRequestField.CWD: str(root),
        },
    )


def publish_todo_branch(repository_root: Path) -> None:
    """Publish the current todo branch to origin; report failures without failing the commit.

    The commit just created is pushed by its identity, never by a symbolic head, as one compare-and-swap
    update of the branch from the tip read immediately before. The push is reported to the platform around
    the push, so a head notice names the exact update this call performed.
    """
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
    expected_tip = _remote_tip(repo, expected_branch)
    key = _register_intent(repository_root, expected_branch, head_sha, expected_tip)
    args = [
        GIT_EXECUTABLE,
        _GIT_PUSH,
        _GIT_PUSH_PORCELAIN,
        _LEASE_TEMPLATE.format(branch=expected_branch, tip=expected_tip),
        _ORIGIN,
        _SHA_REF_TEMPLATE.format(sha=head_sha, branch=expected_branch),
    ]
    execute = cast(Callable[..., object], repo.git.execute)
    swapped = False
    try:
        execute(args, kill_after_timeout=_PUSH_TIMEOUT_SECONDS)
        swapped = True
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
    finally:
        if key is not None:
            _complete_intent(repository_root, expected_branch, key, swapped)

    if swapped:
        logger.info("code_commit.branch_published", branch=expected_branch, sha=head_sha)
