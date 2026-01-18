#!/usr/bin/env python3

from __future__ import annotations

import ast
import argparse
import json
from pathlib import Path
from typing import Iterable

PYRIGHT_TYPE_CHECKING_MODE = "typeCheckingMode"
PYRIGHT_STRICT = "strict"
RUFF_SECTION = "[tool.ruff]"
MAIN_MODULE = "__main__"


def _fail(message: str) -> None:
    raise SystemExit(f"guardrails: {message}")


class GuardrailRule:
    def __init__(
        self,
        name: str,
        file_allowlist: Iterable[Path] | None = None,
        docstring_allow_marker: str | None = None,
    ) -> None:
        self.name = name
        self.file_allowlist = set(file_allowlist or [])
        self.docstring_allow_marker = docstring_allow_marker


def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[1]

    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        _fail("missing pyproject.toml")

    pyright_path = repo_root / "pyrightconfig.json"
    if not pyright_path.exists():
        _fail("missing pyrightconfig.json")

    pyright = json.loads(pyright_path.read_text(encoding="utf-8"))
    if pyright.get(PYRIGHT_TYPE_CHECKING_MODE) != PYRIGHT_STRICT:
        _fail("pyright typeCheckingMode must be strict")

    # Keep this guardrail tight: don't allow ruff to be removed silently.
    pyproject = pyproject_path.read_text(encoding="utf-8")
    if RUFF_SECTION not in pyproject:
        _fail("pyproject.toml must define [tool.ruff]")

    args = _parse_args(argv)

    _warn_for_loose_dicts(repo_root)
    _fail_for_string_comparisons(
        repo_root,
        GuardrailRule(
            name="string-compare",
            docstring_allow_marker="guard: allow-string-compare",
        ),
        verbose=args.verbose,
    )


def _warn_for_loose_dicts(repo_root: Path) -> None:
    """Check for loose dict typings without proper justification.

    Allows exceptions when documented with:
    - # guard: loose-dict - Reason

    This enforces: "You can use dict[str, object] ONLY if you document WHY."  # guard: loose-dict
    """
    scan_roots = [
        repo_root / "teleclaude",
        repo_root / "scripts",
        repo_root / "bin",
    ]
    patterns = ("dict[str, object]", "dict[str, Any]")  # guard: loose-dict - Pattern definition
    matches: list[str] = []
    # Accept multiple marker styles for backwards compatibility
    exception_markers = (
        "# guard: loose-dict",  # New preferred style
        "# guard:loose-dict",   # No space variant
        "# noqa: loose-dict",   # Legacy (causes ruff warnings but works)
        "# type: boundary",     # Legacy (avoid - causes mypy issues)
    )

    excluded_files = {
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


def _fail_for_string_comparisons(repo_root: Path, rule: GuardrailRule, verbose: bool) -> None:
    """Disallow string literal comparisons (require enums/constants).

    Rule supports:
    - file allowlist (skip entire file)
    - function docstring allow marker (skip whole function)
    """
    scan_roots = [
        repo_root / "teleclaude",
        repo_root / "scripts",
        repo_root / "bin",
    ]
    matches: list[str] = []
    allowed: list[str] = []

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path in rule.file_allowlist:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                continue
            lines = source.splitlines()

            function_allow_lines: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node)
                    if doc and rule.docstring_allow_marker and rule.docstring_allow_marker in doc:
                        start = getattr(node, "lineno", None)
                        end = getattr(node, "end_lineno", None)
                        if start and end:
                            function_allow_lines.update(range(start, end + 1))
                        else:
                            for child in ast.walk(node):
                                lineno = getattr(child, "lineno", None)
                                if lineno:
                                    function_allow_lines.add(lineno)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not node.ops:
                    continue
                if not any(isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)) for op in node.ops):
                    continue

                # Collect all operands in the comparison (left + comparators)
                operands = [node.left, *node.comparators]
                if not any(isinstance(op, ast.Constant) and isinstance(op.value, str) for op in operands):
                    continue

                lineno = getattr(node, "lineno", None)
                if not lineno:
                    continue
                line = lines[lineno - 1]
                if lineno in function_allow_lines:
                    if verbose:
                        allowed.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")
                    continue
                matches.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")

    if matches:
        formatted = "\n".join(f"- {match}" for match in matches)
        _fail(
            f"{rule.name}: string literal comparisons detected (use enums/constants)\n"
            f"{formatted}\n"
        )
    if verbose and allowed:
        formatted = "\n".join(f"- {match}" for match in allowed)
        print(f"{rule.name}: allowed string comparisons (guarded)\n{formatted}\n")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


if __name__ == MAIN_MODULE:
    main()
