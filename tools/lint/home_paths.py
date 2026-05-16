#!/usr/bin/env python3
"""Reject hardcoded HOME paths under .teleclaude in staged markdown files.

Scans the staged set (relative to the calling project's cwd) for
``/Users/<user>/.teleclaude/...`` or ``/home/<user>/.teleclaude/...`` patterns
that should be ``~/.teleclaude/...`` instead. Used by `telec code lint
--step home_paths`.

Project root is derived from cwd, never from this script's filesystem
location — the script ships with TeleClaude but must scan the calling
project's tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_HOME_PATH_RE = re.compile(r"(@?)(/Users/[^/\s]+|/home/[^/\s]+)/\.teleclaude")


def _staged_markdown_files(project_root: Path) -> list[Path]:
    """Return staged ACM markdown files, relative to project root."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z", "--", "*.md"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [project_root / name for name in result.stdout.split("\0") if name]


def _file_has_home_path(path: Path, project_root: Path) -> bool:
    """Check the staged blob (not the worktree) so partial stages match what will commit."""
    rel = path.relative_to(project_root).as_posix()
    result = subprocess.run(
        ["git", "show", f":{rel}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return bool(_HOME_PATH_RE.search(result.stdout))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    project_root = Path.cwd()
    if args and args[0] == "--project-root":
        project_root = Path(args[1]).resolve()

    offenders = [path for path in _staged_markdown_files(project_root) if _file_has_home_path(path, project_root)]
    if not offenders:
        return 0

    for path in offenders:
        print(path.relative_to(project_root))
    print("ERROR: Hardcoded HOME paths found in docs. Run 'telec projects init' to set up filters.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
