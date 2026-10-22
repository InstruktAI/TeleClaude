"""Post an admitted issue comment through real gh and retain verified creation attribution."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from http.client import HTTPException, parse_headers
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO
from urllib.parse import quote

from githubkit_schemas.v2026_03_10.models import IssueComment
from githubkit_schemas.v2026_03_10.types import AppPermissionsType
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.core.db import get_db
from teleclaude.core.github_identity import (
    GitHubPostingContext,
    ManagedGitHubInvocation,
    resolve_managed_github_invocation,
    resolve_native_github_posting_context,
)
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.envelope import render_github_envelope
from teleclaude.github.native import NativeCommentRefused, prepare_native_issue_comment
from teleclaude.paths import BIN_DIR
from teleclaude.types.github_account import GitHubAccount, GitHubAccountKind
from teleclaude.types.github_posting import (
    GitHubAcceptance,
    GitHubEditEvidence,
    GitHubIssueCommentRequest,
    GitHubObjectAssociation,
    GitHubObjectKind,
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
_GH = "gh"
_PATH = "PATH"
_UTF8 = "utf-8"
_EMPTY = ""
_EMPTY_BYTES = b""
_BASE_ENVIRONMENT = frozenset({_PATH, "HOME", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "WINDIR"})
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
_ISSUE_URL = "https://api.github.com/repos/{owner}/{repo}/issues/{number}"
_COMMENT_URL = "https://api.github.com/repos/{owner}/{repo}/issues/comments/{identifier}"
_GH_ARGUMENTS = (
    "api",
    "--hostname",
    "github.com",
    "--method",
    "POST",
    "--include",
    "--input",
    "-",
    "--header",
    "Accept: application/vnd.github+json",
    "--header",
    "Content-Type: application/json",
    "--header",
    "X-GitHub-Api-Version: 2026-03-10",
)
_SEND_TIMEOUT_SECONDS = 60.0
_HTTP_PREFIX = b"HTTP/"
_RETRY_AFTER = "Retry-After"
_RATE_REMAINING = "X-RateLimit-Remaining"
_RATE_RESET = "X-RateLimit-Reset"
_ZERO = "0"
_DEFINITIVE_REJECTIONS = frozenset({400, 401, 403, 404, 405, 406, 410, 413, 414, 415, 422, 429})
_WRAPPER_DIRECTORY = Path("install/wrappers")
_UNVERIFIED_OBJECT = "GitHub comment result could not be verified"
_ISSUE_COMMENT_PERMISSIONS: AppPermissionsType = {"issues": "write"}
_ASSOCIATION = "association"
_FAILURE = "failure"


@dataclass(frozen=True)
class _Response:
    status: int | None
    body: bytes = _EMPTY_BYTES
    retry_after: timedelta | None = None
    started: bool = True


class _SendCancelled(asyncio.CancelledError):
    def __init__(self, response: _Response) -> None:
        super().__init__()
        self.response = response


class GitHubPostingCancelled(asyncio.CancelledError):
    """Propagate cancellation with safe provider evidence, without claiming unrecorded attribution."""

    def __init__(self, result: GitHubPostResult) -> None:
        super().__init__(_CANCELLED_MESSAGE)
        self.result = result


def _launch_environment() -> dict[str, str]:
    """Keep only host basics; provider controls and loader/proxy overrides never pass through."""
    return {
        name: value
        for name, value in os.environ.items()  # guard: direct-env-read - child-process startup seam
        if name in _BASE_ENVIRONMENT
    }


def _gh_binary(environment: Mapping[str, str]) -> Path | None:
    wrapper = (BIN_DIR / _GH).resolve()
    source_wrapper = (Path(__file__).resolve().parents[1] / _WRAPPER_DIRECTORY / _GH).resolve()
    for directory in environment.get(_PATH, os.defpath).split(os.pathsep):
        candidate = (Path(directory) / _GH).resolve()
        if candidate not in (wrapper, source_wrapper) and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _response(stdout: bytes) -> _Response:
    """Translate gh's included response with the standard-library header parser, without raw diagnostics."""
    stream = BytesIO(stdout)
    line = stream.readline()
    try:
        status = int(line.split()[1]) if line.startswith(_HTTP_PREFIX) else None
    except (IndexError, ValueError):
        status = None
    if status is None or not 100 <= status <= 599:
        return _Response(None)
    try:
        headers = parse_headers(stream)
    except HTTPException:
        return _Response(status)
    delay = None
    if status in (403, 429):
        try:
            seconds = headers.get(_RETRY_AFTER)
            reset = headers.get(_RATE_RESET)
            if seconds is not None:
                delay = timedelta(seconds=max(0, int(seconds)))
            elif headers.get(_RATE_REMAINING) == _ZERO and reset is not None:
                delay = max(datetime.fromtimestamp(int(reset), UTC) - datetime.now(UTC), timedelta())
        except (OverflowError, OSError, ValueError):
            delay = None
    return _Response(status, stream.read(), delay)


async def _send(
    binary: Path, endpoint: str, payload: bytes, environment: Mapping[str, str], directory: str
) -> _Response:
    # Real gh owns provider HTTP/auth behavior; subprocess execution preserves the adopted native client contract.
    try:
        process = await asyncio.create_subprocess_exec(
            str(binary),
            *_GH_ARGUMENTS,
            endpoint,
            cwd=directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return _Response(None, started=False)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(payload), timeout=_SEND_TIMEOUT_SECONDS)
    except (TimeoutError, OSError):
        return _response(await _reap(process))
    except asyncio.CancelledError:
        try:
            recovered = _response(await _reap(process))
        except OSError:
            recovered = _Response(None)
        raise _SendCancelled(recovered) from None
    # A process exit code is neither acceptance evidence nor safe-retry permission.
    return _response(stdout)


async def _reap(process: asyncio.subprocess.Process) -> bytes:
    """Settle the actual child after timeout, failed I/O or cancellation, without retrying its request."""
    try:
        process.kill()
    except ProcessLookupError:
        pass
    try:
        stdout, _ = await process.communicate()
        return stdout
    except OSError:
        await process.wait()
        return _EMPTY_BYTES


async def _current_context(context: GitHubPostingContext, request: GitHubIssueCommentRequest) -> bool:
    invocation = await resolve_managed_github_invocation()
    if not isinstance(invocation, ManagedGitHubInvocation) or invocation != context.invocation:
        return False
    store = await get_db()
    binding = await store.get_github_session_binding(invocation.session.session_id)
    if (
        binding is None
        or binding != context.binding
        or binding.session_id != invocation.session.session_id
        or binding.role is not invocation.role.name
    ):
        return False
    project = invocation.session.project_path
    if (
        not project
        or request.target.project_path.resolve() != Path(project).resolve()
        or request.target.project_path.resolve() != context.target.project_path.resolve()
    ):
        return False
    if isinstance(request.source, NativeGitHubPostSource):
        target = await store.get_github_native_target(binding.session_id)
        return (
            request.target == context.target == target and request.target.work_item == invocation.session.working_slug
        )
    # Sealed/reflected target, act, phase and identity are admitted by their owner, never native CLI arguments.
    return True


def _accepted(
    response: _Response, request: GitHubIssueCommentRequest, context: GitHubPostingContext, body: str
) -> GitHubPostResult:
    """Verify actual object, scope, body and stable author independently of the envelope's assertions."""
    ref = None
    digest = None
    evidence = None
    try:
        comment = IssueComment.model_validate_json(response.body)
        owner, repo = request.target.repository.split(_REPOSITORY_SEPARATOR)
        if (
            comment.id <= 0
            or comment.issue_url.casefold()
            != _ISSUE_URL.format(owner=owner, repo=repo, number=request.target.issue_number).casefold()
            or comment.url.casefold() != _COMMENT_URL.format(owner=owner, repo=repo, identifier=comment.id).casefold()
        ):
            raise ValueError(_UNVERIFIED_OBJECT)
        ref = GitHubObjectRef(
            repository_id=request.target.repository_id,
            container_number=request.target.issue_number,
            kind=GitHubObjectKind.ISSUE_COMMENT,
            provider_id=comment.id,
        )
        if not isinstance(comment.body, str) or comment.body != body or comment.user is None:
            raise ValueError(_UNVERIFIED_OBJECT)
        digest = sha256(comment.body.encode(_UTF8)).hexdigest()
        evidence = GitHubEditEvidence(updated_at=comment.updated_at.isoformat())
        author = GitHubAccount(
            id=comment.user.id,
            node_id=comment.user.node_id,
            login=comment.user.login,
            type=GitHubAccountKind(comment.user.type),
        )
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
    response: _Response, request: GitHubIssueCommentRequest, context: GitHubPostingContext, body: str
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


async def post_github_issue_comment(
    context: GitHubPostingContext, request: GitHubIssueCommentRequest
) -> GitHubPostResult:
    """Carry one finite owner-admitted append to verified durable attribution; never replay an uncertain send."""
    try:
        if not await _current_context(context, request):
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
        body = render_github_envelope(
            context.binding.role, context.binding.session_id, request.act, request.phase, request.source, request.body
        )
        payload = json.dumps({_BODY: body}, ensure_ascii=False).encode(_UTF8)
        environment = _launch_environment()
        binary = _gh_binary(environment)
        if binary is None:
            return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.BINARY_UNAVAILABLE)
        owner, repo = request.target.repository.split(_REPOSITORY_SEPARATOR)
        endpoint = _COMMENT_ENDPOINT.format(
            owner=quote(owner, safe=_EMPTY), repo=quote(repo, safe=_EMPTY), number=request.target.issue_number
        )
    except (OSError, ValueError, SQLAlchemyError):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    response: _Response | None = None
    cancelled = False
    try:
        with TemporaryDirectory(prefix=_CONFIG_PREFIX) as directory:
            credential = await issue_github_installation_credential(
                context.binding.assignment, request.target, _ISSUE_COMMENT_PERMISSIONS
            )
            if not await _current_context(context, request):
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
                response = await _send(binary, endpoint, payload, child_environment, directory)
            except _SendCancelled as error:
                response = error.response
                cancelled = True
            except OSError:
                # Failure while settling an already-started child leaves acceptance unknown.
                response = _Response(None)
    except GitHubCredentialRefused as error:
        return GitHubPostResult(
            acceptance=GitHubAcceptance.NO_EFFECT,
            failure=GitHubPostFailure.CREDENTIAL_REFUSED,
            provider_status=error.rate_limit.status_code if error.rate_limit is not None else None,
            retry_after=error.rate_limit.retry_after if error.rate_limit is not None else None,
            credential_refusal=error.key_failure.value if error.key_failure is not None else error.reason.value,
        )
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


async def post_native_issue_comment(
    arguments: Sequence[str], *, directory: Path, stdin: BinaryIO, editor: Callable[[], str] | None = None
) -> GitHubPostResult:
    """Resolve managed execution, admit/collect native prose, and execute the same complete finite posting path."""
    context = await resolve_native_github_posting_context()
    if not isinstance(context, GitHubPostingContext):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    try:
        native = prepare_native_issue_comment(arguments, context, directory=directory, stdin=stdin, editor=editor)
        request = GitHubIssueCommentRequest(target=context.target, body=native.body, act=Act.NOTE, source=native.source)
    except (NativeCommentRefused, ValueError):
        return GitHubPostResult(acceptance=GitHubAcceptance.NO_EFFECT, failure=GitHubPostFailure.ADMISSION_REFUSED)
    return await post_github_issue_comment(context, request)
