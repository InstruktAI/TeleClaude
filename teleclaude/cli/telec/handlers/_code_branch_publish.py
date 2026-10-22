"""Publish a committed todo branch without making publication part of commit success."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from instrukt_ai_logging import get_logger

from teleclaude.core.github_identity import (
    GitHubPostingContext,
    LocalNativeGitHubInvocation,
    NativeHumanGitHubInvocation,
    resolve_native_github_posting_context,
)
from teleclaude.git import GIT_EXECUTABLE, GitCommandError, Repo
from teleclaude.github.publication import GitHubPublicationCancelled, publish_github_work_branch
from teleclaude.project_root import is_slug_worktree
from teleclaude.types.github_publication import (
    GitHubBranchPublicationRequest,
    GitHubPublicationFailure,
    GitHubPublicationResult,
    GitHubPublicationState,
)

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
_PLATFORM_RESULT = "Commit recorded; GitHub branch publication: {result}"
_PLATFORM_EVENT = "code_commit.github_branch_publication state=%s failure=%s possible_remote_effect=%s"


def publish_todo_branch(repository_root: Path, committed_head: str) -> None:
    """Publish the current todo branch to origin; report failures without failing the commit."""
    if not is_slug_worktree(repository_root):
        return

    try:
        if asyncio.run(_publish_platform_branch(repository_root, committed_head)):
            return
    except GitHubPublicationCancelled as error:
        _report_platform_result(error.result)
        raise
    except Exception:
        # This post-commit supervision boundary must preserve commit success. Raw provider
        # exceptions may contain credentials, so convert them to a defined safe partial result.
        _report_platform_result(
            GitHubPublicationResult(
                state=GitHubPublicationState.UNKNOWN,
                failure=GitHubPublicationFailure.SEND,
                desired=committed_head,
                possible_remote_effect=True,
            )
        )
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


def _report_platform_result(result: GitHubPublicationResult) -> None:
    print(_PLATFORM_RESULT.format(result=result.model_dump_json()), file=sys.stderr)
    logger.info(_PLATFORM_EVENT, result.state, result.failure, result.possible_remote_effect)


async def _publish_platform_branch(repository_root: Path, committed_head: str) -> bool:
    """Keep positive local/human publication intact; no refused binding ever selects human credentials."""
    context = await resolve_native_github_posting_context()
    if isinstance(context, LocalNativeGitHubInvocation | NativeHumanGitHubInvocation):
        return False
    if not isinstance(context, GitHubPostingContext):
        _report_platform_result(
            GitHubPublicationResult(
                state=GitHubPublicationState.REFUSED,
                failure=GitHubPublicationFailure.CONTEXT,
                desired=committed_head,
            )
        )
        return True
    target = context.target
    if not target.branch or not target.base:
        _report_platform_result(
            GitHubPublicationResult(
                state=GitHubPublicationState.REFUSED,
                failure=GitHubPublicationFailure.WORK_REF,
                desired=committed_head,
            )
        )
        return True
    request = GitHubBranchPublicationRequest(
        target=target,
        worktree=repository_root.resolve(),
        branch=target.branch,
        head_sha=committed_head,
        base=target.base,
    )
    _report_platform_result(await publish_github_work_branch(context, request))
    return True
