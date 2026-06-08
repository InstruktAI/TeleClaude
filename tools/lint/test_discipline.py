#!/usr/bin/env python3
"""Reject env-mutation patterns for controlled TELECLAUDE_* vars.

RuntimeConfig owns the one-shot path controls, and lifecycle dispatch carries
project paths on typed payloads. Code that mutates these values through process
env bypasses those seams.

Rejected patterns (anywhere in teleclaude/** or tests/**/conftest.py):
  - os.environ[<KEY>] = ...            # direct assignment
  - os.environ.setdefault(<KEY>, ...)  # conditional set
  - os.environ.update({<KEY>: ...})    # bulk set
  - os.putenv(<KEY>, ...)              # POSIX set
  - monkeypatch.setenv(<KEY>, ...)     # pytest env mutation

where <KEY> matches one of the six controlled vars:
  TELECLAUDE_HOME, TELECLAUDE_CONFIG_PATH, TELECLAUDE_PROJECT_CONFIG_PATH,
  TELECLAUDE_ENV_PATH, TELECLAUDE_SESSION_TMPDIR_BASE, TELECLAUDE_PROJECT_PATH

Usage:
    uv run python tools/lint/test_discipline.py [--check]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_CONTROLLED_VARS = (
    "TELECLAUDE_HOME",
    "TELECLAUDE_CONFIG_PATH",
    "TELECLAUDE_PROJECT_CONFIG_PATH",
    "TELECLAUDE_ENV_PATH",
    "TELECLAUDE_SESSION_TMPDIR_BASE",
    "TELECLAUDE_PROJECT_PATH",
)

_CONTROLLED_VAR_SET = frozenset(_CONTROLLED_VARS)
_ALLOWED_READ_IN_RUNTIME_CONFIG = Path("teleclaude/runtime/config.py")


def _is_scanned_file(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root).as_posix()
    # Production code under teleclaude/ (excluding runtime/config.py which owns its env-read seam)
    if rel.startswith("teleclaude/") and Path(rel) != _ALLOWED_READ_IN_RUNTIME_CONFIG:
        return True
    # Test conftest files
    if rel.startswith("tests/") and path.name == "conftest.py":
        return True
    return False


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_no, matched_var, source_line) for each violation."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise RuntimeError(f"cannot scan {path}: {exc}") from exc

    lines = source.splitlines()
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        matched_var = _matched_mutation_var(node)
        if matched_var is None:
            continue
        lineno = getattr(node, "lineno", 0)
        source_line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        hits.append((lineno, matched_var, source_line))
    return hits


def _matched_mutation_var(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            matched = _controlled_environ_subscript(target)
            if matched is not None:
                return matched
        return None

    if not isinstance(node, ast.Call):
        return None

    if _is_attr_call(node, "os", "putenv") or _is_attr_call(node, "monkeypatch", "setenv"):
        return _first_controlled_arg(node)

    if isinstance(node.func, ast.Attribute) and _is_os_environ(node.func.value):
        if node.func.attr == "setdefault":
            return _first_controlled_arg(node)
        if node.func.attr == "update":
            return _first_controlled_mapping_key(node)

    return None


def _controlled_environ_subscript(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript) or not _is_os_environ(node.value):
        return None
    return _controlled_string(node.slice)


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _is_attr_call(node: ast.Call, value_name: str, attr: str) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == value_name
    )


def _first_controlled_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    return _controlled_string(node.args[0])


def _first_controlled_mapping_key(node: ast.Call) -> str | None:
    for arg in node.args:
        if isinstance(arg, ast.Dict):
            for key in arg.keys:
                matched = _controlled_string(key)
                if matched is not None:
                    return matched
    for keyword in node.keywords:
        matched = _controlled_string(keyword.value)
        if matched is not None:
            return matched
    return None


def _controlled_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _CONTROLLED_VAR_SET:
        return node.value
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parents[2]

    violations: list[tuple[str, int, str, str]] = []

    py_files = [
        p
        for p in sorted(repo_root.rglob("*.py"))
        if not any(part.startswith(".") for part in p.parts) and _is_scanned_file(p, repo_root)
    ]

    for path in py_files:
        for lineno, var, source_line in _scan_file(path):
            rel = path.relative_to(repo_root).as_posix()
            violations.append((rel, lineno, var, source_line))

    if not violations:
        if "--check" not in args:
            print("test-discipline: OK - no env-mutation violations found.")
        return 0

    for rel, lineno, var, source_line in violations:
        print(f"{rel}:{lineno}: mutation of {var} via os.environ / monkeypatch.setenv")
        print(f"    {source_line}")

    print(
        f"\nERROR: {len(violations)} env-mutation violation(s) found.\n"
        "Use set_runtime_config(RuntimeConfig(...)) instead of env mutation.\n"
        "See teleclaude/runtime/config.py for the controlled seam.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
