#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path


def _fail(message: str) -> None:
    raise SystemExit(f"guardrails: {message}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        _fail("missing pyproject.toml")

    pyright_path = repo_root / "pyrightconfig.json"
    if not pyright_path.exists():
        _fail("missing pyrightconfig.json")

    pyright = json.loads(pyright_path.read_text(encoding="utf-8"))
    if pyright.get("typeCheckingMode") != "strict":
        _fail("pyright typeCheckingMode must be strict")

    # Keep this guardrail tight: don't allow ruff to be removed silently.
    pyproject = pyproject_path.read_text(encoding="utf-8")
    if "[tool.ruff]" not in pyproject:
        _fail("pyproject.toml must define [tool.ruff]")

    _warn_for_loose_dicts(repo_root)


def _warn_for_loose_dicts(repo_root: Path) -> None:
    """Check for loose dict typings without proper justification.

    Allows exceptions when documented with:
    - # noqa: loose-dict - Reason
    - # type: boundary - Reason

    This enforces: "You can use dict[str, object] ONLY if you document WHY."  # noqa: loose-dict - Documentation
    """
    scan_roots = [
        repo_root / "teleclaude",
        repo_root / "tests",
        repo_root / "scripts",
        repo_root / "bin",
    ]
    patterns = ("dict[str, object]", "dict[str, Any]")  # noqa: loose-dict - Pattern definition
    matches: list[str] = []
    exception_markers = ("# noqa: loose-dict", "# type: boundary")

    excluded_files = {
        repo_root / "teleclaude" / "adapters" / "redis_adapter.py",
    }

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path in excluded_files:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if any(pattern in line for pattern in patterns):
                    # Skip if line has documented exception
                    if any(marker in line for marker in exception_markers):
                        continue
                    matches.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    if not matches:
        return

    max_allowed = 145  # TODO: Reduce to 0 as we type everything (see todos/reduce-loose-dict-typings/)
    if len(matches) > max_allowed:
        _fail(f"loose dict typings detected ({len(matches)} > {max_allowed})\nFIX by replacing with typed dicts!!\n")

    if len(matches) > 0:
        sys.stderr.write("guardrails warning: loose dict typings detected\n")
        for match in matches:
            sys.stderr.write(f"  {match}\n")
    else:
        sys.stdout.write("guardrails ok: no problems detected\n")


if __name__ == "__main__":
    main()
