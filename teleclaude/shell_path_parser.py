"""Shell command mutation and path extraction helpers."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Mapping

__all__ = [
    "command_likely_mutates_files",
    "extract_shell_command",
    "extract_shell_touched_paths",
    "looks_like_path_token",
    "segment_tokens",
    "split_shell_segments",
]

# A digit directly before `>` is a file-descriptor redirect (`2>/dev/null`, `1>&2`),
# not a file write — excluded so stderr-suppression idioms on read-only commands
# never register as mutation intent.
_OUTPUT_REDIRECT_RE = re.compile(r"(?:^|[^<>&\d])>>?\s*(?:\"[^\"]+\"|'[^']+'|[^\s;&|]+)")
_OUTPUT_REDIRECT_TARGET_RE = re.compile(r"(?:^|[^<>&\d])>>?\s*(?P<target>\"[^\"]+\"|'[^']+'|[^\s;&|]+)")


def command_likely_mutates_files(command: str) -> bool:
    """Best-effort shell command classifier for file-mutating intent."""
    if not command:
        return False
    cmd = command.strip()
    if not cmd:
        return False

    patterns = (
        r"\bapply_patch\b",
        r"\bgit\s+(add|mv|rm|restore|checkout|apply)\b",
        r"\bsed\s+.*-i(?:\s|$)",
        r"\bperl\s+-pi\b",
        r"\btouch\b",
        r"\bmkdir\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\brm\b",
        r"\btee\b",
    )
    if any(re.search(pattern, cmd) for pattern in patterns):
        return True
    return bool(_OUTPUT_REDIRECT_RE.search(cmd))


def extract_shell_command(input_data: Mapping[str, object]) -> str:
    """Extract command text from tool input payloads across adapters."""
    command = input_data.get("command")
    if not isinstance(command, str) or not command.strip():
        command = input_data.get("cmd")
    if isinstance(command, str):
        return command.strip()
    return ""


def looks_like_path_token(token: str) -> bool:
    """Heuristic for shell tokens that are likely file paths."""
    if not token:
        return False
    if token.startswith(("-", "$")):
        return False
    if token in {"|", ">", ">>", "2>", "1>", "&&", "||", ";"}:
        return False
    if token.startswith("s/") and token.count("/") >= 2:
        return False
    if token.startswith("{") or token.startswith("["):
        return False

    if token.startswith(("./", "../", "/")):
        return True
    if "/" in token:
        return True

    suffixes = (
        ".py",
        ".md",
        ".txt",
        ".rst",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".sh",
        ".sql",
        ".ini",
        ".cfg",
        ".lock",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
    )
    return token.endswith(suffixes)


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


def extract_shell_touched_paths(command: str, normalize_path: Callable[[str], str]) -> set[str]:
    """Best-effort extraction of mutated file paths from shell commands."""
    touched: set[str] = set()
    if not command:
        return touched

    for segment in split_shell_segments(command):
        touched.update(_extract_redirection_paths(segment, normalize_path))
        for token in segment_tokens(segment):
            clean = _clean_shell_path_token(token)
            if ">" in clean:
                continue
            if not looks_like_path_token(clean):
                continue
            if ":" in clean and not clean.startswith(("./", "../", "/")):
                continue
            normalized = normalize_path(clean)
            if normalized:
                touched.add(normalized)
    return touched


def _clean_shell_path_token(token: str) -> str:
    return token.strip().strip("\"'`").strip(",;:")


def _extract_redirection_paths(segment: str, normalize_path: Callable[[str], str]) -> set[str]:
    touched: set[str] = set()
    for match in _OUTPUT_REDIRECT_TARGET_RE.finditer(segment):
        clean = _clean_shell_path_token(match.group("target"))
        if not looks_like_path_token(clean):
            continue
        normalized = normalize_path(clean)
        if normalized:
            touched.add(normalized)
    return touched
