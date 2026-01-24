#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path


def _fail(message: str) -> None:
    raise SystemExit(f"guardrails: {message}")


def main() -> None:
    # bin/lint/guardrails.py -> go up 2 levels to repo root
    repo_root = Path(__file__).resolve().parents[2]

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
    - # guard: loose-dict - Reason

    This enforces: "You can use dict[str, object] ONLY if you document WHY."  # guard: loose-dict
    """
    scan_roots = [
        repo_root / "teleclaude",
        repo_root / "tests",
        repo_root / "scripts",
        repo_root / "bin",
    ]
    patterns = ("dict[str, object]", "dict[str, Any]")  # guard: loose-dict - Pattern definition
    matches: list[str] = []
    # Accept multiple marker styles for backwards compatibility
    exception_markers = (
        "# guard: loose-dict",  # New preferred style
        "# guard:loose-dict",  # No space variant
        "# noqa: loose-dict",  # Legacy (causes ruff warnings but works)
        "# type: boundary",  # Legacy (avoid - causes mypy issues)
    )

    excluded_files = {
        repo_root / "teleclaude" / "adapters" / "redis_adapter.py",
        repo_root / "teleclaude" / "transport" / "redis_transport.py",
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

    max_allowed = 0  # TODO: Reduce to 0 as we type everything (see todos/reduce-loose-dict-typings/)
    if len(matches) > max_allowed:
        formatted = "\n".join(f"- {match}" for match in matches)
        _fail(
            "loose dict typings detected "
            f"({len(matches)} > {max_allowed})\n"
            "FIX by replacing with typed dicts!!\n"
            f"{formatted}\n"
        )

    if len(matches) > 0:
        _fail("guardrails warning: loose dict typings detected\n")


if __name__ == "__main__":
    main()
