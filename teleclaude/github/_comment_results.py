"""Verify finite issue-comment responses while keeping original work and provider container identities distinct."""

from __future__ import annotations

import asyncio
from hashlib import sha256

from githubkit_schemas.v2026_03_10.models import IssueComment
from instrukt_ai_logging import get_logger

from teleclaude.core.github_identity import GitHubPostingContext
from teleclaude.github import _native_gh
from teleclaude.github.credentials import GitHubCredentialRefused
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind
from teleclaude.types.github_binding import GitHubWorkTarget
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubEditEvidence,
    GitHubIssueCommentRequest,
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
)

logger = get_logger(__name__)
_REPOSITORY_SEPARATOR = "/"
_UTF8 = "utf-8"
_ISSUE_URL = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"
_COMMENT_URL = "https://api.github.com/repos/{owner}/{repo}/issues/comments/{identifier}"
_UNVERIFIED_OBJECT = "GitHub comment result could not be verified"
_DEFINITIVE_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_CANCELLED_MESSAGE = "GitHub posting cancelled; available provider evidence is attached"
_CANCELLED_EVENT = (
    "github_comment_post_cancelled acceptance=%s failure=%s session_id=%s provider_id=%s provider_status=%s"
)
_ASSOCIATION = "association"
_FAILURE = "failure"


class GitHubPostingCancelled(asyncio.CancelledError):
    """Propagate cancellation with safe provider evidence, without claiming unrecorded attribution."""

    def __init__(self, result: GitHubPostResult) -> None:
        super().__init__(_CANCELLED_MESSAGE)
        self.result = result


def comment_reference(
    comment: IssueComment,
    target: GitHubWorkTarget,
    *,
    container_number: int | None = None,
) -> GitHubObjectRef:
    owner, repo = target.repository.split(_REPOSITORY_SEPARATOR)
    container = container_number if container_number is not None else target.issue_number
    if (
        comment.id <= 0
        or comment.issue_url.casefold() != _ISSUE_URL.format(owner=owner, repo=repo, number=container).casefold()
        or comment.url.casefold() != _COMMENT_URL.format(owner=owner, repo=repo, identifier=comment.id).casefold()
    ):
        raise ValueError(_UNVERIFIED_OBJECT)
    return GitHubObjectRef(
        repository_id=target.repository_id,
        container_number=container,
        kind=GitHubObjectKind.ISSUE_COMMENT,
        provider_id=comment.id,
    )


def comment_actor(comment: IssueComment) -> GitHubAccount:
    if comment.user is None:
        raise ValueError(_UNVERIFIED_OBJECT)
    return GitHubAccount(
        id=comment.user.id,
        node_id=comment.user.node_id,
        login=comment.user.login,
        type=GitHubAccountKind(comment.user.type),
    )


def accepted(
    response: _native_gh.Response, request: GitHubIssueCommentRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    """Verify actual object, scope, body and stable author independently of the envelope's assertions."""
    ref = None
    digest = None
    evidence = None
    try:
        comment = IssueComment.model_validate_json(response.body)
        ref = comment_reference(
            comment,
            request.target,
            container_number=request.pr_scope.container_number if request.pr_scope is not None else None,
        )
        if not isinstance(comment.body, str) or comment.body != body or comment.user is None:
            raise ValueError(_UNVERIFIED_OBJECT)
        digest = sha256(comment.body.encode(_UTF8)).hexdigest()
        evidence = GitHubEditEvidence(updated_at=comment.updated_at.isoformat())
        author = comment_actor(comment)
        if not author.same_account(context.binding.assignment.actor):
            return GitHubPostResult(
                acceptance=GitHubAcceptance.CONFIRMED,
                object=ref,
                failure=GitHubPostFailure.ACTOR_MISMATCH,
                body_digest=digest,
                edit_evidence=evidence,
                provider_status=response.status,
            )
        association = GitHubObjectAssociation(
            object=ref,
            work_issue_number=request.target.issue_number,
            session_id=context.binding.session_id,
            role=context.binding.role,
            actor=author,
            source=request.source,
            body_digest=digest,
            edit_evidence=evidence,
        )
        return GitHubPostResult(
            acceptance=GitHubAcceptance.CONFIRMED,
            object=ref,
            association=association,
            body_digest=digest,
            edit_evidence=evidence,
            provider_status=response.status,
        )
    except ValueError:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.CONFIRMED,
            object=ref,
            failure=GitHubPostFailure.RESULT_UNVERIFIED,
            body_digest=digest,
            edit_evidence=evidence,
            provider_status=response.status,
        )


def provider_result(
    response: _native_gh.Response, request: GitHubIssueCommentRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    """Classify the same received evidence for normal completion and cancellation."""
    if not response.started:
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.BINARY_UNAVAILABLE)
    if response.status in _DEFINITIVE_REJECTIONS:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.NO_EFFECT,
            failure=GitHubPostFailure.PROVIDER_REFUSED,
            provider_status=response.status,
            retry_after=response.retry_after,
        )
    if response.status != 201:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.UNKNOWN,
            failure=GitHubPostFailure.SEND_UNCERTAIN,
            provider_status=response.status,
            retry_after=response.retry_after,
        )
    return accepted(response, request, context, body)


def cancelled(result: GitHubPostResult, session_id: str) -> GitHubPostingCancelled:
    if result.association is not None:
        result = result.model_copy(update={_ASSOCIATION: None, _FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
    logger.warning(
        _CANCELLED_EVENT,
        result.acceptance,
        result.failure,
        session_id,
        result.object.provider_id if result.object is not None else None,
        result.provider_status,
    )
    return GitHubPostingCancelled(result)


def credential_result(error: GitHubCredentialRefused) -> GitHubPostResult:
    return GitHubPostResult(
        acceptance=GitHubAcceptance.NO_EFFECT,
        failure=GitHubPostFailure.CREDENTIAL_REFUSED,
        provider_status=error.rate_limit.status_code if error.rate_limit is not None else None,
        retry_after=error.rate_limit.retry_after if error.rate_limit is not None else None,
        credential_refusal=error.key_failure.value if error.key_failure is not None else error.reason.value,
    )
