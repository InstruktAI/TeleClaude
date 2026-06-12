#!/usr/bin/env python3
"""Project lint guardrails for repo-wide and staged-file validation."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple


def _fail(message: str) -> None:
    """Abort guardrails execution with a formatted failure message."""
    raise SystemExit(f"guardrails: {message}")


MODULE_SIZE_EXCEPTIONS = frozenset(
    {
        "teleclaude/daemon.py",
        "teleclaude/cli/telec/surface.py",  # declarative CLI schema registry, not logic
        "teleclaude/hooks/receiver/__init__.py",  # pre-existing >1000-line receiver; decomposition tracked separately
        "teleclaude/core/todos_db/_roadmap.py",
    }
)

# File size gate: max lines per module. Exceptions require explicit allowlisting.
MODULE_MAX_LINES = 1000


class RuntimePathBypass(NamedTuple):
    """Structured runtime path bypass diagnostic before rendering."""

    rel_path: str
    line_number: int
    source_line: str


def main(argv: Sequence[str] | None = None) -> None:
    """Run repo-wide or selected-file guardrails."""
    parser = argparse.ArgumentParser(description="Run TeleClaude lint guardrails.")
    parser.add_argument("paths", nargs="*", help="Optional repo-relative files to scope the checks to.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    # tools/lint/guardrails.py -> go up 2 levels to repo root
    repo_root = Path(__file__).resolve().parents[2]
    selected_paths = _normalize_selected_paths(repo_root, args.paths)

    # Module size gate
    _check_module_sizes(repo_root, selected_paths)

    # Source pattern guardrails (table-driven)
    _check_source_patterns(repo_root, selected_paths)
    _check_runtime_path_bypasses(repo_root, selected_paths)

    # Loose-dict typing guardrail
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
# Module size gate
# ---------------------------------------------------------------------------


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
# Source pattern guardrails
# ---------------------------------------------------------------------------


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
        name="divergent-kind-vocabulary",
        pattern=re.compile(r"""\bkind\s*(?::\s*\w+\s*)?=(?!=)\s*["'](?:feature|change|bug)["']"""),
        scan_dirs=["teleclaude"],
        glob="*.py",
        exclude_prefixes=(
            "teleclaude/types/todo_kind.py",  # canonical definitions live here only
            "tools/lint/",
        ),
        exception_marker="guard: kind-vocabulary-override",
        message=(
            "raw kind string literal assigned outside the canonical module — "
            "import from teleclaude.types.todo_kind instead of hard-coding kind values. "
            "Every layer must use the canonical constants; divergent vocabularies "
            "caused the bug this rule prevents. "
            "If a legitimate exception exists, add `# guard: kind-vocabulary-override` on the line."
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


# ---------------------------------------------------------------------------
# Runtime path bypass guardrail
# ---------------------------------------------------------------------------


def _check_runtime_path_bypasses(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Reject TeleClaude runtime state paths that bypass teleclaude.paths."""
    matches = _collect_runtime_path_bypasses(repo_root, selected_paths)
    if matches:
        formatted = "\n".join(f"- {match.rel_path}:{match.line_number}: {match.source_line}" for match in matches)
        _fail(f"teleclaude-runtime-path-bypass: use teleclaude.paths as the single runtime path authority\n{formatted}")


def _collect_runtime_path_bypasses(repo_root: Path, selected_paths: set[str] | None = None) -> list[RuntimePathBypass]:
    """Collect TeleClaude runtime state paths that bypass teleclaude.paths."""
    matches: list[RuntimePathBypass] = []
    candidates: Iterable[Path]
    if selected_paths is None:
        candidates = (
            path
            for root_name in ("teleclaude", "tests", "scripts", "tools")
            for path in (repo_root / root_name).rglob("*.py")
            if path.is_file()
        )
    else:
        candidates = _iter_selected_files(
            repo_root,
            selected_paths,
            prefixes=("teleclaude/", "tests/", "scripts/", "tools/"),
            suffixes=(".py",),
        )

    for path in candidates:
        rel = path.relative_to(repo_root).as_posix()
        if rel in {"teleclaude/paths.py", "teleclaude/runtime/config.py", "tools/lint/guardrails.py"}:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if _is_teleclaude_home_bypass(node):
                lineno = getattr(node, "lineno", 0)
                line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
                matches.append(RuntimePathBypass(rel_path=rel, line_number=lineno, source_line=line))
    return matches


def _is_teleclaude_home_bypass(node: ast.AST) -> bool:
    """Return True when a syntax node constructs ~/.teleclaude without teleclaude.paths."""
    if isinstance(node, ast.Call):
        if _is_name_call(node, "Path") and _first_string_arg_startswith(node, "~/.teleclaude"):
            return True
        if _is_attr_call(node, "expanduser") and _first_string_arg_startswith(node, "~/.teleclaude"):
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "joinpath":
            return _is_path_home_call(node.func.value) and _first_string_arg_equals(node, ".teleclaude")
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_path_home_call(node.left) and _is_string_constant(node.right, ".teleclaude")
    return False


def _is_name_call(node: ast.Call, name: str) -> bool:
    """Return True when a call target is a bare function/class name."""
    return isinstance(node.func, ast.Name) and node.func.id == name


def _is_attr_call(node: ast.Call, attr: str) -> bool:
    """Return True when a call target is an attribute with the given name."""
    return isinstance(node.func, ast.Attribute) and node.func.attr == attr


def _is_path_home_call(node: ast.AST) -> bool:
    """Return True for ``Path.home()`` syntax."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "home"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
    )


def _first_string_arg_startswith(node: ast.Call, prefix: str) -> bool:
    """Return True when the first positional argument is a matching string literal."""
    return bool(
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value.startswith(prefix)
    )


def _first_string_arg_equals(node: ast.Call, value: str) -> bool:
    """Return True when the first positional argument is the exact string literal."""
    return bool(
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and node.args[0].value == value
    )


def _is_string_constant(node: ast.AST, value: str) -> bool:
    """Return True when a node is the exact string literal."""
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == value


# ---------------------------------------------------------------------------
# Loose-dict typing guardrail
# ---------------------------------------------------------------------------


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
