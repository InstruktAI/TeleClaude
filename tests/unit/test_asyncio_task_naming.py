"""Static analysis: every asyncio.create_task / loop.create_task call must carry name=.

Unnamed tasks appear as generic Task-N in pressure logs, making leak diagnosis impossible.
This test fails whenever a new unnamed create_task call is introduced.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[2] / "teleclaude"

# Legitimate call sites that do NOT pass name= because they delegate naming
# to a higher-level wrapper (task_registry.spawn) in the primary branch,
# and the fallback branch used here is a secondary path where providing a
# matching name is the fix tracked by this bug.  After the fix these entries
# are removed from this allowlist.
_KNOWN_UNNAMED: frozenset[tuple[str, int]] = frozenset()


def _collect_unnamed_create_task_calls() -> list[tuple[str, int]]:
    """Return (relative_path, lineno) for every unnamed create_task call in src."""
    violations: list[tuple[str, int]] = []
    for py_file in sorted(_SRC_ROOT.rglob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match asyncio.create_task(...) and loop.create_task(...)
            is_create_task = isinstance(func, ast.Attribute) and func.attr == "create_task"
            if not is_create_task:
                continue
            has_name_kwarg = any(kw.arg == "name" for kw in node.keywords)
            if not has_name_kwarg:
                rel = str(py_file.relative_to(_SRC_ROOT.parent))
                violations.append((rel, node.lineno))
    return sorted(violations)


@pytest.mark.timeout(10)
def test_all_create_task_calls_have_name_parameter() -> None:
    """Every create_task call must include name= for diagnosable task leak reports."""
    violations = _collect_unnamed_create_task_calls()
    unnamed = [(path, line) for path, line in violations if (path, line) not in _KNOWN_UNNAMED]
    assert not unnamed, f"Found {len(unnamed)} unnamed create_task call(s) — add name= to each:\n" + "\n".join(
        f"  {path}:{line}" for path, line in unnamed
    )
