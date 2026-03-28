#!/usr/bin/env python3
"""Session-aware file scope resolver for lint and test scripts.

Callable from shell as a subprocess. Resolves the set of files touched by the
current agent session and outputs them filtered by mode.

Exit code protocol:
  0  — session detected, scoped files written to stdout (one per line).
  2  — no session identity file found (normal non-agent context; fall back silently).
  3  — session detected but file collection failed; diagnostic emitted on stderr.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from teleclaude.session_identity import get_session_id
from teleclaude.todo_scaffold import _collect_session_touched_files  # pylint: disable=protected-access

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _mirror_path(source_path: str) -> str:
    """Compute the expected test path for a teleclaude source file.

    Applies the same convention as tools/lint/test_mapping._mirror_path:
    ``teleclaude/x/y.py`` → ``tests/unit/x/test_y.py``.
    """
    without_prefix = source_path.removeprefix("teleclaude/")
    parent, filename = without_prefix.rsplit("/", 1) if "/" in without_prefix else ("", without_prefix)
    test_filename = f"test_{filename}"
    if parent:
        return f"tests/unit/{parent}/{test_filename}"
    return f"tests/unit/{test_filename}"


def _filter_by_mode(mode: str, touched: set[str], project_root: Path) -> list[str]:
    """Filter touched files for the given mode.

    lint mode: include Python source files that the session actually touched.
    test mode: map teleclaude/ sources to test companions; include touched test files directly.
    """
    if mode == "lint":
        result_set: set[str] = set()
        for f in touched:
            if f.endswith(".py") or f.endswith(".pyi"):
                if (project_root / f).exists():
                    result_set.add(f)
        return sorted(result_set)
    # test mode
    test_set: set[str] = set()
    for f in touched:
        if "tests/" in f:
            # Test files included directly if they exist on disk.
            if (project_root / f).exists():
                test_set.add(f)
        elif f.startswith("teleclaude/") and (f.endswith(".py") or f.endswith(".pyi")):
            # Map source file to its test companion; silently skip missing companions.
            companion = _mirror_path(f)
            if (project_root / companion).exists():
                test_set.add(companion)
    return sorted(test_set)


def main() -> None:
    """Resolve session-touched files and print them to stdout."""
    # Testing seam: when SESSION_SCOPE_STUB_OUTPUT is set, bypass session detection
    # and emit the stub content directly. Used by shell-level tests to exercise
    # the scoped branch in lint.sh/test.sh without a live DB session.
    _stub = os.environ.get("SESSION_SCOPE_STUB_OUTPUT")
    if _stub is not None:
        if _stub:
            sys.stdout.write(_stub)
            if not _stub.endswith("\n"):
                sys.stdout.write("\n")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Resolve session-touched files for scoped lint/test runs.",
    )
    parser.add_argument("--mode", choices=["lint", "test"], required=True)
    parser.add_argument(
        "--project-root",
        default=str(_REPO_ROOT),
        help="Repository root (default: derived from script location).",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    session_id = get_session_id()
    if not session_id:
        sys.exit(2)

    try:
        touched: set[str] = _collect_session_touched_files(str(project_root))
    except Exception as exc:  # all collection errors → exit 3 per protocol
        print(f"session_scope: collection failed for session {session_id}: {exc}", file=sys.stderr)
        sys.exit(3)

    result = _filter_by_mode(args.mode, touched, project_root)

    if result:
        sys.stdout.write("\n".join(result) + "\n")


if __name__ == "__main__":
    main()
