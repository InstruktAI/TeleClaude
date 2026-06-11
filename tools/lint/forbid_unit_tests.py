"""Forbid unit tests.

Behavior is verified by human-owned functional and integration tests bound to
the feature specs — not by agent-authored unit tests, which grade the author's
own code and tend toward green-theater. This check fails if any unit-tier test
is tracked, enforcing the no-unit-test policy structurally instead of relying on
review to catch it.

With explicit paths, it checks only selected working-tree test files. With no
paths or ``--all``, it checks tracked repo-wide files.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _is_python_unit_test(path: str) -> bool:
    rel = Path(path).as_posix()
    return rel.startswith("tests/unit/") and rel.endswith(".py") and Path(rel).name.startswith("test_")


def _selected_offenders(repo_root: Path, paths: list[str]) -> list[str]:
    offenders: list[str] = []
    root = repo_root.resolve()
    for raw in paths:
        candidate = Path(raw)
        path = candidate if candidate.is_absolute() else root / candidate
        try:
            rel = path.resolve(strict=False).relative_to(root).as_posix()
        except ValueError:
            continue
        if path.is_dir():
            offenders.extend(
                child.relative_to(root).as_posix()
                for child in path.rglob("test_*.py")
                if _is_python_unit_test(child.relative_to(root).as_posix())
            )
        elif _is_python_unit_test(rel):
            offenders.append(rel)
    return sorted(set(offenders))


def _repo_offenders(repo_root: Path) -> list[str]:
    # Git index inspection has no project-native binding and is the repo-wide tracked-file contract.
    result = subprocess.run(
        ["git", "ls-files", "--", "tests/unit"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return sorted(line for line in result.stdout.splitlines() if _is_python_unit_test(line))


def main(repo_root: Path | None = None, argv: list[str] | None = None) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    args = list(sys.argv[1:] if argv is None else argv)
    run_all = "--all" in args or not args
    paths = [arg for arg in args if arg != "--all"]

    offenders = _repo_offenders(repo_root) if run_all else _selected_offenders(repo_root, paths)

    if offenders:
        print("FORBIDDEN UNIT TESTS:")
        for path in offenders:
            print(f"  {path}")
        print()
        print(f"Total: {len(offenders)} unit test file(s).")
        print("Unit tests are not permitted. Behavior is verified by functional/integration")
        print("tests bound to the feature specs — move coverage there or delete the test.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
