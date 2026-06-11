#!/usr/bin/env python3
"""Reject bare hardcoded HOME paths under .teleclaude in markdown files.

Scans selected working-tree files, a repo-wide working-tree list, or the
staged set (relative to the calling project's cwd) for
``/Users/<user>/.teleclaude/...`` or ``/home/<user>/.teleclaude/...`` patterns
that should be ``~/.teleclaude/...`` instead. ``@``-prefixed resource refs are
managed by the ``teleclaude-docs`` git filter and are allowed. Used by `telec code lint
and as a raw pre-commit backstop.

Project root is derived from cwd, never from this script's filesystem
location — the script ships with TeleClaude but must scan the calling
project's tree.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from teleclaude.git import GIT_EXECUTABLE

_HOME_PATH_RE = re.compile(r"(?<!@)(/Users/[^/\s]+|/home/[^/\s]+)/\.teleclaude")


def _staged_markdown_files(project_root: Path) -> list[Path]:
    """Return staged ACM markdown files, relative to project root."""
    result = subprocess.run(
        [GIT_EXECUTABLE, "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z", "--", "*.md"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [project_root / name for name in result.stdout.split("\0") if name]


def _staged_file_has_home_path(path: Path, project_root: Path) -> bool:
    """Check the staged blob (not the worktree) so partial stages match what will commit."""
    rel = path.relative_to(project_root).as_posix()
    result = subprocess.run(
        [GIT_EXECUTABLE, "show", f":{rel}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return bool(_HOME_PATH_RE.search(result.stdout))


def _working_tree_file_has_home_path(path: Path) -> bool:
    try:
        return bool(_HOME_PATH_RE.search(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def _resolve_working_tree_files(project_root: Path, files: list[str]) -> list[Path]:
    resolved: list[Path] = []
    root = project_root.resolve()
    for file in files:
        candidate = Path(file)
        path = candidate if candidate.is_absolute() else root / candidate
        try:
            rel = path.resolve(strict=False).relative_to(root)
        except ValueError:
            continue
        if rel.suffix == ".md" and (root / rel).is_file():
            resolved.append(root / rel)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject hardcoded HOME paths in markdown files.")
    parser.add_argument("--project-root", default=str(Path.cwd()))
    parser.add_argument(
        "--working-tree-files",
        nargs="*",
        help="Filesystem paths to scan from the working tree. Omit for staged-blob mode.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    project_root = Path(args.project_root).resolve()

    if args.working_tree_files is None:
        offenders = [
            path for path in _staged_markdown_files(project_root) if _staged_file_has_home_path(path, project_root)
        ]
    else:
        offenders = [
            path
            for path in _resolve_working_tree_files(project_root, args.working_tree_files)
            if _working_tree_file_has_home_path(path)
        ]
    if not offenders:
        return 0

    for path in offenders:
        print(path.relative_to(project_root))
    print("ERROR: Hardcoded HOME paths found in docs. Run 'telec projects init' to set up filters.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
