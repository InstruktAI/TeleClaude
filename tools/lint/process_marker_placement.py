#!/usr/bin/env -S uv run --quiet
"""Detect the ``process`` pytest marker used outside ``tests/process/``.

The ``process`` marker tier is collected by CI only from ``tests/process/``; a
``process`` marker anywhere else is silently dropped from that tier and never
runs. This check fails when a ``process`` marker reference appears in a test
file whose repo-relative path does not start with ``tests/process/``.

With explicit paths, it checks only selected working-tree test files. With no
paths or ``--all``, it checks tracked repo-wide test files.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

PROCESS_DIR = "tests/process/"


@dataclass(frozen=True)
class Finding:
    """One misplaced ``process`` marker reference."""

    path: str
    line: int


def _line(node: ast.AST) -> int:
    line = getattr(node, "lineno", 1)
    return line if isinstance(line, int) else 1


def _is_process_marker(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "process"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    )


def _display_path(path: Path, repo_root: Path) -> str:
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return resolved_path.as_posix()


def _is_python_test_file(path: Path, repo_root: Path) -> bool:
    if path.suffix != ".py" or not path.name.startswith("test_"):
        return False
    try:
        relative = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return len(relative.parts) > 1 and relative.parts[0] == "tests"


def _repo_targets(repo_root: Path) -> Iterable[Path]:
    # Git index inspection has no project-native binding and is the repo-wide tracked-file contract.
    result = subprocess.run(
        ["git", "ls-files", "--", "tests"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        path = repo_root / line
        if _is_python_test_file(path, repo_root):
            yield path


def _selected_targets(raw_targets: Sequence[str], repo_root: Path) -> Iterable[Path]:
    for target_str in raw_targets:
        target = Path(target_str)
        path = target if target.is_absolute() else repo_root / target
        if path.is_dir():
            yield from sorted(f for f in path.rglob("test_*.py") if _is_python_test_file(f, repo_root))
        elif path.is_file() and _is_python_test_file(path, repo_root):
            yield path


def _iter_targets(raw_targets: Sequence[str], repo_root: Path, *, run_all: bool) -> Iterable[Path]:
    if run_all:
        yield from sorted(_repo_targets(repo_root))
    else:
        yield from _selected_targets(raw_targets, repo_root)


def lint_file(path: Path, repo_root: Path) -> list[Finding]:
    """Return misplaced ``process`` marker findings for one Python test file."""
    display = _display_path(path, repo_root)
    if display.startswith(PROCESS_DIR):
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=display)
    except SyntaxError:
        return []
    return [Finding(path=display, line=_line(node)) for node in ast.walk(tree) if _is_process_marker(node)]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the process-marker placement linter."""
    args = list(sys.argv[1:] if argv is None else argv)
    run_all = "--all" in args or not args
    args = [arg for arg in args if arg != "--all"]
    repo_root = Path.cwd()
    findings: list[Finding] = []
    seen: set[Path] = set()

    for path in _iter_targets(args, repo_root, run_all=run_all):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        findings.extend(lint_file(resolved, repo_root))

    for finding in findings:
        print(
            f"{finding.path}:{finding.line}: process-marker-placement: "
            f"the 'process' marker is collected only from {PROCESS_DIR}; "
            f"move this test under {PROCESS_DIR} or drop the marker"
        )

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
