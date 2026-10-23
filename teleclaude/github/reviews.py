"""Execute native COMMENT reviews and creator-owned body edits with immutable reviewed-commit attribution."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote

from githubkit.auth.token import TokenAuthStrategy
from githubkit.cache.mem_cache import MemCacheStrategy
from githubkit.exception import GitHubException, RateLimitExceeded, RequestFailed
from githubkit_schemas.v2026_03_10.models import PullRequestReview
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from httpx import HTTPError
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import GitHubPostingContext, resolve_native_github_posting_context
from teleclaude.github._comment_results import CommentResponse, credential_result
from teleclaude.github._conversation_scope import requested_pr_scope, resolve_native_review
from teleclaude.github._pr_provider import pr_reader, prose_digest, verify_pr_membership
from teleclaude.github.accounts import GitHubRateLimitFacts
from teleclaude.github.client import create_github_client
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.envelope import render_github_envelope
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubCommentMaintenanceOperation,
    GitHubCommentMaintenanceResult,
    GitHubCommentMaintenanceStage,
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectMutation,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
    GitHubReviewEditRequest,
    GitHubReviewRequest,
    NativeGitHubPostSource,
)
from teleclaude.types.workflow_record import Act

logger = get_logger(__name__)
_EMPTY = ""
_SLASH = "/"
_COMMENT: Final = "COMMENT"
_REQUEST_SECONDS = 60.0
_COMMENTED = "COMMENTED"
_SHA = re.compile(r"[0-9a-f]{40}")
_PR_URL = "https://api.github.com/repos/{repository}/pulls/{number}"
_REVIEW_URL = "https://github.com/{repository}/pull/{number}#pullrequestreview-{identifier}"
_INVALID = "Review response does not establish exact scope, writer, COMMENT event and reviewed commit"
_CANCELLED = "Native review cancelled; available provider evidence is attached"
_LOG = "github_native_review stage=%s acceptance=%s failure=%s session_id=%s provider_id=%s reviewed_sha=%s"
_PERMISSIONS: AppPermissionsType = {"pull_requests": "write"}
_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_ACCEPTANCE = "acceptance"
_FAILURE = "failure"
_STATUS = "provider_status"
_DELAY = "retry_after"
_ASSOCIATION = "association"
_OBJECT = "object"
_REVIEWED_SHA = "reviewed_sha"
_BODY_DIGEST = "body_digest"


class GitHubReviewCancelled(asyncio.CancelledError):
    """Keep cancellation separate from acceptance and unrecorded result attribution."""

    def __init__(self, result: GitHubPostResult | GitHubCommentMaintenanceResult) -> None:
        super().__init__(_CANCELLED)
        self.result = result


@dataclass
class _ReviewRun:
    """Private state of one finite review exchange, including its dispatch boundary."""

    context: GitHubPostingContext
    request: GitHubReviewRequest
    scope: GitHubObjectAssociation
    body: str
    result: GitHubPostResult
    creation: GitHubObjectAssociation | None = None
    stage: GitHubCommentMaintenanceStage = GitHubCommentMaintenanceStage.ADMISSION
    preflight_digest: str | None = None
    mutation: GitHubObjectMutation | None = None
    cancelled: bool = False


async def _authority_current(run: _ReviewRun) -> bool:
    context, request = run.context, run.request
    if request.target != context.target or await resolve_native_github_posting_context() != context:
        return False
    valid, scope = await requested_pr_scope(context, request.pr_scope)
    if not valid or scope is None or not scope.same_creation(run.scope):
        return False
    if isinstance(request, GitHubReviewEditRequest):
        resolved = await resolve_native_review(context, request.object.provider_id)
        if resolved is None or resolved[0] != run.creation or resolved[1] != scope:
            return False
    return True


def _observe(
    response: CommentResponse, run: _ReviewRun, *, body: str | None = None, reviewed_sha: str
) -> tuple[GitHubObjectRef, GitHubAccount, str, str]:
    review = PullRequestReview.model_validate_json(response.body)
    repository, number = run.request.target.repository, run.scope.object.container_number
    if (
        review.id <= 0
        or review.pull_request_url.casefold() != _PR_URL.format(repository=repository, number=number).casefold()
        or review.html_url.casefold()
        != _REVIEW_URL.format(repository=repository, number=number, identifier=review.id).casefold()
    ):
        raise ValueError(_INVALID)
    ref = GitHubObjectRef(
        repository_id=run.request.target.repository_id,
        container_number=number,
        kind=GitHubObjectKind.REVIEW,
        provider_id=review.id,
    )
    # Retain verified object/commit observations even when the rest of the response fails verification.
    actual_sha = review.commit_id
    run.result = run.result.model_copy(update={_OBJECT: ref})
    if actual_sha is not None and _SHA.fullmatch(actual_sha):
        run.result = run.result.model_copy(update={_REVIEWED_SHA: actual_sha})
    if (
        review.user is None
        or review.state != _COMMENTED
        or not isinstance(review.submitted_at, datetime)
        or review.submitted_at.utcoffset() is None
        or actual_sha != reviewed_sha
        or (body is not None and review.body != body)
        or (isinstance(run.request, GitHubReviewEditRequest) and ref != run.request.object)
    ):
        raise ValueError(_INVALID)
    actor = GitHubAccount(
        id=review.user.id,
        node_id=review.user.node_id,
        login=review.user.login,
        type=GitHubAccountKind(review.user.type),
    )
    if not actor.same_account(run.context.binding.assignment.actor):
        raise ValueError(_INVALID)
    return ref, actor, prose_digest(review.body), reviewed_sha


def _received(run: _ReviewRun, response: CommentResponse, reviewed_sha: str) -> None:
    run.result = run.result.model_copy(update={_STATUS: response.status, _DELAY: response.retry_after})
    if not response.started or response.status in _REJECTIONS:
        run.result = run.result.model_copy(
            update={
                _ACCEPTANCE: GitHubAcceptance.NO_EFFECT,
                _FAILURE: GitHubPostFailure.PROVIDER_REFUSED
                if response.started
                else GitHubPostFailure.ADMISSION_REFUSED,
            }
        )
        return
    if response.status != 200:
        return
    run.result = run.result.model_copy(
        update={
            _ACCEPTANCE: GitHubAcceptance.CONFIRMED,
            _FAILURE: GitHubPostFailure.RESULT_UNVERIFIED,
        }
    )
    ref, actor, digest, actual_sha = _observe(response, run, body=run.body, reviewed_sha=reviewed_sha)
    run.result = run.result.model_copy(update={_BODY_DIGEST: digest})
    context = run.context
    if isinstance(run.request, GitHubReviewEditRequest):
        if run.preflight_digest is None:
            raise ValueError(_INVALID)
        run.mutation = GitHubObjectMutation(
            object=ref,
            operation=GitHubCommentMaintenanceOperation.EDIT,
            session_id=context.binding.session_id,
            role=context.binding.role,
            actor=actor,
            observed_at=datetime.now(UTC),
            provider_status=200,
            preflight_digest=run.preflight_digest,
            body_digest=digest,
            reviewed_sha=actual_sha,
        )
    else:
        association = GitHubObjectAssociation(
            object=ref,
            work_issue_number=context.target.issue_number,
            session_id=context.binding.session_id,
            role=context.binding.role,
            actor=actor,
            source=NativeGitHubPostSource(),
            body_digest=digest,
            reviewed_sha=actual_sha,
        )
        run.result = run.result.model_copy(update={_ASSOCIATION: association})
    run.result = run.result.model_copy(update={_FAILURE: None})


def _provider_error(run: _ReviewRun, error: Exception) -> None:
    """Keep safe SDK recovery facts without replacing an already observed response."""
    if run.result.provider_status is not None:
        return
    if isinstance(error, RateLimitExceeded):
        facts = GitHubRateLimitFacts.from_sdk(error)
        run.result = run.result.model_copy(update={_STATUS: facts.status_code, _DELAY: facts.retry_after})
    elif isinstance(error, RequestFailed):
        run.result = run.result.model_copy(update={_STATUS: error.response.status_code})


async def _exchange(run: _ReviewRun) -> None:
    """Execute fixed SDK review GET/COMMENT POST/body-only PUT, keeping evidence before cleanup."""
    context, request = run.context, run.request
    if not await _authority_current(run):
        return
    credential = await issue_github_installation_credential(context.binding.assignment, request.target, _PERMISSIONS)
    if not await _authority_current(run):
        return
    run.stage = GitHubCommentMaintenanceStage.PREFLIGHT
    run.result = run.result.model_copy(update={_FAILURE: GitHubPostFailure.PREFLIGHT_FAILED})
    async with pr_reader(credential) as (reader, client):
        pr = await reader.get(client, request.pr_scope.container_number)
        verify_pr_membership(pr, context, run.scope)
    # Creation explicitly reviews the observed provider head; later edits retain the original reviewed SHA.
    reviewed_sha = run.creation.reviewed_sha if run.creation is not None else pr.head.sha
    if reviewed_sha is None or _SHA.fullmatch(reviewed_sha) is None:
        raise ValueError(_INVALID)
    owner, repo = (quote(part, safe=_EMPTY) for part in credential.target.repository.split(_SLASH))
    number = request.pr_scope.container_number
    cache = MemCacheStrategy()
    try:
        async with create_github_client(TokenAuthStrategy(credential.token.get_secret_value()), cache) as client:
            if isinstance(request, GitHubReviewEditRequest):
                async with asyncio.timeout(_REQUEST_SECONDS):
                    received = await client.rest.pulls.async_get_review(owner, repo, number, request.object.provider_id)
                response = CommentResponse(received.status_code, received.content)
                run.result = run.result.model_copy(update={_STATUS: response.status, _DELAY: response.retry_after})
                if response.status != 200:
                    return
                _, _, run.preflight_digest, _ = _observe(response, run, reviewed_sha=reviewed_sha)
            if not await _authority_current(run):
                run.result = run.result.model_copy(update={_FAILURE: GitHubPostFailure.ADMISSION_REFUSED})
                return
            run.stage = GitHubCommentMaintenanceStage.MUTATION
            run.result = run.result.model_copy(
                update={
                    _ACCEPTANCE: GitHubAcceptance.UNKNOWN,
                    _FAILURE: GitHubPostFailure.SEND_UNCERTAIN,
                    _STATUS: None,
                    _DELAY: None,
                }
            )
            try:
                async with asyncio.timeout(_REQUEST_SECONDS):
                    if isinstance(request, GitHubReviewEditRequest):
                        received = await client.rest.pulls.async_update_review(
                            owner, repo, number, request.object.provider_id, body=run.body
                        )
                    else:
                        received = await client.rest.pulls.async_create_review(
                            owner, repo, number, body=run.body, event=_COMMENT, commit_id=reviewed_sha
                        )
                response = CommentResponse(received.status_code, received.content)
            except RequestFailed as error:
                facts = GitHubRateLimitFacts.from_sdk(error) if isinstance(error, RateLimitExceeded) else None
                response = CommentResponse(
                    error.response.status_code,
                    error.response.content,
                    retry_after=facts.retry_after if facts is not None else None,
                )
            # Verify known mutation evidence before either resource cleanup can fail or be cancelled.
            _received(run, response, reviewed_sha)
    except asyncio.CancelledError:
        run.cancelled = True
    except (GitHubException, HTTPError, OSError, ValueError, TimeoutError) as error:
        _provider_error(run, error)
    finally:
        try:
            await cache.acleanup()
        except asyncio.CancelledError:
            run.cancelled = True
        except (GitHubException, HTTPError, OSError, ValueError, TimeoutError) as error:
            _provider_error(run, error)


def _result(run: _ReviewRun) -> GitHubPostResult | GitHubCommentMaintenanceResult:
    if not isinstance(run.request, GitHubReviewEditRequest):
        return run.result
    return GitHubCommentMaintenanceResult(
        operation=GitHubCommentMaintenanceOperation.EDIT,
        object=run.request.object,
        stage=run.stage,
        acceptance=run.result.acceptance,
        failure=run.result.failure,
        mutation=run.mutation,
        preflight_digest=run.preflight_digest,
        body_digest=run.result.body_digest,
        reviewed_sha=run.result.reviewed_sha,
        provider_status=run.result.provider_status,
        retry_after=run.result.retry_after,
        credential_refusal=run.result.credential_refusal,
    )


def _cancel(run: _ReviewRun) -> GitHubReviewCancelled:
    # Recovered acceptance is evidence, but cancellation never claims an uncompleted durable append.
    if run.result.acceptance is GitHubAcceptance.CONFIRMED and run.result.failure is None:
        run.result = run.result.model_copy(update={_ASSOCIATION: None, _FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
    elif run.result.acceptance is GitHubAcceptance.NO_EFFECT:
        run.result = run.result.model_copy(update={_FAILURE: GitHubPostFailure.CANCELLED})
    run.mutation = None
    _log(run)
    return GitHubReviewCancelled(_result(run))


def _log(run: _ReviewRun) -> None:
    logger.info(
        _LOG,
        run.stage,
        run.result.acceptance,
        run.result.failure,
        run.context.binding.session_id,
        run.result.object.provider_id if run.result.object is not None else None,
        run.result.reviewed_sha,
    )


async def execute_native_review(
    context: GitHubPostingContext, request: GitHubReviewRequest
) -> GitHubPostResult | GitHubCommentMaintenanceResult:
    """Complete one finite native review operation through durable creation or separate later edit attribution."""
    initial = GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    valid, scope = await requested_pr_scope(context, request.pr_scope)
    if not valid or scope is None:
        return initial
    body = render_github_envelope(
        context.binding.role, context.binding.session_id, Act.NOTE, None, NativeGitHubPostSource(), request.body
    )
    run = _ReviewRun(context, request, scope, body, initial)
    try:
        if isinstance(request, GitHubReviewEditRequest):
            resolved = await resolve_native_review(context, request.object.provider_id)
            if resolved is None or resolved[0].object != request.object or resolved[1] != scope:
                return _result(run)
            run.creation = resolved[0]
        await _exchange(run)
    except GitHubCredentialRefused as error:
        run.result = credential_result(error)
    except asyncio.CancelledError:
        run.cancelled = True
    except (GitHubException, HTTPError, OSError, ValueError, SQLAlchemyError, TimeoutError) as error:
        _provider_error(run, error)
    if run.cancelled:
        raise _cancel(run)
    if run.result.acceptance is GitHubAcceptance.CONFIRMED and run.result.failure is None:
        run.stage = GitHubCommentMaintenanceStage.ATTRIBUTION
        try:
            store = await get_db()
            if run.mutation is not None and run.creation is not None:
                run.mutation = await store.record_github_object_mutation(
                    run.mutation, creation=run.creation, pr_scope=scope
                )
            elif run.result.association is not None:
                association = await store.record_github_object_association(run.result.association, pr_scope=scope)
                run.result = run.result.model_copy(update={_ASSOCIATION: association})
        except asyncio.CancelledError:
            raise _cancel(run) from None
        except (OSError, ValueError, SQLAlchemyError):
            run.mutation = None
            run.result = run.result.model_copy(
                update={_ASSOCIATION: None, _FAILURE: GitHubPostFailure.ASSOCIATION_FAILED}
            )
    _log(run)
    return _result(run)
