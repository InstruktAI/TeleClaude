"""Admit only explicit creating-builder PR text operations before collecting prose."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO, Never
from urllib.parse import unquote, urlsplit

from teleclaude.core.github_identity import GitHubPostingContext
from teleclaude.core.roles import RoleName
from teleclaude.github.native import NativeCommentRefusal, NativeCommentRefused
from teleclaude.types.github_publication import GitHubPullRequestCreateRequest, GitHubPullRequestEditRequest

_PROGRAM = "gh pr description"
_PR = "pr"
_CREATE = "create"
_EDIT = "edit"
_APPEND = "append"
_COUNT = "count"
_TARGET = "target"
_TITLE = "title"
_BODY = "body"
_FILE = "body_file"
_REPO = "repository"
_BASE = "base"
_HEAD = "head"
_DRAFT = "draft"
_EDITOR = "editor"
_UTF8 = "utf-8"
_STDIN = "-"
_SLASH = "/"
_NEWLINE = "\n"
_HOST_PREFIX = "github.com/"
_HTTPS = "https"
_HOST = "github.com"
_PULL = "pull"
_MAIN = "main"


class _Flag(StrEnum):
    TITLE = "--title"
    TITLE_SHORT = "-t"
    BODY = "--body"
    BODY_SHORT = "-b"
    FILE = "--body-file"
    FILE_SHORT = "-F"
    REPO = "--repo"
    REPO_SHORT = "-R"
    BASE = "--base"
    BASE_SHORT = "-B"
    HEAD = "--head"
    HEAD_SHORT = "-H"
    DRAFT = "--draft"
    DRAFT_SHORT = "-d"
    EDITOR = "--editor"
    EDITOR_SHORT = "-e"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)


class _Arguments(argparse.Namespace):
    target: str | None = None
    title: list[str] | None = None
    body: list[str] | None = None
    body_file: list[str] | None = None
    repository: list[str] | None = None
    base: list[str] | None = None
    head: list[str] | None = None
    draft: int = 0
    editor: int = 0


def _number(selector: str, repository: str) -> int:
    if selector.isascii() and selector.isdecimal() and int(selector) > 0:
        return int(selector)
    parsed = urlsplit(selector)
    parts = parsed.path.split(_SLASH)
    if (
        parsed.scheme != _HTTPS
        or parsed.hostname != _HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or len(parts) != 5
        or parts[3] != _PULL
        or _SLASH.join(unquote(part) for part in parts[1:3]).casefold() != repository.casefold()
        or not parts[4].isascii()
        or not parts[4].isdecimal()
        or int(parts[4]) <= 0
    ):
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    return int(parts[4])


def prepare_native_pull_request(
    arguments: Sequence[str],
    context: GitHubPostingContext,
    *,
    directory: Path,
    stdin: BinaryIO,
    editor: Callable[[], str],
) -> GitHubPullRequestCreateRequest | GitHubPullRequestEditRequest:
    """No implicit target, branch, text, metadata, or interactive provider-side defaults."""
    if len(arguments) < 2 or arguments[0] != _PR or arguments[1] not in (_CREATE, _EDIT):
        raise NativeCommentRefused(NativeCommentRefusal.UNSUPPORTED_OPERATION)
    create = arguments[1] == _CREATE
    target = context.target
    if context.binding.role is not RoleName.BUILDER:
        raise NativeCommentRefused(NativeCommentRefusal.BUILDER_REQUIRED)
    if not target.branch or not target.base or target.branch == target.base or target.branch == _MAIN:
        raise NativeCommentRefused(NativeCommentRefusal.WORK_REF_UNAVAILABLE)
    parser = _Parser(prog=_PROGRAM, add_help=False, allow_abbrev=False, exit_on_error=False)
    if not create:
        parser.add_argument(_TARGET)
    parser.add_argument(_Flag.TITLE, _Flag.TITLE_SHORT, dest=_TITLE, action=_APPEND)
    body = parser.add_mutually_exclusive_group()
    body.add_argument(_Flag.BODY, _Flag.BODY_SHORT, dest=_BODY, action=_APPEND)
    body.add_argument(_Flag.FILE, _Flag.FILE_SHORT, dest=_FILE, action=_APPEND)
    parser.add_argument(_Flag.REPO, _Flag.REPO_SHORT, dest=_REPO, action=_APPEND)
    if create:
        parser.add_argument(_Flag.BASE, _Flag.BASE_SHORT, dest=_BASE, action=_APPEND)
        parser.add_argument(_Flag.HEAD, _Flag.HEAD_SHORT, dest=_HEAD, action=_APPEND)
        parser.add_argument(_Flag.DRAFT, _Flag.DRAFT_SHORT, dest=_DRAFT, action=_COUNT)
        parser.add_argument(_Flag.EDITOR, _Flag.EDITOR_SHORT, dest=_EDITOR, action=_COUNT)
    values = _Arguments()
    try:
        parser.parse_args(arguments[2:], namespace=values)
    except argparse.ArgumentError:
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS) from None
    if (
        any(
            len(value) != 1
            for value in (values.title, values.body, values.body_file, values.repository, values.base, values.head)
            if value is not None
        )
        or (
            values.repository is not None
            and values.repository[0].removeprefix(_HOST_PREFIX).casefold() != target.repository.casefold()
        )
        or (values.base is not None and values.base[0] != target.base)
        or (values.head is not None and values.head[0] != target.branch)
        or values.editor > 1
        or (create and values.draft != 1)
        or (values.editor and any(value is not None for value in (values.title, values.body, values.body_file)))
        or (
            create
            and not values.editor
            and (values.title is None or (values.body is None and values.body_file is None))
        )
        or (not create and values.title is None and values.body is None and values.body_file is None)
    ):
        raise NativeCommentRefused(NativeCommentRefusal.INVALID_ARGUMENTS)
    number = _number(values.target, target.repository) if values.target is not None else None
    title = values.title[0] if values.title is not None else None
    contents: str | None = None
    try:
        if values.editor:
            title, _, contents = editor().partition(_NEWLINE)
        elif values.body is not None:
            contents = values.body[0]
        elif values.body_file is not None:
            path = values.body_file[0]
            contents = (stdin.read() if path == _STDIN else (directory / Path(path)).read_bytes()).decode(_UTF8)
        if title is not None:
            title.encode(_UTF8)
        if contents is not None:
            contents.encode(_UTF8)
    except (OSError, UnicodeError):
        raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE) from None
    if create:
        if title is None or contents is None:
            raise NativeCommentRefused(NativeCommentRefusal.BODY_UNAVAILABLE)
        return GitHubPullRequestCreateRequest(target=target, title=title, body=contents)
    if number is None:
        raise NativeCommentRefused(NativeCommentRefusal.TARGET_MISMATCH)
    return GitHubPullRequestEditRequest(target=target, number=number, title=title, body=contents)
