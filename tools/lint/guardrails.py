#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
from pathlib import Path


def _fail(message: str) -> None:
    raise SystemExit(f"guardrails: {message}")


def main() -> None:
    # tools/lint/guardrails.py -> go up 2 levels to repo root
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
        repo_root / "tools",
        repo_root / "bin",
    ]
    patterns = (
        "dict[str, object]",
        "dict[str, Any]",
        "Mapping[str, Any]",
        "MutableMapping[str, Any]",
    )  # guard: loose-dict - Pattern definition
    legacy_noqa_marker = "# noqa: loose-dict"
    matches: list[str] = []
    legacy_marker_matches: list[str] = []
    # Canonical marker styles.
    exception_markers = (
        "# guard: loose-dict",
        "# guard:loose-dict",  # No space variant
        "# guard: loose-dict-func",  # Function-scope exception marker
    )

    excluded_files = {
        repo_root / "tools" / "lint" / "guardrails.py",
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
            guarded_ranges = _collect_function_guard_ranges(lines)
            for lineno, line in enumerate(lines, start=1):
                if legacy_noqa_marker in line:
                    legacy_marker_matches.append(
                        f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}"
                    )
                if any(pattern in line for pattern in patterns):
                    # Skip if line or previous line has documented exception.
                    if _line_has_exception_marker(lines, lineno, exception_markers):
                        continue
                    if _line_in_ranges(lineno, guarded_ranges):
                        continue
                    matches.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    if legacy_marker_matches:
        formatted = "\n".join(f"- {match}" for match in legacy_marker_matches)
        _fail(
            "legacy loose-dict marker detected (# noqa: loose-dict). "
            "Use canonical guard markers instead.\n"
            "Allowed: '# guard: loose-dict - reason' or '# guard: loose-dict-func - reason'\n"
            f"{formatted}\n"
        )

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


def _collect_function_guard_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Collect line ranges guarded by function-scope loose-dict markers.

    Marker usage:
    - Add `# guard: loose-dict-func - reason` directly above a function/class def.
    - That marker exempts loose-dict checks for the entire function/class block.
    """
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end_lineno = getattr(node, "end_lineno", None)
        if end_lineno is None:
            continue
        marker_found = False
        for marker_lineno in range(max(1, node.lineno - 3), node.lineno):
            if "# guard: loose-dict-func" in lines[marker_lineno - 1]:
                marker_found = True
                break
        if marker_found:
            ranges.append((node.lineno, end_lineno))
    return ranges


def _line_in_ranges(lineno: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= lineno <= end for start, end in ranges)


def _line_has_exception_marker(lines: list[str], lineno: int, markers: tuple[str, ...]) -> bool:
    """Return True if an exception marker exists on current or preceding line."""
    current = lines[lineno - 1]
    if any(marker in current for marker in markers):
        return True

    if lineno > 1:
        previous = lines[lineno - 2]
        if any(marker in previous for marker in markers):
            return True

    return False


if __name__ == "__main__":
    main()
