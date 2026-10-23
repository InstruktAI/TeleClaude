"""Admit a bound native issue-comment request and collect its opaque prose before credentials."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Never
from urllib.parse import unquote, urlsplit

from teleclaude.core.github_identity import GitHubPostingContext
from teleclaude.github._conversation_scope import (
    resolve_native_comment,
    resolve_native_reply,
    resolve_native_review,
    resolve_pr_scope,
)
from teleclaude.types.github_posting import (
    GitHubIssueCommentDeleteRequest,
    GitHubIssueCommentEditRequest,
    GitHubObjectAssociation,
    GitHubObjectRef,
    GitHubReviewEditRequest,
    GitHubReviewReplyRequest,
    GitHubReviewRequest,
    NativeGitHubPostSource,
)

_PROGRAM = "gh issue comment"
_UTF8 = "utf-8"
_STDIN_PATH = "-"
_PATH_SEPARATOR = "/"
_HTTPS = "https"
_GITHUB_HOST = "github.com"
_HOST_PREFIX = _GITHUB_HOST + _PATH_SEPARATOR
_ISSUES_SEGMENT = "issues"
_PULL_SEGMENT = "pull"
_VIEW_PROGRAM = "gh view"
_VIEW_COMMAND = "view"
_COMMENTS_FLAG = "--comments"
_COMMENTS_SHORT_FLAG = "-c"
_GET_METHOD = "GET"
_API_COMMAND = "api"
_API_PROGRAM = "gh api comment maintenance"
_METHOD_FLAG = "--method"
_METHOD_SHORT_FLAG = "-X"
_RAW_FIELD_FLAG = "--raw-field"
_RAW_FIELD_SHORT_FLAG = "-f"
_INPUT_FLAG = "--input"
_METHOD_ARGUMENT = "methods"
_FIELD_ARGUMENT = "fields"
_INPUT_ARGUMENT = "inputs"
_ENDPOINT_ARGUMENT = "endpoint"
_PATCH_METHOD = "PATCH"
_DELETE_METHOD = "DELETE"
_PUT_METHOD = "PUT"
_POST_METHOD = "POST"
_REPLIES_SEGMENT = "replies"
_REVIEW_COMMAND = "review"
_REVIEW_FLAG = "--comment"
_REVIEW_SHORT_FLAG = "-c"
_REVIEW_ARGUMENT = "comment"
_PULLS_SEGMENT = "pulls"
_REVIEWS_SEGMENT = "reviews"
_REPOS_SEGMENT = "repos"
_COMMENTS_SEGMENT = "comments"
_BODY_FIELD = "body"
_BODY_ASSIGNMENT = "body="


class _Command(StrEnum):
    ISSUE = "issue"
    COMMENT = "comment"
    PR = "pr"


_COMMENT_PATH = (_Command.ISSUE, _Command.COMMENT)
_PR_COMMENT_PATH = (_Command.PR, _Command.COMMENT)


class _Flag(StrEnum):
    BODY = "--body"
    BODY_SHORT = "-b"
    BODY_FILE = "--body-file"
    BODY_FILE_SHORT = "-F"
    EDITOR = "--editor"
    EDITOR_SHORT = "-e"
    REPOSITORY = "--repo"
    REPOSITORY_SHORT = "-R"


class _Argument(StrEnum):
    TARGET = "target"
    BODY = "body"
    BODY_FILE = "body_file"
    EDITOR = "editor"
    REPOSITORY = "repository"


class _Action(StrEnum):
    APPEND = "append"
    COUNT = "count"


class NativeCommentRefusal(StrEnum):
    """Pre-effect admission failures, without echoing arguments or prose."""

    UNSUPPORTED_OPERATION = "unsupported_operation"
    INVALID_ARGUMENTS = "invalid_arguments"
    TARGET_MISMATCH = "target_mismatch"
    BODY_UNAVAILABLE = "body_unavailable"
    EDITOR_UNAVAILABLE = "editor_unavailable"
    BUILDER_REQUIRED = "current_builder_required"
    WORK_REF_UNAVAILABLE = "authoritative_branch_or_base_unavailable"
    PR_SCOPE_UNAVAILABLE = "recorded_pr_relationship_unavailable"
    CREATOR_UNAVAILABLE = "recorded_native_creator_unavailable"


class NativeCommentRefused(ValueError):
    """The invocation produced no provider request or credential lookup."""

    def __init__(self, reason: NativeCommentRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        """Refuse without allowing argparse to print caller-supplied values."""
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)


class _Arguments(argparse.Namespace):
    target: str
    body: list[str] | None = None
    body_file: list[str] | None = None
    repository: list[str] | None = None
    editor: int = 0
    comment: int = 0


class _ViewArguments(argparse.Namespace):
    target: str
    repository: list[str] | None = None
    comments: int = 0


class _MaintenanceArguments(argparse.Namespace):
    endpoint: str
    methods: list[str] | None = None
    fields: list[str] | None = None
    inputs: list[str] | None = None


def _json_body_pairs(pairs: list[tuple[str, object]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in pairs:
        if key in result or not isinstance(value, str):
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        result[key] = value
    return result


async def prepare_native_comment_maintenance(
    arguments: Sequence[str], context: GitHubPostingContext, *, directory: Path, stdin: BinaryIO
) -> (
    GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest | GitHubReviewEditRequest | GitHubReviewReplyRequest
):
    """Admit only fixed comment maintenance, submitted-review body PUT or explicit root reply POST."""
    if not arguments or arguments[0] != _API_COMMAND:
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    parser = _Parser(prog=_API_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument(_ENDPOINT_ARGUMENT)
    parser.add_argument(_METHOD_FLAG, _METHOD_SHORT_FLAG, dest=_METHOD_ARGUMENT, action=_Action.APPEND)
    payload = parser.add_mutually_exclusive_group()
    payload.add_argument(_RAW_FIELD_FLAG, _RAW_FIELD_SHORT_FLAG, dest=_FIELD_ARGUMENT, action=_Action.APPEND)
    payload.add_argument(_INPUT_FLAG, dest=_INPUT_ARGUMENT, action=_Action.APPEND)
    values = _MaintenanceArguments()
    try:
        parser.parse_args(arguments[1:], namespace=values)
    except argparse.ArgumentError:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
    if (
        values.methods is None
        or len(values.methods) != 1
        or any(len(value) != 1 for value in (values.fields, values.inputs) if value is not None)
    ):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    method = values.methods[0]
    if method not in (_PATCH_METHOD, _DELETE_METHOD, _PUT_METHOD, _POST_METHOD):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    parts = values.endpoint.split(_PATH_SEPARATOR)
    target = context.target
    if method == _POST_METHOD:
        return await _prepare_reply_api(values, parts, context, directory, stdin)
    if len(parts) == 7 and parts[3] == _PULLS_SEGMENT and parts[5] == _REVIEWS_SEGMENT:
        if (
            method != _PUT_METHOD
            or parts[0] != _REPOS_SEGMENT
            or _PATH_SEPARATOR.join(parts[1:3]).casefold() != target.repository.casefold()
            or any(not value.isascii() or not value.isdecimal() or int(value) <= 0 for value in (parts[4], parts[6]))
        ):
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        review = await resolve_native_review(context, int(parts[6]))
        if review is None or review[0].object.container_number != int(parts[4]):
            raise NativeCommentRefused(NativeCommentRefusal.CREATOR_UNAVAILABLE)
        creation, scope = review
        return GitHubReviewEditRequest(
            target=target, object=creation.object, pr_scope=scope.object, body=_api_body(values, directory, stdin)
        )
    if (
        method == _PUT_METHOD
        or len(parts) != 6
        or parts[0] != _REPOS_SEGMENT
        or parts[3] not in (_ISSUES_SEGMENT, _PULLS_SEGMENT)
        or parts[4] != _COMMENTS_SEGMENT
        or _PATH_SEPARATOR.join(parts[1:3]).casefold() != target.repository.casefold()
        or not parts[5].isascii()
        or not parts[5].isdecimal()
        or int(parts[5]) <= 0
    ):
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    resolved = (
        await resolve_native_reply(context, int(parts[5]))
        if parts[3] == _PULLS_SEGMENT
        else await resolve_native_comment(context, int(parts[5]))
    )
    if resolved is None:
        raise NativeCommentRefused(NativeCommentRefusal.CREATOR_UNAVAILABLE)
    creation, scope = resolved
    ref = creation.object
    pr_scope = scope.object if scope is not None else None
    if method == _DELETE_METHOD:
        if values.fields is not None or values.inputs is not None:
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        return GitHubIssueCommentDeleteRequest(target=target, object=ref, pr_scope=pr_scope)
    return GitHubIssueCommentEditRequest(
        target=target, object=ref, body=_api_body(values, directory, stdin), pr_scope=pr_scope
    )


async def _prepare_reply_api(
    values: _MaintenanceArguments,
    parts: list[str],
    context: GitHubPostingContext,
    directory: Path,
    stdin: BinaryIO,
) -> GitHubReviewReplyRequest:
    """Only an explicit PR/top-level candidate and body may enter the fixed reply handler."""
    if (
        len(parts) != 8
        or parts[0] != _REPOS_SEGMENT
        or _PATH_SEPARATOR.join(parts[1:3]).casefold() != context.target.repository.casefold()
        or parts[3] != _PULLS_SEGMENT
        or parts[5] != _COMMENTS_SEGMENT
        or parts[7] != _REPLIES_SEGMENT
        or any(not value.isascii() or not value.isdecimal() or int(value) <= 0 for value in (parts[4], parts[6]))
    ):
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    scope = await resolve_pr_scope(context, int(parts[4]))
    if scope is None:
        raise NativeCommentRefused(NativeCommentRefusal.PR_SCOPE_UNAVAILABLE)
    return GitHubReviewReplyRequest(
        target=context.target, pr_scope=scope.object, root_id=int(parts[6]), body=_api_body(values, directory, stdin)
    )


def _api_body(values: _MaintenanceArguments, directory: Path, stdin: BinaryIO) -> str:
    """Read exactly one body field after immutable object selection; duplicate keys refuse."""
    try:
        if values.fields is not None:
            field = values.fields[0]
            if not field.startswith(_BODY_ASSIGNMENT):
                raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
            body = field.removeprefix(_BODY_ASSIGNMENT)
        elif values.inputs is not None:
            source = values.inputs[0]
            contents = stdin.read() if source == _STDIN_PATH else (directory / Path(source)).read_bytes()
            decoded: object = json.loads(contents.decode(_UTF8), object_pairs_hook=_json_body_pairs)
            if not isinstance(decoded, dict) or set(decoded) != {_BODY_FIELD}:
                raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
            body = decoded[_BODY_FIELD]
            if not isinstance(body, str):
                raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        else:
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        body.encode(_UTF8)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None
    return body


@dataclass(frozen=True)
class NativeIssueCommentRequest:
    """One admitted body-only append; source identity is structurally absent."""

    context: GitHubPostingContext
    body: str
    pr_scope: GitHubObjectRef | None = None
    source: NativeGitHubPostSource = field(default_factory=NativeGitHubPostSource, init=False)


class NativeReadKind(StrEnum):
    """The three fixed conversational read shapes; no generic API read."""

    ISSUE = "issue"
    PR = "pr"
    REVIEW_COMMENTS = "review_comments"


@dataclass(frozen=True)
class NativeViewRequest:
    """One exact issue/associated PR read, with an optional complete conversation list."""

    kind: NativeReadKind
    number: int
    comments: bool = False
    scope: GitHubObjectAssociation | None = None


async def prepare_native_view(arguments: Sequence[str], context: GitHubPostingContext) -> NativeViewRequest:
    """Use the existing selectors and PR relationship owner before any read credential."""
    path = tuple(arguments[:2])
    if path == (_API_COMMAND, _GET_METHOD):
        if len(arguments) != 3:
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        parts = arguments[2].split(_PATH_SEPARATOR)
        if (
            len(parts) != 7
            or parts[0]
            or parts[1] != _REPOS_SEGMENT
            or _PATH_SEPARATOR.join(parts[2:4]).casefold() != context.target.repository.casefold()
            or parts[4] != _PULLS_SEGMENT
            or not parts[5].isascii()
            or not parts[5].isdecimal()
            or int(parts[5]) <= 0
            or parts[6] != _COMMENTS_SEGMENT
        ):
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        number = int(parts[5])
        kind = NativeReadKind.REVIEW_COMMENTS
        comments = True
    else:
        if path not in ((_Command.ISSUE, _VIEW_COMMAND), (_Command.PR, _VIEW_COMMAND)):
            raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
        parser = _Parser(prog=_VIEW_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
        parser.add_argument(_Argument.TARGET)
        parser.add_argument(_Flag.REPOSITORY, _Flag.REPOSITORY_SHORT, dest=_Argument.REPOSITORY, action=_Action.APPEND)
        parser.add_argument(_COMMENTS_FLAG, _COMMENTS_SHORT_FLAG, action=_Action.COUNT, default=0)
        values = _ViewArguments()
        try:
            parser.parse_args(arguments[2:], namespace=values)
        except argparse.ArgumentError:
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
        if values.comments > 1 or (values.repository is not None and len(values.repository) > 1):
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        repository = values.repository[0] if values.repository else context.target.repository
        if repository.casefold().removeprefix(_HOST_PREFIX) != context.target.repository.casefold():
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        kind = NativeReadKind.ISSUE if path[0] == _Command.ISSUE else NativeReadKind.PR
        number = _issue_number(values.target, context.target.repository, pull_request=kind is NativeReadKind.PR)
        comments = bool(values.comments)
    if kind is NativeReadKind.ISSUE:
        if number != context.target.issue_number:
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        return NativeViewRequest(kind, number, comments)
    scope = await resolve_pr_scope(context, number)
    if scope is None:
        raise NativeCommentRefused(NativeCommentRefusal.PR_SCOPE_UNAVAILABLE)
    return NativeViewRequest(kind, number, comments, scope)


async def prepare_native_issue_comment(
    arguments: Sequence[str],
    context: GitHubPostingContext,
    *,
    directory: Path,
    stdin: BinaryIO,
    editor: Callable[[], str] | None = None,
) -> NativeIssueCommentRequest:
    """Resolve all fields and the exact bound target before reading prose or loading credentials."""
    path = tuple(arguments[:2])
    if path not in (_COMMENT_PATH, _PR_COMMENT_PATH):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    values = _parse(arguments[2:])
    if any(len(value) > 1 for value in (values.body, values.body_file, values.repository) if value is not None):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    if values.editor > 1:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    target = context.target
    repository = values.repository[0] if values.repository else target.repository
    if repository.casefold().removeprefix(_HOST_PREFIX) != target.repository.casefold():
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    number = _issue_number(values.target, target.repository, pull_request=path == _PR_COMMENT_PATH)
    pr_scope = None
    if path == _PR_COMMENT_PATH:
        scope = await resolve_pr_scope(context, number)
        if scope is None:
            raise NativeCommentRefused(NativeCommentRefusal.PR_SCOPE_UNAVAILABLE)
        pr_scope = scope.object
    elif number != target.issue_number:
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    try:
        if values.body is not None:
            body = values.body[0]
        elif values.body_file is not None:
            source = values.body_file[0]
            body = (
                stdin.read().decode(_UTF8)
                if source == _STDIN_PATH
                else (directory / Path(source)).read_bytes().decode(_UTF8)
            )
        else:
            if editor is None:
                raise NativeCommentRefused(NativeCommentRefusal.EDITOR_UNAVAILABLE)
            body = editor()
        body.encode(_UTF8)
    except (OSError, UnicodeError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None
    return NativeIssueCommentRequest(context, body, pr_scope)


async def prepare_native_review(
    arguments: Sequence[str], context: GitHubPostingContext, *, directory: Path, stdin: BinaryIO
) -> GitHubReviewRequest:
    """Require explicit PR, COMMENT and body before any credential; never create a pending review."""
    if tuple(arguments[:2]) != (_Command.PR, _REVIEW_COMMAND):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    values = _parse(arguments[2:], review=True)
    if values.comment != 1 or (values.body is None and values.body_file is None):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    if any(len(value) != 1 for value in (values.body, values.body_file, values.repository) if value is not None):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    repository = values.repository[0] if values.repository else context.target.repository
    if repository.casefold().removeprefix(_HOST_PREFIX) != context.target.repository.casefold():
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    number = _issue_number(values.target, context.target.repository, pull_request=True)
    scope = await resolve_pr_scope(context, number)
    if scope is None:
        raise NativeCommentRefused(NativeCommentRefusal.PR_SCOPE_UNAVAILABLE)
    try:
        if values.body is not None:
            body = values.body[0]
        else:
            if values.body_file is None:
                raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE)
            source = values.body_file[0]
            body = (stdin.read() if source == _STDIN_PATH else (directory / Path(source)).read_bytes()).decode(_UTF8)
        body.encode(_UTF8)
    except (OSError, UnicodeError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None
    return GitHubReviewRequest(target=context.target, pr_scope=scope.object, body=body)


def _parse(arguments: Sequence[str], *, review: bool = False) -> _Arguments:
    parser = _Parser(prog=_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument(_Argument.TARGET)
    body = parser.add_mutually_exclusive_group()
    body.add_argument(_Flag.BODY, _Flag.BODY_SHORT, dest=_Argument.BODY, action=_Action.APPEND)
    body.add_argument(_Flag.BODY_FILE, _Flag.BODY_FILE_SHORT, dest=_Argument.BODY_FILE, action=_Action.APPEND)
    if review:
        parser.add_argument(_REVIEW_FLAG, _REVIEW_SHORT_FLAG, dest=_REVIEW_ARGUMENT, action=_Action.COUNT)
    else:
        body.add_argument(_Flag.EDITOR, _Flag.EDITOR_SHORT, dest=_Argument.EDITOR, action=_Action.COUNT)
    parser.add_argument(_Flag.REPOSITORY, _Flag.REPOSITORY_SHORT, dest=_Argument.REPOSITORY, action=_Action.APPEND)
    values = _Arguments()
    try:
        parser.parse_args(arguments, namespace=values)
    except argparse.ArgumentError:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
    return values


def _issue_number(selector: str, repository: str, *, pull_request: bool = False) -> int:
    """Resolve only an explicit number or matching GitHub issue URL."""
    try:
        if selector.isascii() and selector.isdecimal():
            return int(selector)
        parsed = urlsplit(selector)
        fields = parsed.path.split(_PATH_SEPARATOR)
        if (
            parsed.scheme != _HTTPS
            or parsed.hostname != _GITHUB_HOST
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or len(fields) != 5
            or fields[3] != (_PULL_SEGMENT if pull_request else _ISSUES_SEGMENT)
            or (pull_request and parsed.fragment)
            or _PATH_SEPARATOR.join(unquote(value) for value in fields[1:3]).casefold() != repository.casefold()
            or not fields[4].isascii()
            or not fields[4].isdecimal()
        ):
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        return int(fields[4])
    except ValueError:
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH) from None
