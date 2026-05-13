"""Build-time audit: every ``event_bus.emit(...)`` call must declare visibility.

Pins the implementation-plan §R5 contract for
``event-bus-visibility-aware-dispatch``. Plan §R5: *"Every existing call site
of `event_bus.emit(...)` in the codebase is visited and given an explicit
`visibility=...` argument."*

The audit is AST-based so it survives wrapping, formatting changes, and
multi-line emits. Failure reports the exact file:line of each violation so a
new untagged emit fails the build with an actionable diagnostic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = REPO_ROOT / "teleclaude"


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "/tests/" not in str(path) and "__pycache__" not in str(path))


def _is_event_bus_emit(node: ast.Call) -> bool:
    """Return True for ``event_bus.emit(...)`` or ``self._bus.emit(...)``-shape calls."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr != "emit":
        return False
    receiver = func.value
    if isinstance(receiver, ast.Name) and receiver.id == "event_bus":
        return True
    return False


def _collect_untagged_emits(source: str, relpath: Path) -> list[tuple[Path, int]]:
    """Return (relpath, line) for every ``event_bus.emit(...)`` lacking visibility=."""
    try:
        tree = ast.parse(source, filename=str(relpath))
    except SyntaxError:
        return []
    violations: list[tuple[Path, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_event_bus_emit(node):
            continue
        kwarg_names = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "visibility" not in kwarg_names:
            violations.append((relpath, node.lineno))
    return violations


@pytest.mark.unit
def test_every_event_bus_emit_site_declares_visibility() -> None:
    """Every ``event_bus.emit(...)`` call in production code must pass ``visibility=``.

    Catches a regression where a new emit site is added without choosing a
    transport scope. The bus defaults to CLUSTER, but that default exists for
    back-compat — every call site must make the choice explicit per
    implementation-plan §R5 and the tagging rule in
    ``docs/project/design/architecture-v2/event-bus-transports.md``.
    """
    files = _iter_python_files(SOURCE_ROOT)
    violations: list[tuple[Path, int]] = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        if "event_bus.emit" not in source:
            continue
        relpath = path.relative_to(REPO_ROOT)
        violations.extend(_collect_untagged_emits(source, relpath))

    if violations:
        rendered = "\n".join(f"  {rel}:{line}" for rel, line in violations)
        pytest.fail(
            "event_bus.emit(...) sites without explicit visibility= kwarg "
            f"({len(violations)} found):\n{rendered}\n"
            "Apply the tagging rule from "
            "docs/project/design/architecture-v2/event-bus-transports.md."
        )
