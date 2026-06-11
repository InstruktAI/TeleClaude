"""Forbid TypeScript unit tests.

Behavior is verified by human-owned functional tests bound to the feature specs,
not by agent-authored unit tests. This check fails if tracked TypeScript test
files appear outside the doctrine path under the configured frontend root.

With explicit paths, it checks only selected working-tree TypeScript test
files. With no paths or ``--all``, it checks tracked repo-wide files.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

DOCTRINE_TEST_PATH = re.compile(r"^tests/[^/]+/[^/]+\.test\.tsx?$")
DEFAULT_FRONTEND_ROOT = "frontend"


def _resolve_frontend_root(repo_root: Path) -> str:
    config_path = repo_root / "teleclaude.yml"
    if config_path.exists():
        data: object = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            frontend_root = data.get("frontend_root")
            if frontend_root:
                return str(frontend_root)
    return DEFAULT_FRONTEND_ROOT


def _git_ls_files(repo_root: Path, frontend_root: str) -> subprocess.CompletedProcess[str]:
    command = ["git", "ls-files", "--"]
    if frontend_root != ".":
        command.append(frontend_root)

    # Git index inspection has no project-native binding and must match pre-commit's staged tree.
    return subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False)


def _relative_to_frontend(path: str, frontend_root: str) -> str:
    if frontend_root == ".":
        return path

    try:
        return Path(path).relative_to(frontend_root).as_posix()
    except ValueError:
        return path


def _is_typescript_test(path: str) -> bool:
    return path.endswith((".test.ts", ".test.tsx"))


def _is_off_doctrine(path: str, frontend_root: str) -> bool:
    return _is_typescript_test(path) and not DOCTRINE_TEST_PATH.fullmatch(_relative_to_frontend(path, frontend_root))


def _repo_offenders(repo_root: Path, frontend_root: str) -> list[str]:
    result = _git_ls_files(repo_root, frontend_root)
    if result.returncode != 0:
        print("Failed to inspect tracked TypeScript files with git ls-files.", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode or 1)

    return sorted(path for path in result.stdout.splitlines() if _is_off_doctrine(path, frontend_root))


def _selected_offenders(repo_root: Path, frontend_root: str, paths: list[str]) -> list[str]:
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
                for child in path.rglob("*")
                if child.is_file() and _is_off_doctrine(child.relative_to(root).as_posix(), frontend_root)
            )
        elif _is_off_doctrine(rel, frontend_root):
            offenders.append(rel)
    return sorted(set(offenders))


def main(repo_root: Path | None = None, argv: list[str] | None = None) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    args = list(sys.argv[1:] if argv is None else argv)
    run_all = "--all" in args or not args
    paths = [arg for arg in args if arg != "--all"]

    frontend_root = _resolve_frontend_root(repo_root)
    offenders = (
        _repo_offenders(repo_root, frontend_root) if run_all else _selected_offenders(repo_root, frontend_root, paths)
    )

    if offenders:
        print("FORBIDDEN TYPESCRIPT UNIT TESTS:")
        for path in offenders:
            print(f"  {path}")
        print()
        print(f"Total: {len(offenders)} TypeScript unit test file(s).")
        print(f"TypeScript tests must bind feature-spec scenarios at {frontend_root}/tests/<domain>/<slug>.test.ts.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
