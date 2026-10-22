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
from teleclaude.types.github_posting import (
    GitHubIssueCommentDeleteRequest,
    GitHubIssueCommentEditRequest,
    GitHubObjectKind,
    GitHubObjectRef,
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
_VIEW_PROGRAM = "gh issue view"
_VIEW_COMMAND = "view"
_COMMENTS_FLAG = "--comments"
_COMMENTS_SHORT_FLAG = "-c"
_JSON_FLAG = "--json"
_JSON_FIELDS = "fields"
_COMMA = ","
_VIEW_FIELDS = frozenset(
    {"id", "number", "url", "title", "body", "state", "comments", "author", "createdAt", "updatedAt"}
)
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
_REPOS_SEGMENT = "repos"
_COMMENTS_SEGMENT = "comments"
_BODY_FIELD = "body"
_BODY_ASSIGNMENT = "body="


class _Command(StrEnum):
    ISSUE = "issue"
    COMMENT = "comment"


_COMMENT_PATH = (_Command.ISSUE, _Command.COMMENT)


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


class _ViewArguments(argparse.Namespace):
    target: str
    repository: list[str] | None = None
    comments: int = 0
    fields: list[str] | None = None


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


def prepare_native_comment_maintenance(
    arguments: Sequence[str], context: GitHubPostingContext, *, directory: Path, stdin: BinaryIO
) -> GitHubIssueCommentEditRequest | GitHubIssueCommentDeleteRequest:
    """Admit only explicit comment PATCH/DELETE and one body string, rejecting duplicate JSON keys."""
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
    if method not in (_PATCH_METHOD, _DELETE_METHOD):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    parts = values.endpoint.split(_PATH_SEPARATOR)
    target = context.target
    if (
        len(parts) != 6
        or parts[0] != _REPOS_SEGMENT
        or parts[3:5] != [_ISSUES_SEGMENT, _COMMENTS_SEGMENT]
        or _PATH_SEPARATOR.join(parts[1:3]).casefold() != target.repository.casefold()
        or not parts[5].isascii()
        or not parts[5].isdecimal()
        or int(parts[5]) <= 0
    ):
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    ref = GitHubObjectRef(
        repository_id=target.repository_id,
        container_number=target.issue_number,
        kind=GitHubObjectKind.ISSUE_COMMENT,
        provider_id=int(parts[5]),
    )
    if method == _DELETE_METHOD:
        if values.fields is not None or values.inputs is not None:
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        return GitHubIssueCommentDeleteRequest(target=target, object=ref)
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
    return GitHubIssueCommentEditRequest(target=target, object=ref, body=body)


@dataclass(frozen=True)
class NativeIssueCommentRequest:
    """One admitted body-only append; source identity is structurally absent."""

    context: GitHubPostingContext
    body: str
    source: NativeGitHubPostSource = field(default_factory=NativeGitHubPostSource, init=False)


def prepare_native_issue_view(arguments: Sequence[str], context: GitHubPostingContext) -> tuple[str, ...]:
    """Admit one bound read and reconstruct native arguments without executable formatting or diagnostics."""
    if tuple(arguments[:2]) != (_Command.ISSUE, _VIEW_COMMAND):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    parser = _Parser(prog=_VIEW_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument(_Argument.TARGET)
    parser.add_argument(_Flag.REPOSITORY, _Flag.REPOSITORY_SHORT, dest=_Argument.REPOSITORY, action=_Action.APPEND)
    parser.add_argument(_COMMENTS_FLAG, _COMMENTS_SHORT_FLAG, action=_Action.COUNT, default=0)
    parser.add_argument(_JSON_FLAG, dest=_JSON_FIELDS, action=_Action.APPEND)
    values = _ViewArguments()
    try:
        parser.parse_args(arguments[2:], namespace=values)
    except argparse.ArgumentError:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
    fields = values.fields
    if (
        values.comments > 1
        or (values.repository is not None and len(values.repository) > 1)
        or (fields is not None and len(fields) > 1)
    ):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    target = context.target
    repository = values.repository[0] if values.repository else target.repository
    if (
        repository.casefold().removeprefix(_HOST_PREFIX) != target.repository.casefold()
        or _issue_number(values.target, target.repository) != target.issue_number
    ):
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    result: tuple[str, ...] = (
        _Command.ISSUE,
        _VIEW_COMMAND,
        str(target.issue_number),
        _Flag.REPOSITORY,
        target.repository,
    )
    if values.comments:
        result += (_COMMENTS_FLAG,)
    if fields is not None:
        selected = fields[0].split(_COMMA)
        if not selected or any(name not in _VIEW_FIELDS for name in selected):
            raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
        result += (_JSON_FLAG, fields[0])
    return result


def prepare_native_issue_comment(
    arguments: Sequence[str],
    context: GitHubPostingContext,
    *,
    directory: Path,
    stdin: BinaryIO,
    editor: Callable[[], str] | None = None,
) -> NativeIssueCommentRequest:
    """Resolve all fields and the exact bound target before reading prose or loading credentials."""
    if tuple(arguments[:2]) != _COMMENT_PATH:
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
    if _issue_number(values.target, target.repository) != target.issue_number:
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
    return NativeIssueCommentRequest(context, body)


def _parse(arguments: Sequence[str]) -> _Arguments:
    parser = _Parser(prog=_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
    parser.add_argument(_Argument.TARGET)
    body = parser.add_mutually_exclusive_group()
    body.add_argument(_Flag.BODY, _Flag.BODY_SHORT, dest=_Argument.BODY, action=_Action.APPEND)
    body.add_argument(_Flag.BODY_FILE, _Flag.BODY_FILE_SHORT, dest=_Argument.BODY_FILE, action=_Action.APPEND)
    body.add_argument(_Flag.EDITOR, _Flag.EDITOR_SHORT, dest=_Argument.EDITOR, action=_Action.COUNT)
    parser.add_argument(_Flag.REPOSITORY, _Flag.REPOSITORY_SHORT, dest=_Argument.REPOSITORY, action=_Action.APPEND)
    values = _Arguments()
    try:
        parser.parse_args(arguments, namespace=values)
    except argparse.ArgumentError:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
    return values


def _issue_number(selector: str, repository: str) -> int:
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
            or fields[3] != _ISSUES_SEGMENT
            or _PATH_SEPARATOR.join(unquote(value) for value in fields[1:3]).casefold() != repository.casefold()
            or not fields[4].isascii()
            or not fields[4].isdecimal()
        ):
            raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
        return int(fields[4])
    except ValueError:
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH) from None
