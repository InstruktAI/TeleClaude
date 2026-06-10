"""Forbid TypeScript unit tests.

Behavior is verified by human-owned functional tests bound to the feature specs,
not by agent-authored unit tests. This check fails if tracked TypeScript test
files appear outside the doctrine path under the configured frontend root.

It inspects the git index, not the working filesystem, so it reports exactly
what a commit introduces and is not fooled by pre-commit's transient
working-tree stash.
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

    return Path(path).relative_to(frontend_root).as_posix()


def _is_typescript_test(path: str) -> bool:
    return path.endswith((".test.ts", ".test.tsx"))


def main(repo_root: Path | None = None) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    frontend_root = _resolve_frontend_root(repo_root)
    result = _git_ls_files(repo_root, frontend_root)
    if result.returncode != 0:
        print("Failed to inspect tracked TypeScript files with git ls-files.", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
        sys.exit(result.returncode or 1)

    offenders = sorted(
        path
        for path in result.stdout.splitlines()
        if _is_typescript_test(path) and not DOCTRINE_TEST_PATH.fullmatch(_relative_to_frontend(path, frontend_root))
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
