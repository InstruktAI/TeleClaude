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
_TRACKING_REF_TEMPLATE = "refs/remotes/origin/{branch}"
_GIT_VERIFY = "--verify"
_GIT_QUIET = "--quiet"
_GIT_REFLOG = "reflog"
_GIT_REFLOG_FORMAT = "--format=%H"
_GIT_REFLOG_LIMIT = "-n100"
_BRANCH_REF_TEMPLATE = "refs/heads/{branch}"
_GIT_IS_ANCESTOR = "--is-ancestor"
_UNINCORPORATED_MESSAGE = (
    "Commit recorded; the todo branch was not published because origin carries work this clone has not "
    "incorporated. Fetch and integrate it, then commit again."
)
NO_TIP = ""
_STATUS_SEPARATOR = "\n"


def _known_remote_tip(repo: Repo, branch: str) -> str | None:
    """The tip of the branch as this clone last observed it; empty when it never saw one, None when unreadable.

    The tracking reference is the earned base of the overwrite: an update leased on it is refused when
    the remote moved since this clone last saw it.
    """
    try:
        tip: str = repo.git.rev_parse(_GIT_VERIFY, _GIT_QUIET, _TRACKING_REF_TEMPLATE.format(branch=branch))
        return tip.strip()
    except GitCommandError:
        return NO_TIP


def _is_ancestor(repo: Repo, tip: str, descendant: str) -> bool:
    try:
        repo.git.merge_base(_GIT_IS_ANCESTOR, tip, descendant)
    except GitCommandError:
        return False
    return True


def _incorporates(repo: Repo, tip: str, head_sha: str, branch: str) -> bool:
    """Whether this clone has integrated the known remote tip: the commit to push contains it, or a former tip of the branch did.

    The second case is a rebased commit whose branch once carried the tip; it is the case force-if-includes
    admitted, and the branch's own reflog is the evidence.
    """
    if not tip or _is_ancestor(repo, tip, head_sha):
        return True
    entries = repo.git.reflog(_GIT_REFLOG_FORMAT, _GIT_REFLOG_LIMIT, _BRANCH_REF_TEMPLATE.format(branch=branch)).split()
    return any(_is_ancestor(repo, tip, entry) for entry in entries)


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
    expected_tip = _known_remote_tip(repo, expected_branch)
    if expected_tip is None or not _incorporates(repo, expected_tip, head_sha, expected_branch):
        print(_UNINCORPORATED_MESSAGE, file=sys.stderr)
        logger.warning(
            "code_commit.branch_publish_refused", branch=expected_branch, sha=head_sha, reason="unincorporated"
        )
        return
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
