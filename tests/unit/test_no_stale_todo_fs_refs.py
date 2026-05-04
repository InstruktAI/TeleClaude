"""Regression guard: no stale filesystem todos/{slug}/ references in markdown artifacts.

Catches any re-introduction of filesystem-path-style todo references in worker-command
and required-read markdown surfaces. These were cleaned up by the filesystem-todo-refs-
cleanup bug fix; this test ensures they do not reappear.

Allowed: HTTP API route forms like ``/todos/work``, ``/todos/create`` (leading slash).
Disallowed: filesystem path forms like ``todos/{slug}/``, ``todos/fix-*/``,
``todos/person-identity-auth*/`` (no leading slash before ``todos``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# Matches filesystem-style todos/<name>/ paths.
# Requires that todos/ is NOT immediately preceded by '/' (which marks HTTP routes).
# Positive examples: todos/{slug}/, todos/fix-*/, todos/person-identity-auth*/
# Negative examples (not matched): /todos/work, /todos/create, /todos/integrate
_STALE_PATTERN = re.compile(r"(?<![/\w])todos/[a-zA-Z{*]")

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SCANNED_DIRS = [
    _REPO_ROOT / "agents" / "commands",
    _REPO_ROOT / "docs" / "global",
    _REPO_ROOT / "docs" / "project",
    _REPO_ROOT / "demos",
    _REPO_ROOT / "manifests",
    _REPO_ROOT / "templates" / "todos",
]

_SCANNED_FILES = [
    _REPO_ROOT / "README.md",
]


def _markdown_files() -> list[Path]:
    files: list[Path] = []
    for f in _SCANNED_FILES:
        if f.exists():
            files.append(f)
    for d in _SCANNED_DIRS:
        if d.exists():
            files.extend(sorted(d.rglob("*.md")))
    return files


def _stale_hits(path: Path) -> list[tuple[int, str]]:
    return [
        (i, line.rstrip())
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _STALE_PATTERN.search(line)
    ]


@pytest.mark.parametrize("md_file", _markdown_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_no_stale_filesystem_todos_refs(md_file: Path) -> None:
    """Fail if a markdown file contains stale todos/{slug}/ filesystem-path references."""
    hits = _stale_hits(md_file)
    assert not hits, f"{md_file.relative_to(_REPO_ROOT)}: stale filesystem todos/ ref(s):\n" + "\n".join(
        f"  line {ln}: {text}" for ln, text in hits
    )
