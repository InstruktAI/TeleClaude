#!/usr/bin/env python3
"""Run ruff safely by filtering non-Python file targets.

This prevents accidental invocation on markdown/docs files when callers pass
mixed target lists (for example from changed-files sets).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEFAULT_TARGETS = ["teleclaude", "tools", "bin"]
PYTHON_SUFFIXES = {".py", ".pyi"}


def _split_options_and_paths(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split CLI args into ruff options and path-like targets."""
    options: list[str] = []
    paths: list[str] = []
    for token in tokens:
        if token.startswith("-"):
            options.append(token)
        else:
            paths.append(token)
    return options, paths


def _is_python_target(path: Path) -> bool:
    """Return True if a path target is valid for ruff Python linting."""
    if path.is_dir():
        return True
    return path.suffix in PYTHON_SUFFIXES


def main(argv: list[str]) -> int:
    options, raw_paths = _split_options_and_paths(argv)

    requested_paths = raw_paths or DEFAULT_TARGETS
    kept: list[str] = []
    skipped: list[str] = []

    for raw in requested_paths:
        path = Path(raw)
        if _is_python_target(path):
            kept.append(raw)
        else:
            skipped.append(raw)

    if skipped:
        print(
            "ruff-safe: skipped non-Python targets: " + ", ".join(skipped),
            file=sys.stderr,
        )

    if not kept:
        print("ruff-safe: no Python targets after filtering; skipping ruff", file=sys.stderr)
        return 0

    cmd = ["uv", "run", "--quiet", "ruff", "check", *options, *kept]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
