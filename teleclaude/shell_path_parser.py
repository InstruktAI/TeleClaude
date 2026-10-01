"""Shell command extraction and token matching helpers."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class _ShellSyntax(StrEnum):
    EMPTY = ""
    NEWLINE = "\n"
    BACKSLASH = "\\"
    SINGLE_QUOTE = "'"
    DOUBLE_QUOTE = '"'
    COMMENT = "#"
    TAB = "\t"
    NULL_DEVICE = "/dev/null"
    FD_REFERENCE = "&"


@dataclass
class _CommandBuilder:
    """Mutable state while one shell command is being lexed."""

    source: str = ""
    redirections: list[str] = field(default_factory=list)
    heredocs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ShellCommand:
    """One lexed simple command and the data attached to it."""

    words: tuple[str, ...]
    redirections: tuple[str, ...]
    heredocs: tuple[str, ...]


_SHELL_SEPARATORS = ("&&", "||", ";", "|", _ShellSyntax.NEWLINE)
_HEREDOC_PREFIXES = ("<<-", "<<")
_OUTPUT_REDIRECTIONS = (">>", ">")
_INPUT_REDIRECTIONS = ("<",)


def lex_shell_commands(command: str) -> tuple[ShellCommand, ...] | None:
    """Read simple commands, output destinations and here-document bodies.

    This is a bounded, non-evaluating lexer for checkpoint attribution. Unsupported
    or unbalanced shell text returns ``None`` so callers do not infer a target.
    """
    if not command:
        return ()

    lines = command.splitlines()
    commands: list[ShellCommand] = []
    line_index = 0
    while line_index < len(lines):
        group_end = line_index
        line_group = lines[line_index]
        while _has_unclosed_quote(line_group) and group_end + 1 < len(lines):
            group_end += 1
            line_group += _ShellSyntax.NEWLINE + lines[group_end]
        parsed = _lex_shell_line(line_group)
        if parsed is None:
            return None
        builders, delimiters = parsed
        if delimiters:
            body_index = group_end + 1
            bodies: dict[int, list[str]] = {}
            for delimiter, builder_index in delimiters:
                body_lines: list[str] = []
                found = False
                while body_index < len(lines):
                    body_line = lines[body_index]
                    body_index += 1
                    terminator = (
                        body_line.lstrip(_ShellSyntax.TAB) if delimiter.startswith(_ShellSyntax.TAB) else body_line
                    )
                    if terminator == delimiter.removeprefix(_ShellSyntax.TAB):
                        found = True
                        break
                    body_lines.append(body_line)
                if not found:
                    return None
                bodies.setdefault(builder_index, []).append(_ShellSyntax.NEWLINE.join(body_lines))
            for builder_index, command_bodies in bodies.items():
                if builder_index < len(builders):
                    builders[builder_index].heredocs = command_bodies
            line_index = body_index
        else:
            line_index = group_end + 1

        for builder in builders:
            if not builder.source.strip() and not builder.redirections and not builder.heredocs:
                continue
            try:
                words = tuple(shlex.split(builder.source, posix=True))
            except ValueError:
                return None
            commands.append(ShellCommand(words, tuple(builder.redirections), tuple(builder.heredocs)))
    return tuple(commands)


def _has_unclosed_quote(source: str) -> bool:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(source):
        if escaped:
            escaped = False
            continue
        if character == _ShellSyntax.BACKSLASH and quote != _ShellSyntax.SINGLE_QUOTE:
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = None
            continue
        if character == _ShellSyntax.COMMENT and (index == 0 or source[index - 1].isspace()):
            break
        if character in {_ShellSyntax.SINGLE_QUOTE, _ShellSyntax.DOUBLE_QUOTE}:
            quote = character
    return quote is not None


def _lex_shell_line(line: str) -> tuple[list[_CommandBuilder], list[tuple[str, int]]] | None:
    """Split one physical shell line without treating quoted punctuation as syntax."""
    builders: list[_CommandBuilder] = []
    current = _CommandBuilder()
    delimiters: list[tuple[str, int]] = []
    quote: str | None = None
    escaped = False
    index = 0

    def finish() -> None:
        nonlocal current
        if current.source.strip() or current.redirections or current.heredocs:
            builders.append(current)
        current = _CommandBuilder()

    while index < len(line):
        character = line[index]
        if escaped:
            current.source += character
            escaped = False
            index += 1
            continue
        if character == _ShellSyntax.BACKSLASH and quote != _ShellSyntax.SINGLE_QUOTE:
            current.source += character
            escaped = True
            index += 1
            continue
        if quote:
            current.source += character
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {_ShellSyntax.SINGLE_QUOTE, _ShellSyntax.DOUBLE_QUOTE}:
            quote = character
            current.source += character
            index += 1
            continue
        if character == _ShellSyntax.COMMENT and (index == 0 or line[index - 1].isspace()):
            break

        handled, next_index = _consume_redirection(line, index, current, delimiters, len(builders))
        if handled:
            if next_index < 0:
                return None
            index = next_index
            continue

        separator = next((item for item in _SHELL_SEPARATORS if line.startswith(item, index)), None)
        if separator:
            finish()
            index += len(separator)
            continue
        current.source += character
        index += 1

    if quote is not None or escaped:
        return None
    finish()
    return builders, delimiters


def _consume_redirection(
    line: str,
    index: int,
    current: _CommandBuilder,
    delimiters: list[tuple[str, int]],
    builder_index: int,
) -> tuple[bool, int]:
    """Consume one redirection and return its destination or here-document marker."""
    heredoc = next((operator for operator in _HEREDOC_PREFIXES if line.startswith(operator, index)), None)
    redirection = next((operator for operator in _OUTPUT_REDIRECTIONS if line.startswith(operator, index)), None)
    input_redirection = next((operator for operator in _INPUT_REDIRECTIONS if line.startswith(operator, index)), None)
    operator = heredoc or redirection or input_redirection
    if operator is None:
        return False, index
    if current.source and current.source[-1].isdigit() and (len(current.source) == 1 or current.source[-2].isspace()):
        current.source = current.source[:-1]
    destination_index = index + len(operator)
    while destination_index < len(line) and line[destination_index].isspace():
        destination_index += 1
    destination, destination_index = _read_shell_word(line, destination_index)
    if destination is None:
        return True, -1
    try:
        parsed_destination = shlex.split(destination, posix=True)
    except ValueError:
        return True, -1
    if len(parsed_destination) != 1:
        return True, -1
    value = parsed_destination[0]
    if heredoc:
        delimiter = (_ShellSyntax.TAB if operator == "<<-" else _ShellSyntax.EMPTY) + value
        delimiters.append((delimiter, builder_index))
        current.heredocs.append(_ShellSyntax.EMPTY)
    elif redirection and not value.startswith(_ShellSyntax.FD_REFERENCE) and value != _ShellSyntax.NULL_DEVICE:
        current.redirections.append(value)
    return True, destination_index


def _read_shell_word(source: str, start: int) -> tuple[str | None, int]:
    """Read one quoted or bare shell word from a redirection operator."""
    if start >= len(source):
        return None, start
    quote: str | None = None
    escaped = False
    index = start
    while index < len(source):
        character = source[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == _ShellSyntax.BACKSLASH and quote != _ShellSyntax.SINGLE_QUOTE:
            escaped = True
            index += 1
            continue
        if quote:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {_ShellSyntax.SINGLE_QUOTE, _ShellSyntax.DOUBLE_QUOTE}:
            quote = character
            index += 1
            continue
        if character.isspace() or any(
            source.startswith(item, index) for item in (*_SHELL_SEPARATORS, *_OUTPUT_REDIRECTIONS, *_INPUT_REDIRECTIONS)
        ):
            break
        index += 1
    if quote is not None or escaped:
        return None, index
    return source[start:index], index


__all__ = [
    "ShellCommand",
    "executable_command_tokens",
    "extract_shell_command",
    "lex_shell_commands",
    "matches_command_prefix",
    "segment_tokens",
    "split_shell_segments",
]


def extract_shell_command(input_data: Mapping[str, object]) -> str:
    """Extract command text from tool input payloads across adapters."""
    command = input_data.get("command")
    if not isinstance(command, str) or not command.strip():
        command = input_data.get("cmd")
    if isinstance(command, str):
        return command.strip()
    return ""


def split_shell_segments(command: str) -> list[str]:
    """Split a shell command into sequential segments."""
    if not command:
        return []
    parts = re.split(r"(?:&&|\|\||;|\n)", command)
    return [part.strip() for part in parts if part.strip()]


def segment_tokens(segment: str) -> list[str]:
    """Best-effort tokenization for a command segment."""
    if not segment:
        return []
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


def executable_command_tokens(segment: str) -> list[str]:
    """Return command tokens after leading shell environment assignments."""
    tokens = segment_tokens(segment)
    first_command_index = 0
    for token in tokens:
        if not _ENV_ASSIGNMENT_RE.match(token):
            break
        first_command_index += 1
    return tokens[first_command_index:]


def matches_command_prefix(segment: str, command: tuple[str, ...]) -> bool:
    """Match one executable segment against an exact command prefix."""
    tokens = executable_command_tokens(segment)
    return len(tokens) >= len(command) and tuple(tokens[: len(command)]) == command
