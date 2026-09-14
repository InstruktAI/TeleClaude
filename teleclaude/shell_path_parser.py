"""Shell command extraction and token matching helpers."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping

__all__ = [
    "executable_command_tokens",
    "extract_shell_command",
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
