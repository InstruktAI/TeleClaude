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
from teleclaude.github._comment_results import (
    GitHubPostingCancelled,
)
from teleclaude.github._comment_results import (
    cancelled as _cancelled,
)
from teleclaude.github._comment_results import (
    comment_actor as _comment_actor,
)
from teleclaude.github._comment_results import (
    comment_reference as _comment_reference,
)
from teleclaude.github._comment_results import (
    credential_result as _credential_result,
)
from teleclaude.github._comment_results import (
    provider_result as _provider_result,
)
from teleclaude.github._conversation_scope import preflight_pr_scope, requested_pr_scope, resolve_native_comment
from teleclaude.github._native_pr import prepare_native_pull_request
from teleclaude.github.credentials import (
    GitHubCredentialRefused,
    GitHubInstallationCredential,
    issue_github_installation_credential,
)
from teleclaude.github.envelope import render_github_envelope
from teleclaude.github.native import (
    NativeCommentRefusal,
    NativeCommentRefused,
    prepare_native_comment_maintenance,
    prepare_native_issue_comment,
    prepare_native_issue_view,
    prepare_native_review,
)
from teleclaude.github.pull_requests import GitHubPullRequestCancelled, edit_native_pull_request
from teleclaude.github.reviews import GitHubReviewCancelled, execute_native_review
from teleclaude.types.github_account import GitHubAccount
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
    GitHubObjectMutation,
    GitHubObjectRef,
    GitHubPostFailure,
    GitHubPostResult,
    GitHubReviewEditRequest,
    GitHubReviewRequest,
    NativeGitHubPostSource,
)
from teleclaude.types.github_publication import GitHubPullRequestEditRequest, GitHubPullRequestResult
from teleclaude.types.workflow_record import Act

logger = get_logger(__name__)
_POST_EVENT = "github_comment_post acceptance=%s failure=%s session_id=%s provider_id=%s"
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
_DEFINITIVE_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_UNVERIFIED_OBJECT = "GitHub comment result could not be verified"
_ISSUE_COMMENT_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_PR_COMMENT_PERMISSIONS: AppPermissionsType = {"pull_requests": "write"}
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
_PR_COMMENT = ("pr", "comment")
_PR_EDIT = ("pr", "edit")
_PR_REVIEW = ("pr", "review")
_ISSUE_READ_PERMISSIONS: AppPermissionsType = {"issues": "read"}
_EDITOR_ENVIRONMENT = ("GH_EDITOR", "VISUAL", "EDITOR")
_EDITOR_FILE = "comment.md"
_NATIVE_REFUSAL = "gh: platform invocation refused: "
_NATIVE_INCOMPLETE = "gh: platform operation incomplete: "
_NATIVE_UNAVAILABLE = "native execution unavailable"
_NATIVE_CONTEXT_CHANGED = "session scope changed"
_COMMENT_WEB_URL = "https://github.com/{repository}/issues/{number}#issuecomment-{identifier}"
_PR_COMMENT_WEB_URL = "https://github.com/{repository}/pull/{number}#issuecomment-{identifier}"
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


async def post_github_issue_comment(
    context: GitHubPostingContext, request: GitHubIssueCommentRequest
) -> GitHubPostResult:
    """Carry one finite owner-admitted append to verified durable attribution; never replay an uncertain send."""
    scope = None
    try:
        if not await _current_context(
            context, request.target, native=isinstance(request.source, NativeGitHubPostSource)
        ):
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
        valid_scope, scope = await requested_pr_scope(context, request.pr_scope)
        if not valid_scope:
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
            owner=quote(owner, safe=_EMPTY),
            repo=quote(repo, safe=_EMPTY),
            number=scope.object.container_number if scope is not None else request.target.issue_number,
        )
    except (OSError, ValueError, SQLAlchemyError):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    response: _native_gh.Response | None = None
    cancelled = False
    dispatching = False
    try:
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment,
                request.target,
                _PR_COMMENT_PERMISSIONS if scope is not None else _ISSUE_COMMENT_PERMISSIONS,
            )
            if not await _current_context(
                context, request.target, native=isinstance(request.source, NativeGitHubPostSource)
            ):
                return GitHubPostResult(
                    acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED
                )
            if scope is not None:
                refused = await preflight_pr_scope(context, scope, credential)
                if refused is not None:
                    return refused
            child_environment = {
                **environment,
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            dispatching = True
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
    except asyncio.CancelledError:
        cancelled = True
        if response is None:
            response = _native_gh.Response(None, started=dispatching)
    except (OSError, ValueError, SQLAlchemyError):
        if response is None:
            response = _native_gh.Response(None, started=dispatching)
        # A cleanup failure after a received response cannot undo its provider acceptance or cancellation.
    result = _provider_result(response, request, context, body)
    if cancelled:
        raise _cancelled(result, context.binding.session_id)
    if result.acceptance is not GitHubAcceptance.CONFIRMED:
        return result
    if result.association is not None:
        try:
            store = await get_db()
            recorded = await store.record_github_object_association(result.association, pr_scope=scope)
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
    native = await prepare_native_issue_comment(arguments, context, directory=directory, stdin=stdin, editor=editor)
    request = GitHubIssueCommentRequest(
        target=context.target,
        body=native.body,
        act=Act.NOTE,
        source=native.source,
        pr_scope=native.pr_scope,
    )
    return await post_github_issue_comment(context, request)


async def _native_creator(
    context: GitHubPostingContext,
    ref: GitHubObjectRef,
    pr_scope: GitHubObjectRef | None = None,
) -> GitHubObjectAssociation | None:
    resolved = await resolve_native_comment(context, ref.provider_id)
    if resolved is None:
        return None
    creation, scope = resolved
    expected = scope.object if scope is not None else None
    if creation.object != ref or expected != pr_scope:
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
    ref = _comment_reference(comment, request.target, container_number=request.object.container_number)
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
    credential: GitHubInstallationCredential,
    pr_scope: GitHubObjectAssociation | None,
) -> tuple[GitHubCommentMaintenanceResult, GitHubObjectMutation | None, bool]:
    """Keep the read and effect stages separate, even while settling a cancelled child."""
    cancelled = False
    try:
        if (
            not await _current_context(context, request.target, native=True)
            or await _native_creator(context, request.object, request.pr_scope) != creation
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
            or await _native_creator(context, request.object, request.pr_scope) != creation
        ):
            return result.model_copy(update={_FAILURE: GitHubPostFailure.ADMISSION_REFUSED}), None, False
        if pr_scope is not None:
            refused = await preflight_pr_scope(context, pr_scope, credential)
            if refused is not None:
                return (
                    result.model_copy(
                        update={
                            _FAILURE: refused.failure,
                            _PROVIDER_STATUS: refused.provider_status,
                            _RETRY_DELAY: refused.retry_after,
                        }
                    ),
                    None,
                    False,
                )
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
    scope = None
    try:
        if not await _current_context(context, request.target, native=True):
            return result
        creation = await _native_creator(context, request.object, request.pr_scope)
        if creation is None:
            return result
        valid_scope, scope = await requested_pr_scope(context, request.pr_scope)
        if not valid_scope:
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
                context.binding.assignment,
                request.target,
                _PR_COMMENT_PERMISSIONS if scope is not None else _ISSUE_COMMENT_PERMISSIONS,
            )
            environment = {
                **environment,
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            result, mutation, cancelled = await _maintenance_exchange(
                context,
                request,
                creation,
                binary,
                endpoint,
                body,
                payload,
                directory,
                environment,
                result,
                credential,
                scope,
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
            recorded = await store.record_github_object_mutation(mutation, creation=creation, pr_scope=scope)
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
        template = (
            _PR_COMMENT_WEB_URL if result.object.container_number != context.target.issue_number else _COMMENT_WEB_URL
        )
        print(
            template.format(
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
        if arguments[:2] == _PR_EDIT:
            pr_request = prepare_native_pull_request(
                arguments, context, directory=directory, stdin=stdin, editor=lambda: _editor_body(directory)
            )
            if not isinstance(pr_request, GitHubPullRequestEditRequest):
                return _native_failure(NativeCommentRefusal.UNSUPPORTED_OPERATION.value, stderr)
            try:
                pr_result = await edit_native_pull_request(context, pr_request)
            except GitHubPullRequestCancelled as error:
                _native_pr_result(error.result, stdout, stderr)
                raise
            return _native_pr_result(pr_result, stdout, stderr)
        if arguments[:1] == (_API_COMMAND,):
            request = await prepare_native_comment_maintenance(arguments, context, directory=directory, stdin=stdin)
            if isinstance(request, GitHubReviewEditRequest):
                return await _native_review(context, request, stdout, stderr)
            try:
                maintained = await _maintain_native_comment(context, request)
            except GitHubMaintenanceCancelled as error:
                _native_maintenance_result(error.result, stdout, stderr)
                raise
            return _native_maintenance_result(maintained, stdout, stderr)
        if arguments[:2] == _PR_REVIEW:
            review = await prepare_native_review(arguments, context, directory=directory, stdin=stdin)
            return await _native_review(context, review, stdout, stderr)
        if arguments[:2] == _ISSUE_VIEW:
            return await _native_view(context, binary, arguments, stdout, stderr)
        if arguments[:2] not in (_ISSUE_COMMENT, _PR_COMMENT):
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


def _native_pr_result(result: GitHubPullRequestResult, stdout: TextIO, stderr: TextIO) -> int:
    """Print only safe typed facts; a creator association alone never stands in for later edit attribution."""
    print(result.model_dump_json(), file=stdout if result.attributed else stderr)
    return 0 if result.attributed else 1


async def _native_review(
    context: GitHubPostingContext, request: GitHubReviewRequest, stdout: TextIO, stderr: TextIO
) -> int:
    try:
        result = await execute_native_review(context, request)
    except GitHubReviewCancelled as error:
        print(error.result.model_dump_json(), file=stderr)
        raise
    print(result.model_dump_json(), file=stdout if result.attributed else stderr)
    return 0 if result.attributed else 1
