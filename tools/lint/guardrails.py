#!/usr/bin/env python3
"""Project lint guardrails for repo-wide and staged-file validation."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import re
import tokenize
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple


def _fail(message: str) -> None:
    """Abort guardrails execution with a formatted failure message."""
    raise SystemExit(f"guardrails: {message}")


_REPO_INVARIANT_INPUTS = frozenset(
    {
        ".pre-commit-config.yaml",
        "Makefile",
        "pyproject.toml",
        "pyrightconfig.json",
        "tools/lint.sh",
    }
)

_STARTUP_BOUNDARY_IMPORT_ALLOWLIST = frozenset(
    {
        "teleclaude/daemon.py",
        "teleclaude/daemon_event_platform.py",
        "teleclaude/core/adapter_client/_client.py",
    }
)
_STARTUP_BOUNDARY_IMPORT_REASON = "startup boundary"
MODULE_SIZE_EXCEPTIONS = frozenset(
    {
        "teleclaude/daemon.py",
        "teleclaude/cli/telec/surface.py",  # declarative CLI schema registry, not logic
    }
)


def main(argv: Sequence[str] | None = None) -> None:
    """Run repo-wide or selected-file guardrails."""
    parser = argparse.ArgumentParser(description="Run TeleClaude lint guardrails.")
    parser.add_argument("paths", nargs="*", help="Optional repo-relative files to scope the checks to.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    # tools/lint/guardrails.py -> go up 2 levels to repo root
    repo_root = Path(__file__).resolve().parents[2]
    selected_paths = _normalize_selected_paths(repo_root, args.paths)

    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        _fail("missing pyproject.toml")

    pyright_path = repo_root / "pyrightconfig.json"
    if not pyright_path.exists():
        _fail("missing pyrightconfig.json")

    pyright = json.loads(pyright_path.read_text(encoding="utf-8"))
    pyproject = pyproject_path.read_text(encoding="utf-8")

    if _should_run_repo_invariants(selected_paths):
        # Repo-wide invariants should only fire on repo-wide lint runs or when one of
        # their owning files is actually part of the staged selection.
        if pyright.get("typeCheckingMode") != "strict":
            _fail("pyright typeCheckingMode must be strict")
        if "[tool.ruff]" not in pyproject:
            _fail("pyproject.toml must define [tool.ruff]")

        # Config invariant enforcement (prevents silent erosion by agents)
        _check_pyright_invariants(pyright)
        _check_ruff_invariants(pyproject)
        _check_mypy_invariants(pyproject)
        _check_lint_pipeline_integrity(repo_root)

    # Test structure enforcement
    _check_module_sizes(repo_root, selected_paths)
    _check_no_companion_markers(repo_root, selected_paths)
    _check_test_companions(repo_root, selected_paths)

    # Source pattern guardrails (table-driven)
    _check_source_patterns(repo_root, selected_paths)
    _check_import_outside_toplevel_policy(repo_root, selected_paths)

    # Existing guardrails
    _remove_empty_claude_md(repo_root, selected_paths)
    _warn_for_loose_dicts(repo_root, selected_paths)


def _normalize_selected_paths(repo_root: Path, raw_paths: Sequence[str]) -> set[str] | None:
    """Normalize raw path arguments to repo-relative POSIX paths."""
    if not raw_paths:
        return None

    normalized: set[str] = set()
    for raw in raw_paths:
        candidate = Path(raw)
        try:
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (repo_root / candidate).resolve(strict=False)
            )
            rel = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        normalized.add(rel)
    return normalized


def _should_run_repo_invariants(selected_paths: set[str] | None) -> bool:
    """Return True when repo-wide invariants should run for the current selection."""
    if selected_paths is None:
        return True
    return any(path in _REPO_INVARIANT_INPUTS for path in selected_paths)


def _iter_selected_files(
    repo_root: Path,
    selected_paths: set[str] | None,
    *,
    prefixes: tuple[str, ...] = (),
    suffixes: tuple[str, ...] = (),
) -> Iterable[Path]:
    """Yield selected files that match the provided repo-relative constraints."""
    if selected_paths is None:
        return

    for rel in sorted(selected_paths):
        if prefixes and not rel.startswith(prefixes):
            continue
        if suffixes and not rel.endswith(suffixes):
            continue
        candidate = repo_root / rel
        if candidate.is_file():
            yield candidate


# ---------------------------------------------------------------------------
# Config invariant enforcement
# ---------------------------------------------------------------------------

# Frozen baselines: these caps represent the current known state.
# Raising a cap requires explicit human approval and a documented reason.
# The cap exists to make config erosion VISIBLE — not to prevent all change.

PYRIGHT_MAX_IGNORE_FILES = 8
PYRIGHT_ALLOWED_NONE_REPORTS = frozenset(
    {
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
    }
)

RUFF_REQUIRED_RULE_GROUPS = {"E", "F", "I", "C90", "B", "UP", "RUF"}
# guard: ratchet-down — 8 includes 5 tech-debt items (UP042, RUF012, RUF005, RUF006, B905)
RUFF_MAX_GLOBAL_IGNORES = 8
# guard: ratchet-down — 50 entries after rlf-peripherals module decomposition
# (monoliths split into packages, each submodule inherits parent's ignores)
RUFF_MAX_PER_FILE_IGNORE_ENTRIES = 50

MYPY_MAX_OVERRIDE_SECTIONS = 13
MYPY_ALLOWED_IGNORE_ERRORS_MODULES = frozenset({"teleclaude.hooks.*"})

# File size gate: max lines per module. Exceptions require explicit allowlisting.
MODULE_MAX_LINES = 1000
ORPHAN_EXCLUDE_MAX_ENTRIES = 64


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
    ruff_lint = (
        parsed.get("tool", {}).get("ruff", {}).get("lint", {})
    )  # guard: loose-dict - TOML parse result is untyped

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
    # .pre-commit-config.yaml: must contain required hook IDs.
    # When telec code lint consolidates the pipeline, ruff-check and typecheck are
    # subsumed by the guardrails hook entry — only require them when telec code lint
    # is not configured as the guardrails entry.
    precommit_path = repo_root / ".pre-commit-config.yaml"
    if precommit_path.exists():
        precommit = precommit_path.read_text(encoding="utf-8")
        for hook_id in ("commitizen", "format", "guardrails"):
            if f"id: {hook_id}" not in precommit:
                _fail(f".pre-commit-config.yaml: required hook '{hook_id}' is missing")
        if "telec code lint" not in precommit:
            for hook_id in ("ruff-check", "typecheck"):
                if f"id: {hook_id}" not in precommit:
                    _fail(f".pre-commit-config.yaml: required hook '{hook_id}' is missing")

    # Makefile: must contain lint, test, and format targets
    makefile_path = repo_root / "Makefile"
    if makefile_path.exists():
        makefile = makefile_path.read_text(encoding="utf-8")
        for target in ("lint:", "test:", "format:"):
            if target not in makefile:
                _fail(f"Makefile: required target '{target}' is missing")


def _check_module_sizes(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Enforce max lines per Python module."""
    violations: list[str] = []
    candidates: Iterable[Path]
    if selected_paths is None:
        candidates = (path for path in (repo_root / "teleclaude").rglob("*.py"))
    else:
        candidates = _iter_selected_files(repo_root, selected_paths, prefixes=("teleclaude/",), suffixes=(".py",))

    for path in candidates:
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(("teleclaude/cli/tui/", "teleclaude/entrypoints/")):
            # TUI views and entrypoints have different complexity profiles
            continue
        if rel in MODULE_SIZE_EXCEPTIONS:
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


def _check_test_companions(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Enforce that every test file has a corresponding source module.

    Convention: tests/unit/foo/test_bar.py must have teleclaude/foo/bar.py.
    Orphaned tests (testing deleted/renamed modules) are caught here.

    Exclusions: classify intentional orphans in [tool.test-mapping].orphan-exclude.
    """
    tests_root = repo_root / "tests" / "unit"
    source_root = repo_root / "teleclaude"
    if not tests_root.exists() or not source_root.exists():
        return

    orphan_exclusions = _load_orphan_exclusions(repo_root)

    orphans: list[tuple[str, str]] = []
    if selected_paths is None:
        candidates = sorted(tests_root.rglob("test_*.py"))
    else:
        candidates = [
            path
            for path in _iter_selected_files(repo_root, selected_paths, prefixes=("tests/unit/",), suffixes=(".py",))
            if path.name.startswith("test_")
        ]

    no_companion_markers = _find_no_companion_markers(repo_root, candidates)
    if no_companion_markers:
        formatted_markers = "\n".join(f"- {item}" for item in no_companion_markers)
        _fail(
            f"retired local # guard: no-companion markers detected ({len(no_companion_markers)} markers).\n"
            "Classify the test in pyproject.toml [tool.test-mapping].orphan-exclude instead.\n"
            f"{formatted_markers}\n"
        )

    for test_path in candidates:
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
        "a package boundary or cross-module behavior, classify it in pyproject.toml\n"
        "[tool.test-mapping].orphan-exclude with a precise boundary comment.\n"
        f"{formatted}\n"
    )


def _check_no_companion_markers(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Reject ``# guard: no-companion`` markers in test files.

    Test files do not own companion exceptions. Source-side exceptions belong on
    source files; temporary orphan-test exceptions belong in the central
    ratchet list.
    """
    tests_root = repo_root / "tests"
    if not tests_root.exists():
        return

    if selected_paths is None:
        candidates = sorted(tests_root.rglob("*.py"))
    else:
        candidates = [
            path for path in _iter_selected_files(repo_root, selected_paths, prefixes=("tests/",), suffixes=(".py",))
        ]

    violations = _find_no_companion_markers(repo_root, candidates)
    if violations:
        formatted = "\n".join(f"- {path}" for path in violations)
        _fail(
            "test files may not use '# guard: no-companion'.\n"
            "Use the mirrored test path, or add a temporary centralized ratchet entry\n"
            "to pyproject.toml [tool.test-mapping].orphan-exclude.\n"
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


def _find_no_companion_markers(repo_root: Path, test_paths: Iterable[Path]) -> list[str]:
    """Return real local no-companion marker comments in test files."""
    matches: list[str] = []
    for test_path in test_paths:
        try:
            text = test_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tokens = tokenize.generate_tokens(io.StringIO(text).readline)
            for token in tokens:
                if token.type == tokenize.COMMENT and token.string.strip() == "# guard: no-companion":
                    rel = test_path.relative_to(repo_root).as_posix()
                    matches.append(f"{rel}:{token.start[0]}")
        except tokenize.TokenError:
            continue
    return matches


def _load_orphan_exclusions(repo_root: Path) -> set[str]:
    """Load orphan-exclude paths from pyproject.toml [tool.test-mapping]."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        return set()
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    entries = (
        data.get("tool", {}).get("test-mapping", {}).get("orphan-exclude", [])
    )  # guard: loose-dict - TOML parse result
    if not isinstance(entries, list):
        return set()
    string_entries = [entry for entry in entries if isinstance(entry, str)]
    if len(string_entries) > ORPHAN_EXCLUDE_MAX_ENTRIES:
        _fail(
            "pyproject.toml [tool.test-mapping].orphan-exclude has "
            f"{len(string_entries)} entries (max: {ORPHAN_EXCLUDE_MAX_ENTRIES}). "
            "Classify and move/delete tests before growing the central orphan list."
        )
    return set(string_entries)


# ---------------------------------------------------------------------------
# Existing guardrails
# ---------------------------------------------------------------------------


def _remove_empty_claude_md(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Find and remove empty CLAUDE.md files from the filesystem.

    CLAUDE.md is gitignored, so these are always untracked files created by
    agent sessions. They pollute Claude's startup context loading without
    providing value.

    A CLAUDE.md is considered empty if — after stripping <claude-mem-context>
    wrapper tags and whitespace — no content remains. Files with real content
    (e.g. @./AGENTS.md references) are left alone.
    """
    empty: list[str] = []
    if selected_paths is None:
        candidates = sorted(repo_root.rglob("CLAUDE.md"))
    else:
        candidates = [path for path in _iter_selected_files(repo_root, selected_paths) if path.name == "CLAUDE.md"]

    for path in candidates:
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith("trees/"):
            continue
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        cleaned = re.sub(r"</?claude-mem-context>", "", content).strip()
        if cleaned:
            continue
        empty.append(rel)

    if empty:
        formatted = "\n".join(f"  - {r}" for r in empty)
        _fail(
            f"empty CLAUDE.md file(s) detected:\n"
            f"{formatted}\n"
            "Delete these files — they have no content. "
            "Legitimate CLAUDE.md files are generated from AGENTS.master.md."
        )


class PatternRule(NamedTuple):
    """Declarative source-hygiene rule scanned by guardrails."""

    name: str
    pattern: re.Pattern[str]
    scan_dirs: list[str]
    glob: str | list[str]  # single glob or list of globs
    exclude_prefixes: tuple[str, ...]
    exception_marker: str | None  # None = no exceptions allowed
    message: str


SOURCE_PATTERN_RULES: list[PatternRule] = [
    PatternRule(
        name="invalid-noqa",
        pattern=re.compile(r"#\s*noqa:\s*[a-z]"),
        scan_dirs=["teleclaude", "tests", "scripts", "tools"],
        glob="*.py",
        exclude_prefixes=("tools/lint/",),
        exception_marker=None,
        message="invalid # noqa directive — use ruff codes (# noqa: E501) or guard markers (# guard: raw-sql)",
    ),
    PatternRule(
        name="debug-probes",
        pattern=re.compile(r"print\(.*DEBUG:"),
        scan_dirs=["teleclaude", "scripts", "tools", "bin"],
        glob="*.py",
        exclude_prefixes=("tools/lint/", "scripts/fixtures/"),
        exception_marker=None,
        message="leftover debug probes — use structured logging",
    ),
    PatternRule(
        name="stash-in-artifacts",
        pattern=re.compile(r"\bgit\s+stash(?:\s+(?:pop|apply|push|drop|list|show))?\b"),
        scan_dirs=["agents", ".agents"],
        glob="*.md",
        exclude_prefixes=(),
        exception_marker="guard: allow-git-stash",
        message="git stash in agent artifacts — use commits and worktrees",
    ),
    PatternRule(
        name="banned-session-env-vars",
        pattern=re.compile(r"TELECLAUDE_SESSION" + r"_ID|TELECLAUDE_PRINCIPAL" + r"(?:_ROLE)?(?!\s*=)"),
        scan_dirs=["teleclaude", "scripts", "tests", ".githooks"],
        glob="*.py",
        exclude_prefixes=("tools/lint/",),
        exception_marker=None,
        message=(
            "banned env var — use teleclaude.session_identity.get_session_id() "
            "for session ID, DB lookup for principal/role"
        ),
    ),
    PatternRule(
        name="hardcoded-home-path",
        pattern=re.compile(re.escape(str(Path.home()))),
        scan_dirs=["teleclaude", "templates", "bin", "scripts", "tools", "agents", ".agents"],
        glob=["*.py", "*.sh", "*.md", "*.yml", "*.yaml", "*.toml", "*.plist", "*.ts", "*.tsx"],
        exclude_prefixes=("tools/lint/guardrails", "__pycache__/"),
        exception_marker="guard: allow-home-path",
        message=("hardcoded home path — use Path.home(), $HOME, os.path.expanduser('~'), or {{MARKER}} in templates"),
    ),
    PatternRule(
        name="no-parametrize-in-tests",
        pattern=re.compile(r"@pytest\.mark\.parametrize\b|@pytest\.fixture\([^)]*\bparams\s*="),
        scan_dirs=["tests"],
        glob="*.py",
        exclude_prefixes=(),
        exception_marker="guard: parametrize-cleanup-pending",
        message=(
            "@pytest.mark.parametrize / fixture(params=) is forbidden — the unit of testing is the "
            "code-coverage path, not the input row. Multiple inputs through the same path are redundant; "
            'keep one test per path with one representative input. Cleanup is NOT "split into N tests, '
            'one per row" — identify the distinct paths, keep one test per path, delete the rest. '
            "See software-development/policy/testing anti-pattern #23. "
            "Existing sites awaiting cleanup may carry a `# guard: parametrize-cleanup-pending` marker on "
            "the line above; new code may not use that marker"
        ),
    ),
]


def _check_source_patterns(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Table-driven pattern scanner for source hygiene rules."""
    for rule in SOURCE_PATTERN_RULES:
        matches: list[str] = []
        for path in _iter_rule_candidate_paths(repo_root, rule, selected_paths):
            rel = path.relative_to(repo_root).as_posix()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, start=1):
                if rule.exception_marker and rule.exception_marker in line:
                    continue
                if rule.exception_marker and lineno > 1 and rule.exception_marker in lines[lineno - 2]:
                    continue
                if rule.pattern.search(line):
                    matches.append(f"{rel}:{lineno}: {line.strip()}")
        if matches:
            formatted = "\n".join(f"- {m}" for m in matches)
            _fail(f"{rule.name}: {rule.message}\n{formatted}\n")


def _iter_rule_candidate_paths(
    repo_root: Path,
    rule: PatternRule,
    selected_paths: set[str] | None,
) -> Iterable[Path]:
    """Yield files that should be scanned for a given pattern rule."""
    globs = rule.glob if isinstance(rule.glob, list) else [rule.glob]

    if selected_paths is None:
        for dirname in rule.scan_dirs:
            root = repo_root / dirname
            if not root.exists():
                continue
            for glob in globs:
                for path in root.rglob(glob):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(repo_root).as_posix()
                    if any(rel.startswith(prefix) for prefix in rule.exclude_prefixes):
                        continue
                    yield path
        return

    for rel in sorted(selected_paths):
        if not any(rel == dirname or rel.startswith(f"{dirname}/") for dirname in rule.scan_dirs):
            continue
        if any(rel.startswith(prefix) for prefix in rule.exclude_prefixes):
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        if not any(fnmatch.fnmatch(path.name, glob) for glob in globs):
            continue
        yield path


def _check_import_outside_toplevel_policy(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Enforce that noqa suppression of PLC0415 only appears in allowlisted files.

    Ruff enforces PLC0415 (import-outside-top-level). The per-file-ignores in
    pyproject.toml allow the 3 startup-boundary files. This guardrail catches
    agents trying to add inline ``# noqa: PLC0415`` in any other file.
    """
    outside_allowlist: list[str] = []
    missing_startup_reason: list[str] = []
    startup_reason_outside_allowlist: list[str] = []

    candidates: Iterable[Path]
    if selected_paths is None:
        candidates = (
            path
            for root_name in ("teleclaude", "tests", "tools", "bin")
            for path in (repo_root / root_name).rglob("*.py")
            if path.is_file()
        )
    else:
        candidates = _iter_selected_files(
            repo_root,
            selected_paths,
            prefixes=("teleclaude/", "tests/", "tools/", "bin/"),
            suffixes=(".py",),
        )

    for path in candidates:
        rel = path.relative_to(repo_root).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(lines, start=1):
            # Only match actual noqa directives on import lines, not string
            # literals or docstrings that mention the rule.
            stripped = line.lstrip()
            if not stripped.startswith(("from ", "import ")):
                continue
            is_nested_import = len(line) != len(stripped)
            has_startup_reason = f"# {_STARTUP_BOUNDARY_IMPORT_REASON}" in line
            if _is_type_checking_import(lines, lineno - 1):
                continue
            if rel in _STARTUP_BOUNDARY_IMPORT_ALLOWLIST:
                if is_nested_import and not has_startup_reason:
                    missing_startup_reason.append(f"{rel}:{lineno}: {line.strip()}")
                continue
            if has_startup_reason:
                startup_reason_outside_allowlist.append(f"{rel}:{lineno}: {line.strip()}")
            if "# noqa:" in line and "PLC0415" in line.split("# noqa:")[-1]:
                outside_allowlist.append(f"{rel}:{lineno}: {line.strip()}")

    if missing_startup_reason:
        formatted = "\n".join(f"- {item}" for item in missing_startup_reason)
        _fail(
            "startup-boundary import-outside-top-level imports must include the "
            f"same-line reason '# {_STARTUP_BOUNDARY_IMPORT_REASON}'.\n"
            f"{formatted}"
        )

    if startup_reason_outside_allowlist:
        formatted = "\n".join(f"- {item}" for item in startup_reason_outside_allowlist)
        allowlist = "\n".join(f"  - {path}" for path in sorted(_STARTUP_BOUNDARY_IMPORT_ALLOWLIST))
        _fail(f"startup-boundary import reason is only allowed in approved files:\n{allowlist}\n{formatted}")

    if outside_allowlist:
        formatted = "\n".join(f"- {item}" for item in outside_allowlist)
        allowlist = "\n".join(f"  - {path}" for path in sorted(_STARTUP_BOUNDARY_IMPORT_ALLOWLIST))
        _fail(
            "PLC0415 (import-outside-top-level) noqa suppression is only allowed in "
            "startup-boundary files:\n"
            f"{allowlist}\n"
            "Remove the noqa comment and move the import to the top of the file.\n"
            f"{formatted}"
        )


def _is_type_checking_import(lines: Sequence[str], line_index: int) -> bool:
    """Return True when a nested import line belongs to a TYPE_CHECKING block."""
    line = lines[line_index]
    stripped = line.lstrip()
    if len(line) == len(stripped):
        return False
    indent = len(line) - len(stripped)
    for previous in range(line_index - 1, -1, -1):
        previous_line = lines[previous]
        previous_stripped = previous_line.strip()
        if not previous_stripped or previous_stripped.startswith("#"):
            continue
        previous_indent = len(previous_line) - len(previous_line.lstrip())
        if previous_indent < indent:
            return previous_stripped.startswith("if TYPE_CHECKING:")
    return False


def _warn_for_loose_dicts(repo_root: Path, selected_paths: set[str] | None = None) -> None:
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
        repo_root / "teleclaude" / "install" / "configure_agent_cli.py",
        repo_root / "teleclaude" / "config" / "schema.py",
        repo_root / "teleclaude" / "config" / "runtime_settings.py",
        repo_root / "teleclaude" / "types" / "commands.py",
    }

    candidate_paths: Iterable[Path]
    if selected_paths is None:
        candidate_paths = (path for root in scan_roots if root.exists() for path in root.rglob("*.py"))
    else:
        candidate_paths = _iter_selected_files(
            repo_root,
            selected_paths,
            prefixes=("teleclaude/", "tests/", "scripts/", "tools/", "bin/"),
            suffixes=(".py",),
        )

    for path in candidate_paths:
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

    max_allowed = 0  # Guardrail budget must stay at zero until all loose dicts are typed.
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
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
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

# Appended by migration: banned session env vars rule
# (rule is in SOURCE_PATTERN_RULES but appended here to avoid self-match during edit)
