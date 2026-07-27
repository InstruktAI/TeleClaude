"""Replace environment-export steps in release.yaml and lint-test.yaml."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

GITHUB_ENV = "GITHUB_ENV"
GITHUB_PATH = "GITHUB_PATH"
EMPTY_VALUE = ""
EQUALS = "="
NEWLINE = "\n"
PATH_OPTION = "--path"
ENV_OPTION = "--env"
PATH_HELP = "Directory to append to GITHUB_PATH."
ENV_HELP = "KEY=VALUE entry to append to GITHUB_ENV; repeatable."
DESCRIPTION = "Export GitHub Actions environment values."
MISSING_PATH_MESSAGE = "Required environment variable is missing or empty: GITHUB_PATH"
MISSING_ENV_MESSAGE = "Required environment variable is missing or empty: GITHUB_ENV"
INVALID_ENV_MESSAGE = "Environment entries must use KEY=VALUE: "


def required_env(name: str, message: str) -> str:
    """Read a required Actions protocol-file path."""
    value = os.environ.get(name, EMPTY_VALUE)
    if value:
        return value
    raise ValueError(message)


def append_line(destination: str, value: str) -> None:
    """Append one protocol line to an Actions file."""
    with Path(destination).open("a", encoding="utf-8") as output_file:
        output_file.write(value + NEWLINE)


def parse_env_entry(entry: str) -> tuple[str, str]:
    """Split one KEY=VALUE argument without changing its value."""
    key, separator, value = entry.partition(EQUALS)
    if separator and key:
        return key, value
    raise ValueError(INVALID_ENV_MESSAGE + entry)


def main(argv: list[str] | None = None) -> int:
    """Export requested Actions environment values."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(PATH_OPTION, help=PATH_HELP)
    parser.add_argument(ENV_OPTION, action="append", default=[], help=ENV_HELP)
    args = parser.parse_args(argv)
    try:
        if args.path:
            append_line(required_env(GITHUB_PATH, MISSING_PATH_MESSAGE), args.path)
        for entry in args.env:
            key, value = parse_env_entry(entry)
            append_line(required_env(GITHUB_ENV, MISSING_ENV_MESSAGE), key + EQUALS + value)
    except ValueError as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
