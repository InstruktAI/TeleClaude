"""Shared GitHub Actions plumbing for workflow entrypoints."""

from __future__ import annotations

import os
import sys
from pathlib import Path

GITHUB_ENV = "GITHUB_ENV"
GITHUB_OUTPUT = "GITHUB_OUTPUT"
GITHUB_PATH = "GITHUB_PATH"
ERROR_ANNOTATION = "::error::"
MASK_ANNOTATION = "::add-mask::"
EMPTY_VALUE = ""
NEWLINE = "\n"
MISSING_ENV_MESSAGE = "Required environment variable is missing or empty: "


def append_output(key: str, value: str) -> None:
    """Append a step output value to the GitHub Actions output file."""
    append_key_value(required_env(GITHUB_OUTPUT), key, value)


def append_env(key: str, value: str) -> None:
    """Append an environment value to the GitHub Actions environment file."""
    append_key_value(required_env(GITHUB_ENV), key, value)


def append_path(path: str) -> None:
    """Append a directory to the GitHub Actions path file."""
    output_path = Path(required_env(GITHUB_PATH))
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(path + NEWLINE)


def append_key_value(destination: str, key: str, value: str) -> None:
    """Append one GitHub Actions key-value protocol line."""
    output_path = Path(destination)
    with output_path.open("a", encoding="utf-8") as output_file:
        output_file.write(key + "=" + value + NEWLINE)


def emit_error(message: str) -> None:
    """Emit a GitHub Actions error annotation."""
    print(ERROR_ANNOTATION + message)


def emit_mask(value: str) -> None:
    """Mask a value in subsequent GitHub Actions output."""
    print(MASK_ANNOTATION + value)


def required_env(name: str) -> str:
    """Return a required non-empty environment variable or terminate the step."""
    value = os.environ.get(name, EMPTY_VALUE)
    if value:
        return value
    emit_error(MISSING_ENV_MESSAGE + name)
    raise SystemExit(1)


def repo_root() -> Path:
    """Resolve the repository root from this package's location."""
    return Path(__file__).resolve().parents[2]


def exit_with_error(message: str) -> int:
    """Emit an error annotation and return the standard failure status."""
    emit_error(message)
    return 1


def print_to_stderr(message: str) -> None:
    """Write a diagnostic to standard error."""
    print(message, file=sys.stderr)
