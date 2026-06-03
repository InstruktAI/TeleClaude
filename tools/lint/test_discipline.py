#!/usr/bin/env -S uv run --quiet
"""Enforce the test-resource-discipline policy via static analysis.

Detects, with file:line locations, every violation of
``software-development/policy/test-resource-discipline``:

- Per-test timeout overrides (`@pytest.mark.timeout(...)`, `pytestmark` lists
  including a timeout marker) anywhere under ``tests/``.
- The `expensive` marker (decorator or `pytestmark`) anywhere under ``tests/``.
- `pytest_runtest_protocol` hookwrapper in ``tests/conftest.py`` (the
  reaper-style per-test cost amplifier — must be marker-scoped instead).
- Module-scope imports of heavy modules in ``tests/conftest.py`` (rule 17).
- Real subprocess calls in ``tests/unit/**`` (rule 11).
- `session_timeout` in ``pyproject.toml`` differing from the value configured in `pyproject.toml` (rule 3).

Exit code 0 on success, 1 on any violation. Prints offenders as
``path:line: rule: <description>``.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

POLICY_REF = "software-development/policy/test-resource-discipline"

# Files exempt from "no real subprocess in unit tier" (rule 11). Each entry
# names a one-line reason; entries marked TODO are grandfathered violators that
# must shrink to zero over time. New entries require explicit justification.
UNIT_SUBPROCESS_EXEMPT: dict[str, str] = {
    "tests/unit/quality/test_subprocess_reaper.py": "tests the reaper itself, needs a real child",
}

# Heavy modules that must not be imported at the top level of tests/conftest.py.
HEAVY_MODULES = frozenset(
    {
        "teleclaude.core.db",
        "teleclaude.core.todos_db",
        "teleclaude.config",
        "teleclaude.cli.tui.state_store",
        "teleclaude.runtime.binaries",
        "teleclaude.core.session_cleanup",
        "teleclaude.core.session_utils",
        "sqlalchemy",
        "greenlet",
        "aiosqlite",
        "psutil",
    }
)

# Forbidden subprocess-call shapes (module.attr → forbidden attrs).
FORBIDDEN_CALLS = {
    "subprocess": frozenset({"run", "Popen", "call", "check_call", "check_output"}),
    "asyncio": frozenset({"create_subprocess_exec", "create_subprocess_shell"}),
    "os": frozenset(
        {
            "system",
            "fork",
            "execl",
            "execle",
            "execlp",
            "execlpe",
            "execv",
            "execve",
            "execvp",
            "execvpe",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
            "posix_spawn",
            "posix_spawnp",
        }
    ),
}

EXPECTED_SESSION_TIMEOUT = 40


def _violation(repo_root: Path, path: Path, lineno: int, rule: str, message: str) -> str:
    rel = path.relative_to(repo_root).as_posix()
    return f"{rel}:{lineno}: {rule}: {message}"


def _is_timeout_marker_call(node: ast.AST) -> bool:
    """Return True iff ``node`` is a ``pytest.mark.timeout(...)`` call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "timeout"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )


def _is_expensive_marker(node: ast.AST) -> bool:
    """Return True iff ``node`` is ``pytest.mark.expensive`` (call or attribute)."""
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "expensive"
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    )


def _scan_decorations(tree: ast.Module) -> Iterable[tuple[int, str]]:
    """Yield (lineno, kind) for every timeout-decoration or expensive marker."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                if _is_timeout_marker_call(dec):
                    yield dec.lineno, "timeout-decorator"
                if _is_expensive_marker(dec):
                    yield dec.lineno, "expensive-decorator"
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    value = node.value
                    items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
                    for item in items:
                        if _is_timeout_marker_call(item):
                            yield item.lineno, "pytestmark-timeout"
                        if _is_expensive_marker(item):
                            yield item.lineno, "pytestmark-expensive"


def _scan_root_conftest_imports(tree: ast.Module) -> Iterable[tuple[int, str]]:
    """Yield (lineno, module_name) for every heavy module imported at module scope."""
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module == name or module.startswith(name + ".") for name in HEAVY_MODULES):
                yield node.lineno, module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == name or alias.name.startswith(name + ".") for name in HEAVY_MODULES):
                    yield node.lineno, alias.name


def _has_root_runtest_protocol(tree: ast.Module) -> int | None:
    """Return the lineno of any ``pytest_runtest_protocol`` function definition, or None."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "pytest_runtest_protocol":
            return node.lineno
    return None


def _scan_real_subprocess(tree: ast.Module) -> Iterable[tuple[int, str]]:
    """Yield (lineno, label) for every forbidden subprocess-style call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        forbidden = FORBIDDEN_CALLS.get(func.value.id)
        if forbidden is None or func.attr not in forbidden:
            continue
        yield node.lineno, f"{func.value.id}.{func.attr}"


def collect_violations(repo_root: Path) -> list[str]:
    violations: list[str] = []
    tests_dir = repo_root / "tests"
    root_conftest = tests_dir / "conftest.py"
    pyproject = repo_root / "pyproject.toml"

    # Rule 3: session_timeout in pyproject.toml
    if pyproject.is_file():
        cfg = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        actual = cfg.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("session_timeout")
        if actual != EXPECTED_SESSION_TIMEOUT:
            violations.append(
                _violation(
                    repo_root,
                    pyproject,
                    1,
                    "rule-3",
                    f"session_timeout = {actual!r} but policy mandates {EXPECTED_SESSION_TIMEOUT}",
                )
            )

    # Rule 4 (no overrides) + expensive-marker ban — scan all tests/**/*.py
    for path in sorted(tests_dir.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for lineno, kind in _scan_decorations(tree):
            if kind in {"timeout-decorator", "pytestmark-timeout"}:
                violations.append(
                    _violation(
                        repo_root,
                        path,
                        lineno,
                        "rule-4",
                        "per-test timeout override forbidden; tier marker assigns budget centrally",
                    )
                )
            else:
                violations.append(
                    _violation(
                        repo_root,
                        path,
                        lineno,
                        "no-expensive-marker",
                        "@pytest.mark.expensive forbidden; tests that don't run aren't coverage",
                    )
                )

    # Rule 11: no real subprocess in unit tier
    unit_dir = tests_dir / "unit"
    if unit_dir.is_dir():
        for path in sorted(unit_dir.rglob("test_*.py")):
            rel = path.relative_to(repo_root).as_posix()
            if rel in UNIT_SUBPROCESS_EXEMPT:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for lineno, label in _scan_real_subprocess(tree):
                violations.append(
                    _violation(
                        repo_root,
                        path,
                        lineno,
                        "rule-11",
                        f"real subprocess ({label}) in unit tier — move to tests/functional/ or mock",
                    )
                )

    # Root conftest specific checks
    if root_conftest.is_file():
        try:
            tree = ast.parse(root_conftest.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            tree = None
        if tree is not None:
            # Rule 16: pytest_runtest_protocol must not live in root conftest
            lineno = _has_root_runtest_protocol(tree)
            if lineno is not None:
                violations.append(
                    _violation(
                        repo_root,
                        root_conftest,
                        lineno,
                        "rule-16",
                        "pytest_runtest_protocol in root conftest amplifies per-test cost across "
                        "the suite; move to tests/functional/conftest.py or tests/integration/conftest.py",
                    )
                )
            # Rule 17: no module-scope heavy imports in root conftest
            for lineno, module in _scan_root_conftest_imports(tree):
                violations.append(
                    _violation(
                        repo_root,
                        root_conftest,
                        lineno,
                        "rule-17",
                        f"heavy module {module!r} imported at module scope; defer into the fixture body",
                    )
                )

    return violations


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    violations = collect_violations(repo_root)
    if not violations:
        return 0
    print(f"\n{POLICY_REF} — violations:\n", file=sys.stderr)
    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"\n{len(violations)} violation(s). See docs/global/{POLICY_REF}.md.\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
