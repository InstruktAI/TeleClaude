#!/usr/bin/env python3
"""Project lint guardrails for repo-wide and staged-file validation."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from functools import cache
from pathlib import Path
from typing import NamedTuple, NoReturn


def _fail(message: str) -> NoReturn:
    """Abort guardrails execution with a formatted failure message."""
    raise SystemExit(f"guardrails: {message}")


@cache
def _ignored_paths(repo_root: Path) -> frozenset[str]:
    """Repo-relative paths git ignores — build outputs, not repository content.

    Guardrails grade what the repository carries. The staged-file path receives
    a git-derived list and so has always been correct; the repo-wide walk
    reaches the filesystem directly and otherwise grades generated artifacts
    that no commit can change, making the run unfixable by any author. Tracked
    files never appear here, and untracked-but-committable ones stay in scope.

    A failing git invocation aborts with its diagnostic rather than degrading to
    the empty set: an empty set silently restores the whole-filesystem scope and
    re-raises findings on generated artifacts that no author can clear, so the
    run would fail anyway — reporting the wrong cause.

    Invoked through ``subprocess`` because this module imports nothing from
    ``teleclaude``: it grades that package, and depending on it would mean a
    broken package disables its own linter. The sibling lint tools resolve git
    the same way.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--others", "--ignored", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        _fail(f"cannot resolve git-ignored paths: {(result.stderr or result.stdout).strip()}")
    return frozenset(line for line in result.stdout.splitlines() if line)


MODULE_SIZE_EXCEPTIONS = frozenset(
    {
        "teleclaude/daemon.py",
        "teleclaude/cli/telec/surface.py",  # declarative CLI schema registry, not logic
        "teleclaude/hooks/receiver/__init__.py",  # pre-existing >1000-line receiver; decomposition tracked separately
        "teleclaude/core/todos_db/_roadmap.py",
        "teleclaude/context_selector.py",
        "teleclaude/install/distribution.py",  # depth work is deferred until its next functional change
    }
)

# File size gate: max lines per module. Exceptions require explicit allowlisting.
MODULE_MAX_LINES = 1000

DIRECT_ENV_READ_RULE = "direct-env-read"
DIRECT_ENV_READ_MESSAGE = "runtime configuration must flow through file-backed typed configuration"
DIRECT_ENV_READ_MARKER_PATTERN = re.compile(r"#\s*guard:\s*direct-env-read\s*-\s*\S")
DIRECT_ENV_READ_SCAN_PREFIX = "teleclaude/"
DIRECT_ENV_READ_CONFIG_PREFIX = "teleclaude/config/"
DIRECT_ENV_READ_RUNTIME_CONFIG_PATH = "teleclaude/runtime/config.py"
DIRECT_ENV_READ_GUARDRAIL_PATH = "tools/lint/guardrails.py"
DIRECT_ENV_READ_LINE_TEMPLATE = "- {rel_path}:{line_number}: {source_line}"
DIRECT_ENV_READ_FAILURE_TEMPLATE = "{rule}: {message}{newline}{formatted}"
OS_MODULE_NAME = "os"
GETENV_MEMBER_NAME = "getenv"
ENVIRON_MEMBER_NAME = "environ"
AST_LINE_NUMBER_ATTRIBUTE = "lineno"
PYTHON_SUFFIX = ".py"
PYTHON_GLOB = "*.py"
UTF8_ENCODING = "utf-8"
EMPTY_SOURCE_LINE = ""
NEWLINE = "\n"


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

    # Root at the project being linted (the caller runs this script with cwd set
    # to that project), not at this script's install location — the guardrails
    # binary is shared across worktrees and downstream projects.
    repo_root = Path.cwd().resolve()
    selected_paths = _normalize_selected_paths(repo_root, args.paths)

    # Module size gate
    _check_module_sizes(repo_root, selected_paths)

    # Source pattern guardrails (table-driven)
    _check_source_patterns(repo_root, selected_paths)
    _check_runtime_path_bypasses(repo_root, selected_paths)
    _check_direct_environment_reads(repo_root, selected_paths)
    _check_identity_role_imports(repo_root)
    _check_pre_dispatch_import_closure(repo_root)

    # Loose-dict typing guardrail
    _warn_for_loose_dicts(repo_root, selected_paths)


_PRE_DISPATCH_FIRST_PARTY_MODULES = frozenset(
    {
        "teleclaude",
        "teleclaude.agent_registry",
        "teleclaude.caller_identity",
        "teleclaude.cli",
        "teleclaude.cli.session_auth",
        "teleclaude.cli.telec",
        "teleclaude.cli.telec.flags",
        "teleclaude.cli.telec.handlers",
        "teleclaude.cli.telec.handlers._arg_parsing",
        "teleclaude.cli.telec.help",
        "teleclaude.cli.telec.surface",
        "teleclaude.cli.telec.surface_types",
        "teleclaude.closed_model",
        "teleclaude.config_roster",
        "teleclaude.constants",
        "teleclaude.core",
        "teleclaude.core.operation_caller_identity",
        "teleclaude.core.session_identity_facts",
        "teleclaude.core.worktree_layout",
        "teleclaude.paths",
        "teleclaude.project_manifest",
        "teleclaude.runtime",
        "teleclaude.runtime.binaries",
        "teleclaude.runtime.config",
        "teleclaude.session_identity",
        "teleclaude.slug",
        "teleclaude.snippet_scope",
        "teleclaude.types",
        "teleclaude.types.creation_record",
        "teleclaude.types.system",
        "teleclaude.types.todo_kind",
    }
)
_PRE_DISPATCH_THIRD_PARTY_ROOTS = frozenset(
    {
        "annotated_types",
        "psutil",
        "pydantic",
        "pydantic_core",
        "typing_extensions",
        "typing_inspection",
        "yaml",
    }
)
_PRE_DISPATCH_IGNORED_ENVIRONMENT_ROOTS = frozenset({"_virtualenv"})
_PRE_DISPATCH_CLOSURE_GUIDANCE = (
    "Inspect the reported failure and read "
    "project/design/architecture/cli-invocation-boundary. For an undeclared import "
    "edge, trace its chain and shared startup cost before moving command-specific "
    "work behind dispatch or proposing a closure update."
)
_CALLER_IDENTITY_MODULE = "teleclaude.caller_identity"
_IDENTITY_INTERNAL_ROLE_NAMES = frozenset(
    {
        "RoleScope",
        "effective_role",
        "scope_for_path",
        "scope_for_project",
        "scope_for_docs_tier",
        "load_person_role_facts",
        "_scope_for_target",
    }
)
_IDENTITY_ROLE_IMPORT_RULE = "identity-role-internal-import"
_IDENTITY_ROLE_IMPORT_MESSAGE = (
    "role facts and scope construction are private to teleclaude.caller_identity; use RoleResolver.role_for"
)
_IDENTITY_ROLE_IMPORT_SEPARATOR = ", "
_IDENTITY_ROLE_IMPORT_LOCATION_TEMPLATE = "{rel_path}:{line_number}: {names}"
_IDENTITY_ROLE_IMPORT_LIST_TEMPLATE = "- {match}"
_IDENTITY_ROLE_IMPORT_FAILURE_TEMPLATE = "{rule}: {message}{newline}{formatted}"
_PRE_DISPATCH_BARE_PACKAGE_PROBE = """
import sys
import teleclaude

if "importlib.metadata" in sys.modules:
    raise SystemExit("bare import teleclaude loaded importlib.metadata")
"""


def _pre_dispatch_import_probe(expected_first_party: frozenset[str]) -> str:
    """Return the isolated import-recorder program for the pre-dispatch path."""
    expected = repr(sorted(expected_first_party))
    return f"""
import builtins
import ast
import importlib.util
import sys
from pathlib import Path

expected_first_party = set({expected})
expected_third_party_roots = set({_PRE_DISPATCH_THIRD_PARTY_ROOTS!r})
ignored_environment_roots = set({_PRE_DISPATCH_IGNORED_ENVIRONMENT_ROOTS!r})
edges = []
original_import = builtins.__import__

def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
    caller = (globals or {{}}).get("__name__", "")
    frame = sys._getframe(1)
    scope = frame.f_code.co_name
    try:
        package = (globals or {{}}).get("__package__") or caller
        target = importlib.util.resolve_name("." * level + name, package) if level else name
    except (ImportError, ValueError):
        target = name
    if caller.startswith("teleclaude.") or target == "importlib.metadata":
        edges.append((caller, target, scope))
    result = original_import(name, globals, locals, fromlist, level)
    for part in fromlist or ():
        imported_child = f"{{target}}.{{part}}"
        if imported_child in sys.modules and (caller.startswith("teleclaude.") or imported_child == "importlib.metadata"):
            edges.append((caller, imported_child, scope))
    return result

builtins.__import__ = tracked_import
import teleclaude
import teleclaude.cli.telec
import teleclaude.cli.session_auth
import teleclaude.caller_identity
import teleclaude.cli.telec.surface
import teleclaude.cli.telec.surface_types
import teleclaude.cli.telec.flags
import teleclaude.cli.telec.help
import teleclaude.cli.telec.handlers._arg_parsing

errors = []
first_party = {{name for name in sys.modules if name == "teleclaude" or name.startswith("teleclaude.")}}
if first_party != expected_first_party:
    added = sorted(first_party - expected_first_party)
    missing = sorted(expected_first_party - first_party)
    if added:
        errors.append("undeclared first-party modules: " + ", ".join(added))
    if missing:
        errors.append("expected first-party modules not loaded: " + ", ".join(missing))

class ScopedImportVisitor(ast.NodeVisitor):
    def __init__(self):
        self.scope_depth = 0
        self.local_imports = []

    def visit_FunctionDef(self, node):
        self.scope_depth += 1
        for child in node.body:
            self.visit(child)
        self.scope_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.scope_depth += 1
        for child in node.body:
            self.visit(child)
        self.scope_depth -= 1

    def visit_Import(self, node):
        if self.scope_depth:
            self.local_imports.append((node.lineno, ast.unparse(node)))

    def visit_ImportFrom(self, node):
        if self.scope_depth:
            self.local_imports.append((node.lineno, ast.unparse(node)))

local_imports = []
for module_name in sorted(expected_first_party):
    module_path = Path(*module_name.split("."))
    source_path = Path(str(module_path) + ".py")
    if not source_path.is_file():
        source_path = module_path / "__init__.py"
    if not source_path.is_file():
        continue
    visitor = ScopedImportVisitor()
    visitor.visit(ast.parse(source_path.read_text(encoding="utf-8")))
    if visitor.local_imports:
        local_imports.extend((source_path.as_posix(), line, statement) for line, statement in visitor.local_imports)
if local_imports:
    errors.append("pre-dispatch imports outside module scope: " + repr(local_imports))

third_party_roots = set()
for module_name, module in sys.modules.items():
    location = getattr(module, "__file__", None)
    if not location:
        continue
    path = Path(location)
    if "site-packages" in path.parts:
        third_party_roots.add(module_name.split(".", 1)[0])
third_party_roots -= ignored_environment_roots
third_party_roots = {{root for root in third_party_roots if not root.startswith("__editable__")}}
unexpected_third_party = sorted(third_party_roots - expected_third_party_roots)
if unexpected_third_party:
    errors.append("undeclared third-party roots: " + ", ".join(unexpected_third_party))

if "importlib.metadata" not in sys.modules:
    errors.append("expected Pydantic roster discovery to load importlib.metadata")
metadata_edges = {{caller for caller, target, _scope in edges if target == "importlib.metadata"}}
if "pydantic.plugin._loader" not in metadata_edges:
    errors.append("importlib.metadata did not load through Pydantic plugin discovery")
first_party_metadata_edges = sorted(
    (caller, target) for caller, target, _scope in edges
    if caller in expected_first_party and target == "importlib.metadata"
)
if first_party_metadata_edges:
    errors.append("first-party import edges to importlib.metadata: " + repr(first_party_metadata_edges))

local_import_edges = sorted(
    (caller, target, scope) for caller, target, scope in edges
    if caller in expected_first_party and scope != "<module>"
)
if local_import_edges:
    errors.append("pre-dispatch imports outside module scope: " + repr(local_import_edges))

for caller, target, _scope in sorted(set(edges)):
    if caller in expected_first_party and target.startswith("teleclaude.") and target not in expected_first_party:
        errors.append(f"undeclared first-party import edge: {{caller}} -> {{target}}")

if errors:
    raise SystemExit("\\n".join(errors))
"""


def _check_pre_dispatch_import_closure(repo_root: Path) -> None:
    """Keep authentication's fresh-process import closure explicit and lean."""
    if not (repo_root / "teleclaude/cli/telec/__init__.py").is_file():
        return

    probes = (
        ("bare package version", _PRE_DISPATCH_BARE_PACKAGE_PROBE),
        ("pre-dispatch import closure", _pre_dispatch_import_probe(_PRE_DISPATCH_FIRST_PARTY_MODULES)),
    )
    failures: list[str] = []
    for label, source in probes:
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            failures.append(f"{label} failed: {detail}")
    if failures:
        _fail("\n".join([*failures, _PRE_DISPATCH_CLOSURE_GUIDANCE]))


def _check_identity_role_imports(repo_root: Path) -> None:
    """Keep effective-role and scope mechanics inside caller identity."""
    matches: list[str] = []
    source_root = repo_root / DIRECT_ENV_READ_SCAN_PREFIX
    identity_path = f"{DIRECT_ENV_READ_SCAN_PREFIX}caller_identity.py"

    def dotted_name(node: ast.expr) -> str | None:
        """Return the name represented by a simple Name/Attribute chain."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            return f"{parent}.{node.attr}" if parent is not None else None
        return None

    for path in source_root.rglob(PYTHON_GLOB):
        if not path.is_file() or path.relative_to(repo_root).as_posix() == identity_path:
            continue
        try:
            source = path.read_text(encoding=UTF8_ENCODING)
            tree = ast.parse(source, filename=path.relative_to(repo_root).as_posix())
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        module_import_prefixes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == _CALLER_IDENTITY_MODULE:
                        module_import_prefixes.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "teleclaude":
                for alias in node.names:
                    if alias.name == "caller_identity":
                        module_import_prefixes.add(alias.asname or _CALLER_IDENTITY_MODULE)

        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module == _CALLER_IDENTITY_MODULE:
                imported.extend(
                    alias.name
                    for alias in node.names
                    if alias.name in _IDENTITY_INTERNAL_ROLE_NAMES or alias.name == "*"
                )
            elif isinstance(node, ast.Attribute) and node.attr in _IDENTITY_INTERNAL_ROLE_NAMES:
                if dotted_name(node.value) in module_import_prefixes:
                    imported.append(node.attr)
            imported.sort()
            if imported:
                assert isinstance(node, (ast.ImportFrom, ast.Attribute))
                rel_path = path.relative_to(repo_root).as_posix()
                matches.append(
                    _IDENTITY_ROLE_IMPORT_LOCATION_TEMPLATE.format(
                        rel_path=rel_path,
                        line_number=node.lineno,
                        names=_IDENTITY_ROLE_IMPORT_SEPARATOR.join(imported),
                    )
                )
    if matches:
        formatted = NEWLINE.join(_IDENTITY_ROLE_IMPORT_LIST_TEMPLATE.format(match=match) for match in matches)
        _fail(
            _IDENTITY_ROLE_IMPORT_FAILURE_TEMPLATE.format(
                rule=_IDENTITY_ROLE_IMPORT_RULE,
                message=_IDENTITY_ROLE_IMPORT_MESSAGE,
                newline=NEWLINE,
                formatted=formatted,
            )
        )


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
        ignored = _ignored_paths(repo_root)
        for dirname in rule.scan_dirs:
            root = repo_root / dirname
            if not root.exists():
                continue
            for glob in globs:
                for path in root.rglob(glob):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(repo_root).as_posix()
                    if rel in ignored:
                        continue
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


def _check_direct_environment_reads(repo_root: Path, selected_paths: set[str] | None = None) -> None:
    """Reject unclassified runtime reads from the process environment."""
    matches = _collect_direct_environment_reads(repo_root, selected_paths)
    if matches:
        formatted = NEWLINE.join(
            DIRECT_ENV_READ_LINE_TEMPLATE.format(
                rel_path=match.rel_path,
                line_number=match.line_number,
                source_line=match.source_line,
            )
            for match in matches
        )
        _fail(
            DIRECT_ENV_READ_FAILURE_TEMPLATE.format(
                rule=DIRECT_ENV_READ_RULE,
                message=DIRECT_ENV_READ_MESSAGE,
                newline=NEWLINE,
                formatted=formatted,
            )
        )


def _collect_direct_environment_reads(
    repo_root: Path,
    selected_paths: set[str] | None = None,
) -> list[RuntimePathBypass]:
    """Collect unclassified process-environment reads from runtime Python."""
    matches: list[RuntimePathBypass] = []
    candidates: Iterable[Path]
    if selected_paths is None:
        candidates = (repo_root / DIRECT_ENV_READ_SCAN_PREFIX).rglob(PYTHON_GLOB)
    else:
        candidates = _iter_selected_files(
            repo_root,
            selected_paths,
            prefixes=(DIRECT_ENV_READ_SCAN_PREFIX,),
            suffixes=(PYTHON_SUFFIX,),
        )

    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(DIRECT_ENV_READ_CONFIG_PREFIX) or rel in {
            DIRECT_ENV_READ_RUNTIME_CONFIG_PATH,
            DIRECT_ENV_READ_GUARDRAIL_PATH,
        }:
            continue
        try:
            source = path.read_text(encoding=UTF8_ENCODING)
            tree = ast.parse(source, filename=rel)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        lines = source.splitlines()
        os_names, getenv_names, environ_names = _collect_direct_environment_imports(tree)
        line_numbers = _collect_direct_environment_read_lines(tree, os_names, getenv_names, environ_names)
        for lineno in sorted(line_numbers):
            if _line_has_direct_environment_read_marker(lines, lineno):
                continue
            source_line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else EMPTY_SOURCE_LINE
            matches.append(RuntimePathBypass(rel_path=rel, line_number=lineno, source_line=source_line))
    return matches


def _collect_direct_environment_imports(tree: ast.Module) -> tuple[set[str], set[str], set[str]]:
    """Resolve supported os module and direct-member import names."""
    os_names: set[str] = set()
    getenv_names: set[str] = set()
    environ_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == OS_MODULE_NAME:
                    os_names.add(alias.asname or OS_MODULE_NAME)
        elif isinstance(node, ast.ImportFrom) and node.module == OS_MODULE_NAME and node.level == 0:
            for alias in node.names:
                imported_name = alias.name
                resolved_name = alias.asname or imported_name
                if imported_name == GETENV_MEMBER_NAME:
                    getenv_names.add(resolved_name)
                elif imported_name == ENVIRON_MEMBER_NAME:
                    environ_names.add(resolved_name)
    return os_names, getenv_names, environ_names


def _collect_direct_environment_read_lines(
    tree: ast.Module,
    os_names: set[str],
    getenv_names: set[str],
    environ_names: set[str],
) -> set[int]:
    """Return source lines containing resolved getenv or environ access."""
    line_numbers: set[int] = set()
    for node in ast.walk(tree):
        if _is_os_getenv_call(node, os_names) or _is_direct_getenv_call(node, getenv_names):
            lineno = getattr(node, AST_LINE_NUMBER_ATTRIBUTE, None)
            if isinstance(lineno, int):
                line_numbers.add(lineno)
        elif _is_os_environ_access(node, os_names) or _is_direct_environ_access(node, environ_names):
            lineno = getattr(node, AST_LINE_NUMBER_ATTRIBUTE, None)
            if isinstance(lineno, int):
                line_numbers.add(lineno)
    return line_numbers


def _is_os_getenv_call(node: ast.AST, os_names: set[str]) -> bool:
    """Return True when a resolved os module invokes getenv."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in os_names
        and node.func.attr == GETENV_MEMBER_NAME
    )


def _is_direct_getenv_call(node: ast.AST, getenv_names: set[str]) -> bool:
    """Return True when a direct getenv import is invoked."""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in getenv_names


def _is_os_environ_access(node: ast.AST, os_names: set[str]) -> bool:
    """Return True when a resolved os module accesses environ."""
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in os_names
        and node.attr == ENVIRON_MEMBER_NAME
    )


def _is_direct_environ_access(node: ast.AST, environ_names: set[str]) -> bool:
    """Return True when a direct environ import is read after import binding."""
    return isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in environ_names


def _line_has_direct_environment_read_marker(lines: list[str], lineno: int) -> bool:
    """Return True when the current or preceding line has a reasoned marker."""
    current = lines[lineno - 1]
    if DIRECT_ENV_READ_MARKER_PATTERN.search(current):
        return True
    return lineno > 1 and bool(DIRECT_ENV_READ_MARKER_PATTERN.search(lines[lineno - 2]))


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
