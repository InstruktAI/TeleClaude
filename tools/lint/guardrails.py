#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
import re
import tomllib
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
    pyproject = pyproject_path.read_text(encoding="utf-8")

    # Existing checks
    if pyright.get("typeCheckingMode") != "strict":
        _fail("pyright typeCheckingMode must be strict")
    if "[tool.ruff]" not in pyproject:
        _fail("pyproject.toml must define [tool.ruff]")

    # Config invariant enforcement (prevents silent erosion by agents)
    _check_pyright_invariants(pyright)
    _check_ruff_invariants(pyproject)
    _check_mypy_invariants(pyproject)
    _check_lint_pipeline_integrity(repo_root)
    _check_module_sizes(repo_root)

    # Test structure enforcement
    _check_test_companions(repo_root)

    # Existing guardrails
    _warn_for_debug_probes(repo_root)
    _fail_on_stash_commands_in_agent_artifacts(repo_root)
    _warn_for_loose_dicts(repo_root)


# ---------------------------------------------------------------------------
# Config invariant enforcement
# ---------------------------------------------------------------------------

# Frozen baselines: these caps represent the current known state.
# Raising a cap requires explicit human approval and a documented reason.
# The cap exists to make config erosion VISIBLE — not to prevent all change.

PYRIGHT_MAX_IGNORE_FILES = 8
PYRIGHT_ALLOWED_NONE_REPORTS = frozenset({
    "reportOptionalSubscript",
    "reportOptionalMemberAccess",
    "reportOptionalCall",
    "reportOptionalIterable",
    "reportOptionalContextManager",
    "reportOptionalOperand",
    "reportArgumentType",
    "reportMissingTypeStubs",
    "reportUnknownArgumentType",
    "reportUnknownMemberType",
    "reportUnknownParameterType",
    "reportUnknownVariableType",
    "reportPrivateUsage",
})

RUFF_REQUIRED_RULE_GROUPS = {"E", "F", "I", "C90", "B", "UP", "RUF"}
# guard: ratchet-down — 8 includes 5 tech-debt items (UP042, RUF012, RUF005, RUF006, B905)
RUFF_MAX_GLOBAL_IGNORES = 8
# guard: ratchet-down — 43 entries, mostly C901 complexity violations to decompose
RUFF_MAX_PER_FILE_IGNORE_ENTRIES = 43

MYPY_MAX_OVERRIDE_SECTIONS = 13
MYPY_ALLOWED_IGNORE_ERRORS_MODULES = frozenset({"teleclaude.hooks.*"})

# File size gate: max lines per module. No exceptions.
MODULE_MAX_LINES = 1000


def _check_pyright_invariants(pyright: dict[str, object]) -> None:  # guard: loose-dict-func - JSON config is untyped
    """Enforce pyright config does not silently weaken."""
    ignore_list = pyright.get("ignore", [])
    if isinstance(ignore_list, list) and len(ignore_list) > PYRIGHT_MAX_IGNORE_FILES:
        _fail(
            f"pyrightconfig.json ignore list has {len(ignore_list)} entries "
            f"(max: {PYRIGHT_MAX_IGNORE_FILES}). "
            "Do not suppress pyright errors by adding modules to the ignore list — fix the types."
        )

    actual_none_reports = {k for k, v in pyright.items() if v == "none" and k.startswith("report")}
    new_suppressed = actual_none_reports - PYRIGHT_ALLOWED_NONE_REPORTS
    if new_suppressed:
        _fail(
            f"pyrightconfig.json has new 'none' report overrides not in baseline: "
            f"{sorted(new_suppressed)}. Do not suppress pyright report categories."
        )


def _check_ruff_invariants(pyproject: str) -> None:
    """Enforce ruff lint rules are not weakened.

    Uses tomllib for correct TOML array extraction. The previous regex approach
    was broken: ] inside comments (e.g. Optional[X]) prematurely terminated
    the capture, hiding ignored rules from the cap check.
    """
    parsed = tomllib.loads(pyproject)
    ruff_lint = parsed.get("tool", {}).get("ruff", {}).get("lint", {})  # guard: loose-dict - TOML parse result is untyped

    # Required rule groups must be present in select
    selected_rules = set(ruff_lint.get("select", []))
    if not selected_rules:
        _fail("pyproject.toml: [tool.ruff.lint] select list is missing")

    missing = RUFF_REQUIRED_RULE_GROUPS - selected_rules
    if missing:
        _fail(
            f"pyproject.toml: ruff lint select is missing required rule groups: "
            f"{sorted(missing)}. Do not remove lint rules."
        )

    # Global ignore list cap
    ignored_rules = ruff_lint.get("ignore", [])
    if len(ignored_rules) > RUFF_MAX_GLOBAL_IGNORES:
        _fail(
            f"pyproject.toml: ruff global ignore list has {len(ignored_rules)} entries "
            f"(max: {RUFF_MAX_GLOBAL_IGNORES}). Fix lint issues instead of suppressing them."
        )

    # Per-file-ignores entry cap
    pfi = ruff_lint.get("per-file-ignores", {})  # guard: loose-dict - TOML parse result is untyped
    if len(pfi) > RUFF_MAX_PER_FILE_IGNORE_ENTRIES:
        _fail(
            f"pyproject.toml: ruff per-file-ignores has {len(pfi)} entries "
            f"(max: {RUFF_MAX_PER_FILE_IGNORE_ENTRIES}). "
            "Do not add broad file-level ignore rules."
        )


def _check_mypy_invariants(pyproject: str) -> None:
    """Enforce mypy overrides do not grow unchecked."""
    override_count = pyproject.count("[[tool.mypy.overrides]]")
    if override_count > MYPY_MAX_OVERRIDE_SECTIONS:
        _fail(
            f"pyproject.toml: {override_count} mypy override sections "
            f"(max: {MYPY_MAX_OVERRIDE_SECTIONS}). "
            "Do not add module-level mypy exemptions — fix the type errors."
        )

    # Check ignore_errors = true is only used for allowed modules
    override_blocks = re.split(r"\[\[tool\.mypy\.overrides\]\]", pyproject)[1:]
    for block in override_blocks:
        if "ignore_errors" not in block:
            continue
        if not re.search(r"ignore_errors\s*=\s*true", block):
            continue
        module_match = re.search(r'module\s*=\s*"([^"]+)"', block)
        if not module_match:
            continue
        module = module_match.group(1)
        if module not in MYPY_ALLOWED_IGNORE_ERRORS_MODULES:
            _fail(
                f"pyproject.toml: mypy ignore_errors=true for '{module}' is not in the "
                f"allowed baseline {sorted(MYPY_ALLOWED_IGNORE_ERRORS_MODULES)}. "
                "Fix type errors instead of blanket-ignoring them."
            )

    # Ensure strict = true is still set
    if re.search(r"^\s*strict\s*=\s*true", pyproject, re.MULTILINE) is None:
        _fail("pyproject.toml: [tool.mypy] strict must be true")


def _check_lint_pipeline_integrity(repo_root: Path) -> None:
    """Verify critical tool config files haven't been structurally weakened."""
    # .pre-commit-config.yaml: must contain required hook IDs
    precommit_path = repo_root / ".pre-commit-config.yaml"
    if precommit_path.exists():
        precommit = precommit_path.read_text(encoding="utf-8")
        for hook_id in ("commitizen", "format", "guardrails", "ruff-check", "pyright", "mypy", "pylint"):
            if f"id: {hook_id}" not in precommit:
                _fail(f".pre-commit-config.yaml: required hook '{hook_id}' is missing")

    # tools/lint.sh: must invoke guardrails, ruff, and pyright
    lint_sh_path = repo_root / "tools" / "lint.sh"
    if lint_sh_path.exists():
        lint_sh = lint_sh_path.read_text(encoding="utf-8")
        for step in ("guardrails.py", "ruff check", "$PYRIGHT", "$MYPY", "$PYLINT"):
            if step not in lint_sh:
                _fail(f"tools/lint.sh: required lint step '{step}' is missing")

    # Makefile: must contain lint and test targets
    makefile_path = repo_root / "Makefile"
    if makefile_path.exists():
        makefile = makefile_path.read_text(encoding="utf-8")
        for target in ("lint:", "test:"):
            if target not in makefile:
                _fail(f"Makefile: required target '{target}' is missing")


def _check_module_sizes(repo_root: Path) -> None:
    """Enforce max lines per Python module."""
    scan_roots = [
        repo_root / "teleclaude",
    ]
    violations: list[str] = []

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(repo_root).as_posix()
            if rel.startswith(("teleclaude/cli/tui/", "teleclaude/entrypoints/")):
                # TUI views and entrypoints have different complexity profiles
                continue
            try:
                line_count = len(path.read_text(encoding="utf-8").splitlines())
            except OSError:
                continue

            if line_count > MODULE_MAX_LINES:
                violations.append(f"{rel}: {line_count} lines (max: {MODULE_MAX_LINES})")

    if violations:
        formatted = "\n".join(f"- {v}" for v in violations)
        _fail(
            f"module size limit exceeded ({len(violations)} files).\n"
            "Decompose large modules into focused submodules.\n"
            f"{formatted}\n"
        )


# ---------------------------------------------------------------------------
# Test structure enforcement
# ---------------------------------------------------------------------------


def _check_test_companions(repo_root: Path) -> None:
    """Enforce that every test file has a corresponding source module.

    Convention: tests/unit/foo/test_bar.py must have teleclaude/foo/bar.py.
    Orphaned tests (testing deleted/renamed modules) are caught here.

    Exclusions are configured in pyproject.toml [tool.test-mapping].orphan-exclude.
    """
    tests_root = repo_root / "tests" / "unit"
    source_root = repo_root / "teleclaude"
    if not tests_root.exists() or not source_root.exists():
        return

    orphan_exclusions = _load_orphan_exclusions(repo_root)

    orphans: list[tuple[str, str]] = []
    for test_path in sorted(tests_root.rglob("test_*.py")):
        rel_test = test_path.relative_to(repo_root).as_posix()
        if rel_test in orphan_exclusions:
            continue

        expected_source = _test_to_source_path(test_path, tests_root)
        if expected_source is None:
            continue
        if not (source_root / expected_source).exists():
            full_expected = f"teleclaude/{expected_source}"
            orphans.append((rel_test, full_expected))

    if not orphans:
        return

    max_test = max(len(t) for t, _ in orphans)
    formatted = "\n".join(f"- {t:<{max_test}} -> missing: {s}" for t, s in orphans)
    _fail(
        f"orphaned test files detected ({len(orphans)} tests without source companions).\n"
        "Each test file must mirror a source module. If the test intentionally covers\n"
        "cross-module behavior, add it to [tool.test-mapping].orphan-exclude in pyproject.toml.\n"
        f"{formatted}\n"
    )


def _test_to_source_path(test_path: Path, tests_root: Path) -> str | None:
    """Derive the expected source path from a test file path.

    tests/unit/foo/test_bar.py -> foo/bar.py
    tests/unit/test_bar.py -> bar.py
    """
    rel = test_path.relative_to(tests_root)
    parts = list(rel.parts)
    filename = parts[-1]
    if not filename.startswith("test_"):
        return None
    source_filename = filename.removeprefix("test_")
    parts[-1] = source_filename
    return "/".join(parts)


def _load_orphan_exclusions(repo_root: Path) -> set[str]:
    """Load orphan-exclude paths from pyproject.toml [tool.test-mapping]."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return set()
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    return set(
        data.get("tool", {}).get("test-mapping", {}).get("orphan-exclude", [])  # guard: loose-dict - TOML parse result
    )


# ---------------------------------------------------------------------------
# Existing guardrails
# ---------------------------------------------------------------------------


def _warn_for_debug_probes(repo_root: Path) -> None:
    """Fail on leftover ad-hoc debug probes in non-test Python code."""
    scan_roots = [
        repo_root / "teleclaude",
        repo_root / "scripts",
        repo_root / "tools",
        repo_root / "bin",
    ]
    matches: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.relative_to(repo_root).as_posix()
            if rel.startswith("tools/lint/"):
                continue
            if rel.startswith("scripts/fixtures/"):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                stripped = line.strip()
                if "print(" in stripped and "DEBUG:" in stripped:
                    matches.append(f"{rel}:{lineno}: {stripped}")

    if not matches:
        return

    formatted = "\n".join(f"- {match}" for match in matches)
    _fail(
        "leftover debug probe prints detected.\n"
        "Use structured logger calls and remove temporary probes before commit.\n"
        f"{formatted}\n"
    )


def _fail_on_stash_commands_in_agent_artifacts(repo_root: Path) -> None:
    """Fail when agent instruction artifacts include git stash workflows.

    Stash state is repository-wide, so stash pop/apply is unsafe in multi-worktree automation.
    """
    scan_roots = [
        repo_root / "agents",
        repo_root / ".agents",
    ]
    # Match command-like stash usage, including common subcommands.
    stash_pattern = re.compile(r"\bgit\s+stash(?:\s+(?:pop|apply|push|drop|list|show))?\b")
    marker = "guard: allow-git-stash"
    matches: list[str] = []

    for root in scan_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.md"):
            rel = path.relative_to(repo_root).as_posix()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if marker in line:
                    continue
                if lineno > 1 and marker in lines[lineno - 2]:
                    continue
                if stash_pattern.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()}")

    if not matches:
        return

    formatted = "\n".join(f"- {match}" for match in matches)
    _fail(
        "forbidden git stash command usage detected in agent artifacts.\n"
        "Use explicit commits and worktrees instead of stash workflows.\n"
        f"{formatted}\n"
    )


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
        # External data boundaries — WebSocket payloads, JSON serialization, config
        repo_root / "teleclaude" / "api_server.py",
        repo_root / "teleclaude" / "core" / "models.py",
        repo_root / "teleclaude" / "core" / "command_mapper.py",
        repo_root / "teleclaude" / "install" / "install_hooks.py",
        repo_root / "teleclaude" / "config" / "schema.py",
        repo_root / "teleclaude" / "config" / "runtime_settings.py",
        repo_root / "teleclaude" / "types" / "commands.py",
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
                    legacy_marker_matches.append(f"{path.relative_to(repo_root)}:{lineno}: {line.strip()}")
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
