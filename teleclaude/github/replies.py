"""Post explicit top-level review-comment replies and verify their separate provider placement facts."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from urllib.parse import quote

from githubkit.utils import UNSET
from githubkit_schemas.v2026_03_10.models import PullRequestReviewComment
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import GitHubPostingContext, resolve_native_github_posting_context
from teleclaude.github import _native_gh
from teleclaude.github._comment_results import cancelled, credential_result
from teleclaude.github._conversation_scope import preflight_pr_scope, requested_pr_scope
from teleclaude.github._pr_provider import prose_digest
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.envelope import render_github_envelope
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubEditEvidence,
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
    GitHubReviewCommentPlacement,
    GitHubReviewReplyRequest,
    NativeGitHubPostSource,
)
from teleclaude.types.workflow_record import Act

logger = get_logger(__name__)
_UTF8 = "utf-8"
_EMPTY = ""
_SLASH = "/"
_BODY = "body"
_CONFIG_PREFIX = "teleclaude-gh-reply-"
_PERMISSIONS: AppPermissionsType = {"pull_requests": "write"}
_FIXED_ENVIRONMENT = {"GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "GH_PAGER": ""}
_GH_TOKEN = "GH_TOKEN"
_GH_CONFIG_DIR = "GH_CONFIG_DIR"
_COMMENT_ENDPOINT = "repos/{repository}/pulls/comments/{identifier}"
_REPLY_ENDPOINT = "repos/{repository}/pulls/{number}/comments/{identifier}/replies"
_COMMENT_URL = "https://api.github.com/repos/{repository}/pulls/comments/{identifier}"
_PR_URL = "https://api.github.com/repos/{repository}/pulls/{number}"
_WEB_URL = "https://github.com/{repository}/pull/{number}#discussion_r{identifier}"
_INVALID = "Review-comment response does not establish exact provider placement and writer"
_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_LOG = "github_native_reply acceptance=%s failure=%s session_id=%s provider_id=%s root_id=%s"
_ASSOCIATION = "association"
_FAILURE = "failure"


@dataclass(frozen=True)
class NativeReplyObservation:
    """Verified native reply author/body/placement, with no lifecycle or review authority."""

    object: GitHubObjectRef
    actor: GitHubAccount
    digest: str
    evidence: GitHubEditEvidence
    placement: GitHubReviewCommentPlacement


def _reference(comment: PullRequestReviewComment, context: GitHubPostingContext, number: int) -> GitHubObjectRef:
    repository = context.target.repository
    if (
        comment.id <= 0
        or comment.url.casefold() != _COMMENT_URL.format(repository=repository, identifier=comment.id).casefold()
        or comment.pull_request_url.casefold() != _PR_URL.format(repository=repository, number=number).casefold()
        or comment.html_url.casefold()
        != _WEB_URL.format(repository=repository, number=number, identifier=comment.id).casefold()
    ):
        raise ValueError(_INVALID)
    return GitHubObjectRef(
        repository_id=context.target.repository_id,
        container_number=number,
        kind=GitHubObjectKind.REVIEW_COMMENT,
        provider_id=comment.id,
    )


def _placement(comment: PullRequestReviewComment) -> GitHubReviewCommentPlacement:
    if not isinstance(comment.in_reply_to_id, int) or comment.in_reply_to_id <= 0:
        raise ValueError(_INVALID)
    return GitHubReviewCommentPlacement(
        in_reply_to_id=comment.in_reply_to_id,
        commit_id=comment.commit_id,
        original_commit_id=comment.original_commit_id,
        review_id=comment.pull_request_review_id,
        path=comment.path,
        line=comment.line if isinstance(comment.line, int) else None,
        original_line=comment.original_line if isinstance(comment.original_line, int) else None,
        start_line=comment.start_line if isinstance(comment.start_line, int) else None,
        original_start_line=comment.original_start_line if isinstance(comment.original_start_line, int) else None,
        side=comment.side if isinstance(comment.side, str) else None,
        start_side=comment.start_side if isinstance(comment.start_side, str) else None,
    )


def _observation(
    comment: PullRequestReviewComment,
    context: GitHubPostingContext,
    number: int,
    root_id: int,
    *,
    body: str | None = None,
) -> NativeReplyObservation:
    ref = _reference(comment, context, number)
    placement = _placement(comment)
    if (
        placement.in_reply_to_id != root_id
        or comment.user is None
        or (body is not None and comment.body != body)
        or comment.updated_at.utcoffset() is None
    ):
        raise ValueError(_INVALID)
    actor = GitHubAccount(
        id=comment.user.id,
        node_id=comment.user.node_id,
        login=comment.user.login,
        type=GitHubAccountKind(comment.user.type),
    )
    if not actor.same_account(context.binding.assignment.actor):
        raise ValueError(_INVALID)
    return NativeReplyObservation(
        ref, actor, prose_digest(comment.body), GitHubEditEvidence(updated_at=comment.updated_at.isoformat()), placement
    )


def observe_native_reply(
    response: _native_gh.Response,
    context: GitHubPostingContext,
    creation: GitHubObjectAssociation,
    *,
    body: str | None = None,
) -> NativeReplyObservation:
    """Maintenance verifies the exact immutable native reply/root and current writer, never the root's creator."""
    if creation.review_comment is None:
        raise ValueError(_INVALID)
    observed = _observation(
        PullRequestReviewComment.model_validate_json(response.body),
        context,
        creation.object.container_number,
        creation.review_comment.in_reply_to_id,
        body=body,
    )
    if observed.object != creation.object or not observed.actor.same_account(creation.actor):
        raise ValueError(_INVALID)
    return observed


def _accepted(
    response: _native_gh.Response, request: GitHubReviewReplyRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    ref = None
    placement = None
    try:
        comment = PullRequestReviewComment.model_validate_json(response.body)
        ref = _reference(comment, context, request.pr_scope.container_number)
        placement = _placement(comment)
        observed = _observation(comment, context, request.pr_scope.container_number, request.root_id, body=body)
        association = GitHubObjectAssociation(
            object=ref,
            work_issue_number=context.target.issue_number,
            session_id=context.binding.session_id,
            role=context.binding.role,
            actor=observed.actor,
            source=NativeGitHubPostSource(),
            body_digest=observed.digest,
            edit_evidence=observed.evidence,
            review_comment=observed.placement,
        )
        return GitHubPostResult(
            acceptance=GitHubAcceptance.CONFIRMED,
            object=ref,
            association=association,
            body_digest=observed.digest,
            edit_evidence=observed.evidence,
            review_comment=observed.placement,
            provider_status=response.status,
        )
    except ValueError:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.CONFIRMED,
            object=ref,
            review_comment=placement,
            failure=GitHubPostFailure.RESULT_UNVERIFIED,
            provider_status=response.status,
        )


def _received(
    response: _native_gh.Response, request: GitHubReviewReplyRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    if not response.started or response.status in _REJECTIONS:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.NO_EFFECT,
            failure=GitHubPostFailure.PROVIDER_REFUSED if response.started else GitHubPostFailure.BINARY_UNAVAILABLE,
            provider_status=response.status,
            retry_after=response.retry_after,
        )
    if response.status == 201:
        return _accepted(response, request, context, body)
    return GitHubPostResult(
        acceptance=GitHubAcceptance.UNKNOWN,
        failure=GitHubPostFailure.SEND_UNCERTAIN,
        provider_status=response.status,
        retry_after=response.retry_after,
    )


async def _current(context: GitHubPostingContext, scope: GitHubObjectAssociation) -> bool:
    if await resolve_native_github_posting_context() != context:
        return False
    valid, current = await requested_pr_scope(context, scope.object)
    return valid and current is not None and current.same_creation(scope)


async def post_native_review_reply(
    context: GitHubPostingContext, request: GitHubReviewReplyRequest
) -> GitHubPostResult:
    """Read one explicit root and POST only its collected prose; uncertain acceptance is never replay advice."""
    refused = GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    valid, scope = await requested_pr_scope(context, request.pr_scope)
    if not valid or scope is None or request.target != context.target or not await _current(context, scope):
        return refused
    body = render_github_envelope(
        context.binding.role, context.binding.session_id, Act.NOTE, None, NativeGitHubPostSource(), request.body
    )
    payload = json.dumps({_BODY: body}, ensure_ascii=False).encode(_UTF8)
    environment = _native_gh.launch_environment()
    binary = _native_gh.gh_binary(environment)
    if binary is None:
        return refused.model_copy(update={_FAILURE: GitHubPostFailure.BINARY_UNAVAILABLE})
    repository = _SLASH.join(quote(part, safe=_EMPTY) for part in request.target.repository.split(_SLASH))
    root_endpoint = _COMMENT_ENDPOINT.format(repository=repository, identifier=request.root_id)
    endpoint = _REPLY_ENDPOINT.format(
        repository=repository, number=scope.object.container_number, identifier=request.root_id
    )
    response = None
    dispatching = False
    was_cancelled = False
    try:
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment, request.target, _PERMISSIONS
            )
            preflight = await preflight_pr_scope(context, scope, credential)
            if preflight is not None:
                return preflight
            environment = {
                **environment,
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            try:
                root_response = await _native_gh.send(
                    binary, root_endpoint, None, environment, directory, method=_native_gh.CommentMethod.GET
                )
            except _native_gh.SendCancelled as error:
                root_response = error.response
                was_cancelled = True
            refused = GitHubPostResult(
                acceptance=GitHubAcceptance.NO_EFFECT,
                failure=GitHubPostFailure.PREFLIGHT_FAILED,
                provider_status=root_response.status,
                retry_after=root_response.retry_after,
            )
            if root_response.status != 200:
                if was_cancelled:
                    raise asyncio.CancelledError
                return refused
            root = PullRequestReviewComment.model_validate_json(root_response.body)
            root_ref = _reference(root, context, scope.object.container_number)
            if root_ref.provider_id != request.root_id or root.in_reply_to_id is not UNSET:
                raise ValueError(_INVALID)
            if was_cancelled:
                raise asyncio.CancelledError
            if not await _current(context, scope):
                return refused.model_copy(update={_FAILURE: GitHubPostFailure.ADMISSION_REFUSED})
            # Establish uncertainty before awaiting the actual child, including generic settlement failures.
            dispatching = True
            try:
                response = await _native_gh.send(binary, endpoint, payload, environment, directory)
            except _native_gh.SendCancelled as error:
                response = error.response
                was_cancelled = True
    except GitHubCredentialRefused as error:
        return credential_result(error)
    except asyncio.CancelledError:
        was_cancelled = True
    except (OSError, ValueError, SQLAlchemyError):
        pass
    if not dispatching:
        if was_cancelled:
            raise cancelled(refused, context.binding.session_id)
        return refused
    result = _received(response if response is not None else _native_gh.Response(None), request, context, body)
    if was_cancelled:
        raise cancelled(result, context.binding.session_id)
    if result.association is not None:
        try:
            store = await get_db()
            association = await store.record_github_object_association(result.association, pr_scope=scope)
            result = result.model_copy(update={_ASSOCIATION: association})
        except asyncio.CancelledError:
            raise cancelled(result, context.binding.session_id) from None
        except (OSError, ValueError, SQLAlchemyError):
            result = result.model_copy(update={_ASSOCIATION: None, _FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
    logger.info(
        _LOG,
        result.acceptance,
        result.failure,
        context.binding.session_id,
        result.object.provider_id if result.object is not None else None,
        request.root_id,
    )
    return result
