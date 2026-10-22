"""Post an admitted issue comment through real gh and retain verified creation attribution."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, TextIO
from urllib.parse import quote

from githubkit_schemas.v2026_03_10.models import IssueComment
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import (
    AdmittedGitHubInvocation,
    GitHubPostingContext,
    LocalNativeGitHubInvocation,
    NativeHumanGitHubInvocation,
    RefusedGitHubInvocation,
    resolve_admitted_github_posting_context,
    resolve_native_github_posting_context,
)
from teleclaude.github import _native_gh
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.envelope import render_github_envelope
from teleclaude.github.native import (
    NativeCommentRefusal,
    NativeCommentRefused,
    prepare_native_comment_maintenance,
    prepare_native_issue_comment,
    prepare_native_issue_view,
)
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind
from teleclaude.types.github_binding import GitHubWorkTarget
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubCommentMaintenanceOperation,
    GitHubCommentMaintenanceResult,
    GitHubCommentMaintenanceStage,
    GitHubEditEvidence,
    GitHubIssueCommentDeleteRequest,
    GitHubIssueCommentEditRequest,
    GitHubIssueCommentRequest,
    GitHubObjectAssociation,
    GitHubObjectKind,
    GitHubObjectMutation,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
    NativeGitHubPostSource,
)
from teleclaude.types.workflow_record import Act

logger = get_logger(__name__)
_POST_EVENT = "github_comment_post acceptance=%s failure=%s session_id=%s provider_id=%s"
_CANCELLED_EVENT = (
    "github_comment_post_cancelled acceptance=%s failure=%s session_id=%s provider_id=%s provider_status=%s"
)
_CANCELLED_MESSAGE = "GitHub posting cancelled; available provider evidence is attached"
_UTF8 = "utf-8"
_EMPTY = ""
_GH_TOKEN = "GH_TOKEN"
_GH_CONFIG_DIR = "GH_CONFIG_DIR"
_FIXED_ENVIRONMENT = {
    "GH_HOST": "github.com",
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GH_PAGER": "",
}
_CONFIG_PREFIX = "teleclaude-gh-"
_BODY = "body"
_REPOSITORY_SEPARATOR = "/"
_COMMENT_ENDPOINT = "repos/{owner}/{repo}/issues/{number}/comments"
_COMMENT_OBJECT_ENDPOINT = "repos/{owner}/{repo}/issues/comments/{identifier}"
_ISSUE_URL = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"
_COMMENT_URL = "https://api.github.com/repos/{owner}/{repo}/issues/comments/{identifier}"
_DEFINITIVE_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_UNVERIFIED_OBJECT = "GitHub comment result could not be verified"
_ISSUE_COMMENT_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_ASSOCIATION = "association"
_FAILURE = "failure"
_HELP_FLAGS = frozenset({"--help", "-h"})
_HELP_ARGUMENT = "--help"
_HELP_COMMAND = "help"
_VERSION_ARGUMENTS = frozenset({("--version",), ("version",)})
_HELP_PATHS = frozenset(
    {
        (),
        ("issue",),
        ("issue", "view"),
        ("issue", "comment"),
        ("issue", "edit"),
        ("issue", "create"),
        ("issue", "close"),
        ("issue", "reopen"),
        ("issue", "delete"),
        ("pr",),
        ("pr", "view"),
        ("pr", "comment"),
        ("pr", "review"),
        ("pr", "create"),
        ("pr", "edit"),
        ("pr", "merge"),
        ("pr", "ready"),
        ("pr", "close"),
        ("api",),
        ("auth",),
        ("auth", "token"),
        ("auth", "status"),
        ("auth", "switch"),
    }
)
_ISSUE_VIEW = ("issue", "view")
_ISSUE_COMMENT = ("issue", "comment")
_ISSUE_READ_PERMISSIONS: AppPermissionsType = {"issues": "read"}
_EDITOR_ENVIRONMENT = ("GH_EDITOR", "VISUAL", "EDITOR")
_EDITOR_FILE = "comment.md"
_NATIVE_REFUSAL = "gh: platform invocation refused: "
_NATIVE_INCOMPLETE = "gh: platform operation incomplete: "
_NATIVE_UNAVAILABLE = "native execution unavailable"
_NATIVE_CONTEXT_CHANGED = "session scope changed"
_COMMENT_WEB_URL = "https://github.com/{repository}/issues/{number}#issuecomment-{identifier}"
_EXIT_REFUSED = 2
_API_COMMAND = "api"
_MUTATION = "mutation"
_STAGE = "stage"
_MUTATION_EVENT = (
    "github_comment_maintenance operation=%s stage=%s acceptance=%s failure=%s session_id=%s provider_id=%s"
)
_PROVIDER_STATUS = "provider_status"
_RETRY_DELAY = "retry_after"
_ACCEPTANCE = "acceptance"
_BODY_DIGEST = "body_digest"
_EDIT_EVIDENCE = "edit_evidence"
_PREFLIGHT_DIGEST = "preflight_digest"
_CREDENTIAL_REFUSAL = "credential_refusal"


class GitHubPostingCancelled(asyncio.CancelledError):
    """Propagate cancellation with safe provider evidence, without claiming unrecorded attribution."""

    def __init__(self, result: GitHubPostResult) -> None:
        super().__init__(_CANCELLED_MESSAGE)
        self.result = result


class GitHubMaintenanceCancelled(asyncio.CancelledError):
    """Cancellation retains the maintenance stage and safe effect evidence, never replay advice."""

    def __init__(self, result: GitHubCommentMaintenanceResult) -> None:
        super().__init__(_CANCELLED_MESSAGE)
        self.result = result


async def _current_context(context: GitHubPostingContext, target: GitHubWorkTarget, *, native: bool) -> bool:
    current: GitHubPostingContext | RefusedGitHubInvocation | LocalNativeGitHubInvocation | NativeHumanGitHubInvocation
    if isinstance(context.invocation, AdmittedGitHubInvocation):
        if native:
            return False
        current = await resolve_admitted_github_posting_context()
    else:
        current = await resolve_native_github_posting_context()
    return isinstance(current, GitHubPostingContext) and current == context and target == current.target


def _comment_reference(comment: IssueComment, target: GitHubWorkTarget) -> GitHubObjectRef:
    owner, repo = target.repository.split(_REPOSITORY_SEPARATOR)
    if (
        comment.id <= 0
        or comment.issue_url.casefold()
        != _ISSUE_URL.format(owner=owner, repo=repo, number=target.issue_number).casefold()
        or comment.url.casefold() != _COMMENT_URL.format(owner=owner, repo=repo, identifier=comment.id).casefold()
    ):
        raise ValueError(_UNVERIFIED_OBJECT)
    return GitHubObjectRef(
        repository_id=target.repository_id,
        container_number=target.issue_number,
        kind=GitHubObjectKind.ISSUE_COMMENT,
        provider_id=comment.id,
    )


def _comment_actor(comment: IssueComment) -> GitHubAccount:
    if comment.user is None:
        raise ValueError(_UNVERIFIED_OBJECT)
    return GitHubAccount(
        id=comment.user.id,
        node_id=comment.user.node_id,
        login=comment.user.login,
        type=GitHubAccountKind(comment.user.type),
    )


def _accepted(
    response: _native_gh.Response, request: GitHubIssueCommentRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    """Verify actual object, scope, body and stable author independently of the envelope's assertions."""
    ref = None
    digest = None
    evidence = None
    try:
        comment = IssueComment.model_validate_json(response.body)
        ref = _comment_reference(comment, request.target)
        if not isinstance(comment.body, str) or comment.body != body or comment.user is None:
            raise ValueError(_UNVERIFIED_OBJECT)
        digest = sha256(comment.body.encode(_UTF8)).hexdigest()
        evidence = GitHubEditEvidence(updated_at=comment.updated_at.isoformat())
        author = _comment_actor(comment)
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


def _provider_result(
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
    return _accepted(response, request, context, body)


def _cancelled(result: GitHubPostResult, session_id: str) -> GitHubPostingCancelled:
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


def _credential_result(error: GitHubCredentialRefused) -> GitHubPostResult:
    return GitHubPostResult(
        acceptance=GitHubAcceptance.NO_EFFECT,
        failure=GitHubPostFailure.CREDENTIAL_REFUSED,
        provider_status=error.rate_limit.status_code if error.rate_limit is not None else None,
        retry_after=error.rate_limit.retry_after if error.rate_limit is not None else None,
        credential_refusal=error.key_failure.value if error.key_failure is not None else error.reason.value,
    )


async def post_github_issue_comment(
    context: GitHubPostingContext, request: GitHubIssueCommentRequest
) -> GitHubPostResult:
    """Carry one finite owner-admitted append to verified durable attribution; never replay an uncertain send."""
    try:
        if not await _current_context(
            context, request.target, native=isinstance(request.source, NativeGitHubPostSource)
        ):
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
        body = render_github_envelope(
            context.binding.role, context.binding.session_id, request.act, request.phase, request.source, request.body
        )
        payload = json.dumps({_BODY: body}, ensure_ascii=False).encode(_UTF8)
        environment = _native_gh.launch_environment()
        binary = _native_gh.gh_binary(environment)
        if binary is None:
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.BINARY_UNAVAILABLE)
        owner, repo = request.target.repository.split(_REPOSITORY_SEPARATOR)
        endpoint = _COMMENT_ENDPOINT.format(
            owner=quote(owner, safe=_EMPTY), repo=quote(repo, safe=_EMPTY), number=request.target.issue_number
        )
    except (OSError, ValueError, SQLAlchemyError):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    response: _native_gh.Response | None = None
    cancelled = False
    try:
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment, request.target, _ISSUE_COMMENT_PERMISSIONS
            )
            if not await _current_context(
                context, request.target, native=isinstance(request.source, NativeGitHubPostSource)
            ):
                return GitHubPostResult(
                    acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED
                )
            child_environment = {
                **environment,
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            try:
                response = await _native_gh.send(binary, endpoint, payload, child_environment, directory)
            except _native_gh.SendCancelled as error:
                response = error.response
                cancelled = True
            except OSError:
                # Failure while settling an already-started child leaves acceptance unknown.
                response = _native_gh.Response(None)
    except GitHubCredentialRefused as error:
        return _credential_result(error)
    except (OSError, ValueError, SQLAlchemyError):
        if response is None:
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
        # A cleanup failure after a received response cannot undo its provider acceptance or cancellation.
    result = _provider_result(response, request, context, body)
    if cancelled:
        raise _cancelled(result, context.binding.session_id)
    if result.acceptance is not GitHubAcceptance.CONFIRMED:
        return result
    if result.association is not None:
        try:
            store = await get_db()
            recorded = await store.record_github_object_association(result.association)
            result = result.model_copy(update={_ASSOCIATION: recorded})
        except (SQLAlchemyError, OSError, ValueError):
            result = result.model_copy(update={_ASSOCIATION: None, _FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
        except asyncio.CancelledError:
            raise _cancelled(result, context.binding.session_id) from None
    logger.info(
        _POST_EVENT,
        result.acceptance,
        result.failure,
        context.binding.session_id,
        result.object.provider_id if result.object is not None else None,
    )
    return result


async def post_admitted_github_issue_comment(request: GitHubIssueCommentRequest) -> GitHubPostResult:
    """Post an owner-admitted sealed/reflected append as the current local command's durably assigned actor."""
    if isinstance(request.source, NativeGitHubPostSource):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    context = await resolve_admitted_github_posting_context()
    if not isinstance(context, GitHubPostingContext):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    return await post_github_issue_comment(context, request)


async def post_native_issue_comment(
    arguments: Sequence[str], *, directory: Path, stdin: BinaryIO, editor: Callable[[], str] | None = None
) -> GitHubPostResult:
    """Resolve managed execution, admit/collect native prose, and execute the same complete finite posting path."""
    context = await resolve_native_github_posting_context()
    if not isinstance(context, GitHubPostingContext):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    try:
        return await _post_native_comment(context, arguments, directory=directory, stdin=stdin, editor=editor)
    except (NativeCommentRefused, ValueError):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)


async def _post_native_comment(
    context: GitHubPostingContext,
    arguments: Sequence[str],
    *,
    directory: Path,
    stdin: BinaryIO,
    editor: Callable[[], str] | None,
) -> GitHubPostResult:
    native = prepare_native_issue_comment(arguments, context, directory=directory, stdin=stdin, editor=editor)
    request = GitHubIssueCommentRequest(target=context.target, body=native.body, act=Act.NOTE, source=native.source)
    return await post_github_issue_comment(context, request)


async def _native_creator(context: GitHubPostingContext, ref: GitHubObjectRef) -> GitHubObjectAssociation | None:
    store = await get_db()
    creation = await store.get_github_object_association(ref)
    if (
        creation is None
        or not isinstance(creation.source, NativeGitHubPostSource)
        or creation.object != ref
        or creation.session_id != context.binding.session_id
        or creation.role is not context.binding.role
        or not creation.actor.same_account(context.binding.assignment.actor)
        or creation.work_issue_number != context.target.issue_number
        or ref.repository_id != context.target.repository_id
        or ref.container_number != context.target.issue_number
        or ref.kind is not GitHubObjectKind.ISSUE_COMMENT
    ):
        return None
    return creation


def _maintenance_observation(
    response: _native_gh.Response,
    request: GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest,
    creation: GitHubObjectAssociation,
    *,
    body: str | None = None,
) -> tuple[str, GitHubEditEvidence, GitHubAccount]:
    comment = IssueComment.model_validate_json(response.body)
    ref = _comment_reference(comment, request.target)
    actor = _comment_actor(comment)
    if (
        ref != request.object
        or not actor.same_account(creation.actor)
        or not isinstance(comment.body, str)
        or (body is not None and comment.body != body)
    ):
        raise ValueError(_UNVERIFIED_OBJECT)
    return (
        sha256(comment.body.encode(_UTF8)).hexdigest(),
        GitHubEditEvidence(updated_at=comment.updated_at.isoformat()),
        actor,
    )


def _maintenance_response(
    response: _native_gh.Response,
    result: GitHubCommentMaintenanceResult,
    request: GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest,
    creation: GitHubObjectAssociation,
    context: GitHubPostingContext,
    body: str | None,
) -> tuple[GitHubCommentMaintenanceResult, GitHubObjectMutation | None]:
    result = result.model_copy(update={_PROVIDER_STATUS: response.status, _RETRY_DELAY: response.retry_after})
    if not response.started:
        return result.model_copy(
            update={_ACCEPTANCE: GitHubAcceptance.NO_EFFECT, _FAILURE: GitHubPostFailure.BINARY_UNAVAILABLE}
        ), None
    if response.status in _DEFINITIVE_REJECTIONS:
        return result.model_copy(
            update={_ACCEPTANCE: GitHubAcceptance.NO_EFFECT, _FAILURE: GitHubPostFailure.PROVIDER_REFUSED}
        ), None
    expected = 200 if result.operation is GitHubCommentMaintenanceOperation.EDIT else 204
    if response.status != expected:
        return result, None
    result = result.model_copy(update={_ACCEPTANCE: GitHubAcceptance.CONFIRMED, _FAILURE: None})
    digest = None
    evidence = None
    actor = context.binding.assignment.actor
    if result.operation is GitHubCommentMaintenanceOperation.EDIT:
        try:
            digest, evidence, actor = _maintenance_observation(response, request, creation, body=body)
        except ValueError:
            return result.model_copy(update={_FAILURE: GitHubPostFailure.RESULT_UNVERIFIED}), None
    result = result.model_copy(update={_BODY_DIGEST: digest, _EDIT_EVIDENCE: evidence})
    if result.preflight_digest is None:
        return result.model_copy(update={_FAILURE: GitHubPostFailure.RESULT_UNVERIFIED}), None
    try:
        mutation = GitHubObjectMutation(
            object=request.object,
            operation=result.operation,
            session_id=context.binding.session_id,
            role=context.binding.role,
            actor=actor,
            observed_at=datetime.now(UTC),
            provider_status=expected,
            preflight_digest=result.preflight_digest,
            body_digest=digest,
            edit_evidence=evidence,
        )
    except ValueError:
        return result.model_copy(update={_FAILURE: GitHubPostFailure.RESULT_UNVERIFIED}), None
    return result, mutation


async def _maintenance_exchange(
    context: GitHubPostingContext,
    request: GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest,
    creation: GitHubObjectAssociation,
    binary: Path,
    endpoint: str,
    body: str | None,
    payload: bytes | None,
    directory: str,
    environment: Mapping[str, str],
    result: GitHubCommentMaintenanceResult,
) -> tuple[GitHubCommentMaintenanceResult, GitHubObjectMutation | None, bool]:
    """Keep the read and effect stages separate, even while settling a cancelled child."""
    cancelled = False
    try:
        if (
            not await _current_context(context, request.target, native=True)
            or await _native_creator(context, request.object) != creation
        ):
            return result, None, False
        result = result.model_copy(
            update={_STAGE: GitHubCommentMaintenanceStage.PREFLIGHT, _FAILURE: GitHubPostFailure.PREFLIGHT_FAILED}
        )
        try:
            response = await _native_gh.send(
                binary, endpoint, None, environment, directory, method=_native_gh.CommentMethod.GET
            )
        except _native_gh.SendCancelled as error:
            response = error.response
            cancelled = True
        result = result.model_copy(update={_PROVIDER_STATUS: response.status, _RETRY_DELAY: response.retry_after})
        if response.status != 200:
            return result, None, cancelled
        digest, evidence, _actor = _maintenance_observation(response, request, creation)
        result = result.model_copy(update={_PREFLIGHT_DIGEST: digest, _EDIT_EVIDENCE: evidence})
        if cancelled:
            return result.model_copy(update={_FAILURE: GitHubPostFailure.CANCELLED}), None, True
        if (
            not await _current_context(context, request.target, native=True)
            or await _native_creator(context, request.object) != creation
        ):
            return result.model_copy(update={_FAILURE: GitHubPostFailure.ADMISSION_REFUSED}), None, False
        result = result.model_copy(
            update={
                _STAGE: GitHubCommentMaintenanceStage.MUTATION,
                _ACCEPTANCE: GitHubAcceptance.UNKNOWN,
                _FAILURE: GitHubPostFailure.SEND_UNCERTAIN,
                _PROVIDER_STATUS: None,
                _RETRY_DELAY: None,
                _EDIT_EVIDENCE: None,
            }
        )
        method = (
            _native_gh.CommentMethod.PATCH
            if isinstance(request, GitHubIssueCommentEditRequest)
            else _native_gh.CommentMethod.DELETE
        )
        try:
            response = await _native_gh.send(binary, endpoint, payload, environment, directory, method=method)
        except _native_gh.SendCancelled as error:
            response = error.response
            cancelled = True
        result, mutation = _maintenance_response(response, result, request, creation, context, body)
        return result, mutation, cancelled
    except asyncio.CancelledError:
        failure = (
            GitHubPostFailure.CANCELLED
            if result.acceptance is GitHubAcceptance.NO_EFFECT
            else GitHubPostFailure.SEND_UNCERTAIN
        )
        return result.model_copy(update={_FAILURE: failure}), None, True
    except (OSError, ValueError, SQLAlchemyError):
        return result, None, cancelled


def _maintenance_cancelled(result: GitHubCommentMaintenanceResult, session_id: str) -> GitHubMaintenanceCancelled:
    if result.acceptance is GitHubAcceptance.CONFIRMED and result.failure is None:
        result = result.model_copy(update={_FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
    logger.warning(
        _MUTATION_EVENT,
        result.operation,
        result.stage,
        result.acceptance,
        result.failure,
        session_id,
        result.object.provider_id,
    )
    return GitHubMaintenanceCancelled(result)


async def _maintain_native_comment(
    context: GitHubPostingContext, request: GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest
) -> GitHubCommentMaintenanceResult:
    operation = (
        GitHubCommentMaintenanceOperation.EDIT
        if isinstance(request, GitHubIssueCommentEditRequest)
        else GitHubCommentMaintenanceOperation.DELETE
    )
    result = GitHubCommentMaintenanceResult(
        operation=operation,
        object=request.object,
        stage=GitHubCommentMaintenanceStage.ADMISSION,
        acceptance=GitHubAcceptance.NO_EFFECT,
        failure=GitHubPostFailure.ADMISSION_REFUSED,
    )
    mutation = None
    cancelled = False
    creation = None
    try:
        if not await _current_context(context, request.target, native=True):
            return result
        creation = await _native_creator(context, request.object)
        if creation is None:
            return result
        body = (
            render_github_envelope(
                context.binding.role, context.binding.session_id, Act.NOTE, None, NativeGitHubPostSource(), request.body
            )
            if isinstance(request, GitHubIssueCommentEditRequest)
            else None
        )
        payload = json.dumps({_BODY: body}, ensure_ascii=False).encode(_UTF8) if body is not None else None
        environment = _native_gh.launch_environment()
        binary = _native_gh.gh_binary(environment)
        if binary is None:
            return result.model_copy(update={_FAILURE: GitHubPostFailure.BINARY_UNAVAILABLE})
        owner, repo = request.target.repository.split(_REPOSITORY_SEPARATOR)
        endpoint = _COMMENT_OBJECT_ENDPOINT.format(
            owner=quote(owner, safe=_EMPTY), repo=quote(repo, safe=_EMPTY), identifier=request.object.provider_id
        )
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment, request.target, _ISSUE_COMMENT_PERMISSIONS
            )
            environment = {
                **environment,
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            result, mutation, cancelled = await _maintenance_exchange(
                context, request, creation, binary, endpoint, body, payload, directory, environment, result
            )
    except GitHubCredentialRefused as error:
        refused = _credential_result(error)
        return result.model_copy(
            update={
                _FAILURE: refused.failure,
                _PROVIDER_STATUS: refused.provider_status,
                _RETRY_DELAY: refused.retry_after,
                _CREDENTIAL_REFUSAL: refused.credential_refusal,
            }
        )
    except asyncio.CancelledError:
        cancelled = True
        result = result.model_copy(update={_FAILURE: GitHubPostFailure.CANCELLED})
    except (OSError, ValueError, SQLAlchemyError):
        # Cleanup cannot turn a received mutation response into no-effect or erase cancellation.
        pass
    if cancelled:
        raise _maintenance_cancelled(result, context.binding.session_id)
    if mutation is not None and creation is not None:
        result = result.model_copy(update={_STAGE: GitHubCommentMaintenanceStage.ATTRIBUTION})
        try:
            store = await get_db()
            recorded = await store.record_github_object_mutation(mutation, creation=creation)
            result = result.model_copy(update={_MUTATION: recorded})
        except asyncio.CancelledError:
            raise _maintenance_cancelled(result, context.binding.session_id) from None
        except (OSError, ValueError, SQLAlchemyError):
            result = result.model_copy(update={_FAILURE: GitHubPostFailure.ASSOCIATION_FAILED})
    logger.info(
        _MUTATION_EVENT,
        result.operation,
        result.stage,
        result.acceptance,
        result.failure,
        context.binding.session_id,
        result.object.provider_id,
    )
    return result


def _help_arguments(arguments: tuple[str, ...]) -> tuple[str, ...] | None:
    if not arguments or arguments == (_HELP_COMMAND,):
        return (_HELP_ARGUMENT,)
    if arguments in _VERSION_ARGUMENTS:
        return arguments
    if arguments[-1] in _HELP_FLAGS and arguments[:-1] in _HELP_PATHS:
        return (*arguments[:-1], _HELP_ARGUMENT)
    return None


def _editor_body(directory: Path) -> str:
    """Collect opaque prose before issuance; editor selection never reaches a credential-bearing child."""
    selected = next(
        (
            value
            for name in _EDITOR_ENVIRONMENT
            if (value := os.environ.get(name))  # guard: direct-env-read - pre-credential editor selection
        ),
        None,
    )
    if selected is None:
        raise NativeCommentRefused(NativeCommentRefusal.EDITOR_UNAVAILABLE)
    try:
        command = shlex.split(selected)
        if not command:
            raise NativeCommentRefused(NativeCommentRefusal.EDITOR_UNAVAILABLE)
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as temporary:
            body_path = Path(temporary) / _EDITOR_FILE
            body_path.touch(mode=0o600, exist_ok=False)
            completed = subprocess.run(
                (*command, str(body_path)), cwd=directory, env=_native_gh.launch_environment(), check=False
            )
            if completed.returncode != 0:
                raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE)
            return body_path.read_bytes().decode(_UTF8)
    except NativeCommentRefused:
        raise
    except (OSError, ValueError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None


def _native_failure(reason: str, stderr: TextIO) -> int:
    print(_NATIVE_REFUSAL + reason, file=stderr)
    return _EXIT_REFUSED


def _native_result(result: GitHubPostResult, context: GitHubPostingContext, stdout: TextIO, stderr: TextIO) -> int:
    if result.attributed and result.object is not None:
        print(
            _COMMENT_WEB_URL.format(
                repository=context.target.repository,
                number=result.object.container_number,
                identifier=result.object.provider_id,
            ),
            file=stdout,
        )
        return 0
    print(_NATIVE_INCOMPLETE + result.model_dump_json(), file=stderr)
    return _EXIT_REFUSED


def _native_maintenance_result(result: GitHubCommentMaintenanceResult, stdout: TextIO, stderr: TextIO) -> int:
    if result.attributed:
        print(result.model_dump_json(), file=stdout)
        return 0
    print(_NATIVE_INCOMPLETE + result.model_dump_json(), file=stderr)
    return _EXIT_REFUSED


async def _native_view(
    context: GitHubPostingContext,
    binary: Path,
    arguments: tuple[str, ...],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    admitted = prepare_native_issue_view(arguments, context)
    if not await _current_context(context, context.target, native=True):
        return _native_failure(_NATIVE_CONTEXT_CHANGED, stderr)
    try:
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment, context.target, _ISSUE_READ_PERMISSIONS
            )
            if not await _current_context(context, context.target, native=True):
                return _native_failure(_NATIVE_CONTEXT_CHANGED, stderr)
            environment = {
                **_native_gh.launch_environment(),
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            return await _native_gh.native_read_process(binary, admitted, directory, environment, stdout, stderr)
    except GitHubCredentialRefused as error:
        return _native_result(_credential_result(error), context, stdout, stderr)


async def execute_native_github(
    arguments: Sequence[str], *, directory: Path, stdin: BinaryIO, stdout: TextIO, stderr: TextIO
) -> int:
    """Serve the native entry with exact disclosure-free help, observed scope and finite bound handlers."""
    arguments = tuple(arguments)
    try:
        environment = _native_gh.launch_environment()
        binary = _native_gh.gh_binary(environment)
        if binary is None:
            return _native_failure(_NATIVE_UNAVAILABLE, stderr)
        help_arguments = _help_arguments(arguments)
        if help_arguments is not None:
            with TemporaryDirectory(prefix=_CONFIG_PREFIX) as temporary:
                return await _native_gh.native_read_process(
                    binary,
                    help_arguments,
                    temporary,
                    {**environment, **_FIXED_ENVIRONMENT, _GH_CONFIG_DIR: temporary},
                    stdout,
                    stderr,
                )
        context = await resolve_native_github_posting_context()
        if isinstance(context, RefusedGitHubInvocation):
            return _native_failure(context.reason.value, stderr)
        if isinstance(context, (NativeHumanGitHubInvocation, LocalNativeGitHubInvocation)):
            current = await resolve_native_github_posting_context()
            if current != context:
                return _native_failure(_NATIVE_CONTEXT_CHANGED, stderr)
            original = dict(os.environ)  # guard: direct-env-read - preserve native pass-through startup environment
            os.chdir(directory)
            os.execve(str(binary), (str(binary), *arguments), original)
        if arguments[:1] == (_API_COMMAND,):
            request = prepare_native_comment_maintenance(arguments, context, directory=directory, stdin=stdin)
            try:
                maintained = await _maintain_native_comment(context, request)
            except GitHubMaintenanceCancelled as error:
                _native_maintenance_result(error.result, stdout, stderr)
                raise
            return _native_maintenance_result(maintained, stdout, stderr)
        if arguments[:2] == _ISSUE_VIEW:
            return await _native_view(context, binary, arguments, stdout, stderr)
        if arguments[:2] != _ISSUE_COMMENT:
            return _native_failure(NativeCommentRefusal.UNSUPPORTED_OPERATION.value, stderr)
        try:
            result = await _post_native_comment(
                context, arguments, directory=directory, stdin=stdin, editor=lambda: _editor_body(directory)
            )
        except GitHubPostingCancelled as error:
            _native_result(error.result, context, stdout, stderr)
            raise
        return _native_result(result, context, stdout, stderr)
    except NativeCommentRefused as error:
        return _native_failure(error.reason.value, stderr)
    except (OSError, ValueError, SQLAlchemyError, TimeoutError):
        return _native_failure(_NATIVE_UNAVAILABLE, stderr)
