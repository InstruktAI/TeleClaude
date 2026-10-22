"""Post an admitted issue comment through real gh and retain verified creation attribution."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from http.client import HTTPException, parse_headers
from io import BytesIO
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
from teleclaude.github.credentials import GitHubCredentialRefused, issue_github_installation_credential
from teleclaude.github.envelope import render_github_envelope
from teleclaude.github.native import (
    NativeCommentRefusal,
    NativeCommentRefused,
    prepare_native_issue_comment,
    prepare_native_issue_view,
)
from teleclaude.paths import BIN_DIR
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


async def _current_context(context: GitHubPostingContext, target: GitHubWorkTarget, *, native: bool) -> bool:
    current: GitHubPostingContext | RefusedGitHubInvocation | LocalNativeGitHubInvocation | NativeHumanGitHubInvocation
    if isinstance(context.invocation, AdmittedGitHubInvocation):
        if native:
            return False
        current = await resolve_admitted_github_posting_context()
    else:
        current = await resolve_native_github_posting_context()
    return isinstance(current, GitHubPostingContext) and current == context and target == current.target


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
                response = await _send(binary, endpoint, payload, child_environment, directory)
            except _SendCancelled as error:
                response = error.response
                cancelled = True
            except OSError:
                # Failure while settling an already-started child leaves acceptance unknown.
                response = _Response(None)
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
                (*command, str(body_path)), cwd=directory, env=_launch_environment(), check=False
            )
            if completed.returncode != 0:
                raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE)
            return body_path.read_bytes().decode(_UTF8)
    except NativeCommentRefused:
        raise
    except (OSError, ValueError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None


async def _native_read_process(
    binary: Path,
    arguments: tuple[str, ...],
    directory: str,
    environment: Mapping[str, str],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run only reconstructed read/help arguments; real gh owns provider reads and formatting."""
    process = await asyncio.create_subprocess_exec(
        str(binary),
        *arguments,
        cwd=directory,
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout=_SEND_TIMEOUT_SECONDS)
    except (TimeoutError, asyncio.CancelledError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()
        raise


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
                **_launch_environment(),
                **_FIXED_ENVIRONMENT,
                _GH_CONFIG_DIR: directory,
                _GH_TOKEN: credential.token.get_secret_value(),
            }
            return await _native_read_process(binary, admitted, directory, environment, stdout, stderr)
    except GitHubCredentialRefused as error:
        return _native_result(_credential_result(error), context, stdout, stderr)


async def execute_native_github(
    arguments: Sequence[str], *, directory: Path, stdin: BinaryIO, stdout: TextIO, stderr: TextIO
) -> int:
    """Serve the native entry with exact disclosure-free help, observed scope and finite bound handlers."""
    arguments = tuple(arguments)
    try:
        environment = _launch_environment()
        binary = _gh_binary(environment)
        if binary is None:
            return _native_failure(_NATIVE_UNAVAILABLE, stderr)
        help_arguments = _help_arguments(arguments)
        if help_arguments is not None:
            with TemporaryDirectory(prefix=_CONFIG_PREFIX) as temporary:
                return await _native_read_process(
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
