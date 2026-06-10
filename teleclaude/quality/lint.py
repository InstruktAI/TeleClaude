"""Lint runner and pipeline — the ``telec code lint`` implementation.

Orchestrates context-aware file scoping and deterministic pipeline
execution for language-aware linting. See design doc
``software-development/design/workspace-scoping`` for the scoping
contract: worktrees use dirty existing files, shared branches session-scope,
explicit files bypass scoping.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import yaml

from teleclaude.paths import REPO_ROOT
from teleclaude.quality.scope import (
    CargoWorkspaceError,
    RustScope,
    RustScopeKind,
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    get_project_languages,
    markdown_files,
    python_files,
    resolve_rust_scope,
    resolve_workspace_scope_resolution,
    typescript_files,
    validate_scoped_paths,
)
from teleclaude.quality.toolchain import get_toolchain

__all__ = [
    "GuardrailsStep",
    "LintRunner",
    "PythonLintPipeline",
    "RustLintPipeline",
    "TypeScriptLintPipeline",
    "get_project_languages",
    "run_pipeline",
    "validate_scoped_paths",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline steps — each wraps one lint tool with a name for diagnostics.
# ---------------------------------------------------------------------------


class PipelineStep(Protocol):
    """Structural type for pipeline steps — name + run."""

    name: str

    def run(self, targets: list[str]) -> None:
        """Execute the step against targets."""
        ...


def _run_tool(cmd: list[str], project_root: Path, step_name: str) -> None:
    """Run an external tool and raise SystemExit on failure.

    Justified subprocess: external binaries (ruff, pyright, mypy, jscpd)
    have no Python API. Internal scripts (guardrails, markdown) are designed
    as standalone invocations, not importable libraries.
    """
    logger.info("Running %s", step_name)
    result = subprocess.run(cmd, cwd=str(project_root), check=False)
    if result.returncode != 0:
        logger.error("%s failed (exit %d)", step_name, result.returncode)
        raise SystemExit(result.returncode)


@dataclass
class GuardrailsStep:
    """Guardrail cap enforcement step."""

    name: str = "guardrails"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute guardrail enforcement against targets.

        The script ships with TeleClaude (REPO_ROOT/tools/lint/guardrails.py).
        Cwd remains the project being linted so the script can resolve target
        files relative to that project, but the script binary itself is
        always TeleClaude's bundled copy — third-party projects do not need
        to ship their own.
        """
        script = str(REPO_ROOT / "tools" / "lint" / "guardrails.py")
        cmd = [sys.executable, script, *targets]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _MarkdownStep:
    """Markdown and frontmatter validation step."""

    name: str = "markdown"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Execute markdown validation.

        File-scoped: passes only .md targets to the script so foreign
        in-flight docs are ignored. Full-run: repo-wide scan (no args).
        """
        script = str(REPO_ROOT / "tools" / "lint" / "markdown.py")
        if self._run_all:
            cmd = [sys.executable, script]
        else:
            md = markdown_files(targets)
            if not md:
                return
            cmd = [sys.executable, script, *md]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _HomePathsStep:
    """Reject hardcoded HOME paths under .teleclaude in staged markdown."""

    name: str = "home_paths"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute home-paths scan against the calling project's staged set."""
        _ = targets  # the script reads its own staged set from git
        script = str(REPO_ROOT / "tools" / "lint" / "home_paths.py")
        cmd = [sys.executable, script, "--project-root", str(self._project_root)]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _ResourceValidationStep:
    """Resource validation step (telec sync --skip-deploy)."""

    name: str = "resource_validation"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Execute resource validation on full runs only.

        Repo-wide cross-ref validation is inherently global — skip on
        file-scoped runs to avoid blocking an agent's commit on foreign
        in-flight docs.
        """
        _ = targets  # resource validation is repo-wide (full runs only)
        if not self._run_all:
            return
        cmd = [sys.executable, "-m", "teleclaude.cli.telec", "sync", "--skip-deploy"]
        _run_tool(cmd, self._project_root, self.name)


def _resolve_frontend_root(project_root: Path) -> Path:
    """Read frontend_root from teleclaude.yml, defaulting to 'frontend'."""
    config_path = project_root / "teleclaude.yml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            fr = data.get("frontend_root")
            if fr:
                return project_root / str(fr)
    return project_root / "frontend"


def _frontend_relative_targets(paths: list[str], project_root: Path, frontend_root: Path) -> list[str]:
    resolved_targets: list[str] = []
    for path in paths:
        file_path = Path(path)
        if file_path.is_absolute():
            try:
                relative = file_path.relative_to(frontend_root)
            except ValueError:
                continue
        else:
            relative_to_project = (project_root / file_path).resolve()
            try:
                relative = relative_to_project.relative_to(frontend_root.resolve())
            except ValueError:
                continue
        resolved_targets.append(str(relative))
    return resolved_targets


@dataclass
class _SnapshotTestingStep:
    """Snapshot-testing assertion policy enforcement."""

    name: str = "snapshot_testing"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Run Python snapshot assertion checks. TypeScript coverage is handled by _EslintStep."""
        script = str(REPO_ROOT / "tools" / "lint" / "snapshot_testing.py")
        _run_tool([sys.executable, script, *targets], self._project_root, self.name)


@dataclass
class _TestDisciplineStep:
    """Runtime env mutation discipline enforcement."""

    name: str = "test_discipline"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Run the controlled TELECLAUDE_* env mutation scanner."""
        _ = targets  # the scanner owns its repo-wide scope.
        script = str(REPO_ROOT / "tools" / "lint" / "test_discipline.py")
        _run_tool([sys.executable, script, "--check"], self._project_root, self.name)


@dataclass
class _RuffCheckStep:
    """Ruff lint check with auto-fix step."""

    name: str = "ruff_check"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute ruff check against Python targets."""
        py = python_files(targets)
        if not py:
            return
        cmd = ["ruff", "check", "--fix", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _RuffFormatStep:
    """Ruff format step."""

    name: str = "ruff_format"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute ruff format against Python targets."""
        py = python_files(targets)
        if not py:
            return
        cmd = ["ruff", "format", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _PyrightStep:
    """Pyright type-checking step."""

    name: str = "pyright"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute pyright type-checking against Python targets."""
        py = python_files(targets)
        if not py:
            return
        cmd = ["uv", "run", "pyright", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _MypyStep:
    """Mypy type-checking step."""

    name: str = "mypy"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute mypy type-checking against Python targets."""
        py = python_files(targets)
        if not py:
            return
        cmd = ["uv", "run", "mypy", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _JscpdStep:
    """Copy-paste detection via jscpd."""

    name: str = "jscpd"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute jscpd copy-paste detection against targets."""
        py = python_files(targets)
        if not py:
            return
        cmd = [
            "npx",
            "--yes",
            "jscpd",
            "--min-lines",
            "25",
            "--min-tokens",
            "150",
            "--mode",
            "strict",
            "--exit-code",
            "1",
            # DB migrations are immutable, self-contained snapshots; their
            # boilerplate (SQLite column-drop table rebuild) is intentionally
            # duplicated across revisions and must never be deduplicated.
            # `--ignore` takes file-level globs; `--ignore-pattern` is a
            # code-level token regex and silently fails to exclude these files.
            "--ignore",
            "**/migrations/**",
            # .gitignore is honored by default (the current jscpd/cpd CLI exposes
            # only --no-gitignore to opt out), so generated artifacts under dist/
            # etc. stay excluded without a hand-rolled list.
            *py,
        ]
        _run_tool(cmd, self._project_root, self.name)


# ---------------------------------------------------------------------------
# Pipeline — deterministic step ordering
# ---------------------------------------------------------------------------


class PythonLintPipeline:
    """Python lint pipeline with deterministic step ordering.

    Steps are accessible via the ``steps`` attribute and each exposes a
    ``name`` for diagnostics and a ``run(targets)`` method.
    """

    def __init__(self, project_root: Path, *, run_all: bool = False) -> None:
        root = project_root
        self.steps: list[PipelineStep] = [
            GuardrailsStep(_project_root=root),
            _MarkdownStep(_project_root=root, _run_all=run_all),
            _HomePathsStep(_project_root=root),
            _ResourceValidationStep(_project_root=root, _run_all=run_all),
            _SnapshotTestingStep(_project_root=root),
            _TestDisciplineStep(_project_root=root),
            _RuffCheckStep(_project_root=root),
            _RuffFormatStep(_project_root=root),
            _PyrightStep(_project_root=root),
            _MypyStep(_project_root=root),
            _JscpdStep(_project_root=root),
        ]

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


@dataclass
class _EslintStep:
    """ESLint check step for TypeScript."""

    name: str = "eslint"
    _frontend_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute eslint against TypeScript targets."""
        if not targets:
            return
        cmd = ["npx", "--yes", "eslint", *targets]
        _run_tool(cmd, self._frontend_root, self.name)


@dataclass
class _TscStep:
    """TypeScript type-checking via tsc --noEmit."""

    name: str = "tsc"
    _frontend_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute tsc type-checking (project-wide, not file-scoped)."""
        _ = targets  # tsc --noEmit checks the whole project
        cmd = ["npx", "--yes", "tsc", "--noEmit"]
        _run_tool(cmd, self._frontend_root, self.name)


class TypeScriptLintPipeline:
    """TypeScript lint pipeline with eslint and tsc steps."""

    def __init__(self, _project_root: Path, frontend_root: Path) -> None:
        self.steps: list[PipelineStep] = [
            _EslintStep(_frontend_root=frontend_root),
            _TscStep(_frontend_root=frontend_root),
        ]

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


@dataclass
class _CargoFmtCheckStep:
    """Cargo fmt check for Rust workspaces."""

    name: str = "cargo_fmt_check"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Execute cargo fmt --check against package or workspace scope."""
        scope = _resolve_step_rust_scope(self._project_root, targets, run_all=self._run_all)
        if scope.kind is RustScopeKind.EMPTY:
            return
        cmd = _cargo_fmt_check_command(scope)
        _run_tool(cmd, _rust_cwd(scope), self.name)


@dataclass
class _CargoClippyStep:
    """Cargo clippy for Rust workspaces."""

    name: str = "cargo_clippy"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Execute cargo clippy against package or workspace scope."""
        scope = _resolve_step_rust_scope(self._project_root, targets, run_all=self._run_all)
        if scope.kind is RustScopeKind.EMPTY:
            return
        cmd = _cargo_clippy_command(scope)
        _run_tool(cmd, _rust_cwd(scope), self.name)


class RustLintPipeline:
    """Rust lint pipeline with cargo fmt-check and clippy steps."""

    def __init__(self, project_root: Path, *, run_all: bool = False) -> None:
        self.steps: list[PipelineStep] = [
            _CargoFmtCheckStep(_project_root=project_root, _run_all=run_all),
            _CargoClippyStep(_project_root=project_root, _run_all=run_all),
        ]

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


def _resolve_step_rust_scope(project_root: Path, targets: list[str], *, run_all: bool) -> RustScope:
    try:
        return resolve_rust_scope(project_root, targets, run_all=run_all)
    except CargoWorkspaceError as exc:
        logger.error("Rust workspace unavailable: %s", exc)
        raise SystemExit(1) from exc


def _cargo_fmt_check_command(scope: RustScope) -> list[str]:
    if scope.kind is RustScopeKind.PACKAGE and scope.package is not None:
        return ["cargo", "fmt", "-p", scope.package, "--", "--check"]
    return ["cargo", "fmt", "--all", "--", "--check"]


def _cargo_clippy_command(scope: RustScope) -> list[str]:
    if scope.kind is RustScopeKind.PACKAGE and scope.package is not None:
        return ["cargo", "clippy", "-p", scope.package, "--all-targets", "--", "-D", "warnings"]
    return ["cargo", "clippy", "--workspace", "--all-targets", "--", "-D", "warnings"]


def _rust_cwd(scope: RustScope) -> Path:
    if scope.workspace_root is None:
        raise RuntimeError("Rust scope has no workspace root")
    return scope.workspace_root


# ---------------------------------------------------------------------------
# Module-level run_pipeline — called by LintRunner, mockable by tests
# ---------------------------------------------------------------------------

_pipeline_ctx: list[Path | None] = [None]  # mutable container for active project root


def run_pipeline(targets: list[str], *, run_all: bool = False) -> None:
    """Run the Python lint pipeline against the given targets.

    Uses the project root set by the active LintRunner, falling back to cwd.
    """
    root = _pipeline_ctx[0] or Path.cwd()
    pipeline = PythonLintPipeline(project_root=root, run_all=run_all)
    for step in pipeline.steps:
        step.run(targets)


# ---------------------------------------------------------------------------
# LintRunner — the main entry point
# ---------------------------------------------------------------------------


class LintRunner:
    """Orchestrates context-aware lint execution.

    File target resolution follows the workspace-scoping design:
    explicit files bypass scoping, worktrees use dirty existing files,
    and shared branches session-scope to avoid touching other agents' files.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def run(self, files: list[str] | None = None, *, run_all: bool = False) -> None:
        """Run all configured lint pipelines with context-aware file scoping.

        Args:
            files: Explicit file targets. When provided, all scoping is
                   bypassed — these files are validated and passed directly
                   to the pipeline.
            run_all: When True, skip scoping and run against all source
                     directories (equivalent to Makefile invocation).
        """
        _pipeline_ctx[0] = self._project_root
        languages = get_project_languages(self._project_root)
        typescript_scope: list[str] | None = None
        rust_scope: list[str] | None = None
        rust_run_all = False
        file_scoped = False

        if files is not None:
            targets = validate_scoped_paths(files, self._project_root)
            if not targets and files:
                logger.error("All provided files rejected by path validation")
                sys.exit(1)
            if not targets:
                logger.info("No files provided — nothing to lint")
                return
            logger.info("Explicit files provided — bypassing scoping (%d files)", len(targets))
            file_scoped = True
            typescript_scope = targets
            rust_scope = targets
        elif run_all:
            logger.info("--all flag — running against source directories")
            targets = self._resolve_source_dirs(languages)
            rust_run_all = True
        else:
            scope_resolution = self._resolve_workspace_scope_resolution()
            targets = self._targets_from_workspace_scope(scope_resolution, languages)
            if self._is_file_scoped_resolution(scope_resolution):
                file_scoped = True
                typescript_scope = targets
                rust_scope = targets
            else:
                rust_run_all = True

        if self._should_run_python_pipeline(languages):
            run_pipeline(targets, run_all=not file_scoped)

        if "rust" in languages:
            self._run_rust_pipeline(files=rust_scope, run_all=rust_run_all)

        if "typescript" in languages:
            self._run_typescript_pipeline(files=typescript_scope)

    def _resolve_source_dirs(self, languages: list[str]) -> list[str]:
        """Resolve source directories from language toolchain config."""
        if languages:
            all_dirs: list[str] = []
            for lang in languages:
                if lang in ("rust", "typescript"):
                    continue  # TS has its own pipeline dispatch
                try:
                    toolchain = get_toolchain(lang, self._project_root)
                    all_dirs.extend(toolchain.source_dirs)
                except KeyError:
                    logger.warning("No toolchain registered for language %r — skipping", lang)
            return all_dirs or [str(self._project_root)]
        return [str(self._project_root)]

    def _resolve_workspace_scope_resolution(self) -> WorkspaceScopeResolution:
        try:
            return resolve_workspace_scope_resolution(self._project_root)
        except (RuntimeError, OSError) as exc:
            logger.error(
                "Workspace scope unavailable. Pass files explicitly: telec code lint <files...>\nReason: %s",
                exc,
            )
            sys.exit(1)

    def _targets_from_workspace_scope(
        self, scope_resolution: WorkspaceScopeResolution, languages: list[str]
    ) -> list[str]:
        if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.has_session_identity:
            logger.info("No session identity — running against source directories")
            return self._resolve_source_dirs(languages)

        targets = validate_scoped_paths(list(scope_resolution.scoped_existing_paths), self._project_root)
        if not targets:
            logger.info("No files in scope after validation — skipping")
            sys.exit(0)
        return targets

    def _is_file_scoped_resolution(self, scope_resolution: WorkspaceScopeResolution) -> bool:
        return scope_resolution.kind is WorkspaceScopeKind.WORKTREE or scope_resolution.has_session_identity

    def run_step(self, step_name: str, files: list[str]) -> None:
        """Run a single named pipeline step against the given files.

        Pre-commit hooks invoke ``telec code lint --step <name> [files]`` with
        explicit paths. Interactive ``telec code lint --step <name>`` (no
        paths) auto-resolves workspace scope so a step run mirrors the
        scoping ``LintRunner.run`` already provides — agents spot-checking
        their own work see only their files, not the whole repo.

        Step names span both Python and TypeScript pipelines. Raises
        SystemExit(2) when ``step_name`` does not match any step.
        """
        _pipeline_ctx[0] = self._project_root

        step_by_name = self._collect_all_steps()
        step = step_by_name.get(step_name)
        if step is None:
            valid = ", ".join(step_by_name.keys())
            logger.error("Unknown lint step: %r. Valid steps: %s", step_name, valid)
            sys.exit(2)

        if files:
            targets = validate_scoped_paths(files, self._project_root)
            if not targets:
                logger.error("All provided files rejected by path validation")
                sys.exit(1)
        else:
            languages = get_project_languages(self._project_root)
            scope_resolution = self._resolve_workspace_scope_resolution()
            targets = self._targets_from_workspace_scope(scope_resolution, languages)

        step.run(targets)

    def _run_typescript_pipeline(self, files: list[str] | None = None) -> None:
        """Run the TypeScript lint pipeline from frontend_root."""
        frontend_root = self._resolve_frontend_root()
        if not frontend_root.exists():
            logger.info("Frontend root %s does not exist — skipping TypeScript lint", frontend_root)
            return
        targets = ["."] if files is None else self._resolve_typescript_targets(files, frontend_root)
        if not targets:
            logger.info("No TypeScript targets in scope — skipping TypeScript lint")
            return
        pipeline = TypeScriptLintPipeline(self._project_root, frontend_root)
        for step in pipeline.steps:
            step.run(targets)

    def _run_rust_pipeline(self, files: list[str] | None = None, *, run_all: bool = False) -> None:
        """Run the Rust lint pipeline from the Cargo workspace root."""
        targets = [] if files is None else files
        pipeline = RustLintPipeline(self._project_root, run_all=run_all)
        for step in pipeline.steps:
            step.run(targets)

    def _should_run_python_pipeline(self, languages: list[str]) -> bool:
        return "python" in languages

    def _collect_all_steps(self) -> dict[str, PipelineStep]:
        """Collect steps from all configured language pipelines."""
        steps: dict[str, PipelineStep] = {}
        languages = get_project_languages(self._project_root)
        if self._should_run_python_pipeline(languages):
            for s in PythonLintPipeline(self._project_root).steps:
                steps[s.name] = s
        if "rust" in languages:
            for s in RustLintPipeline(self._project_root).steps:
                steps[s.name] = s
        if "typescript" in languages:
            frontend_root = self._resolve_frontend_root()
            for s in TypeScriptLintPipeline(self._project_root, frontend_root).steps:
                steps[s.name] = s
        return steps

    def _resolve_frontend_root(self) -> Path:
        """Read frontend_root from teleclaude.yml, defaulting to 'frontend'."""
        return _resolve_frontend_root(self._project_root)

    def _resolve_typescript_targets(self, files: list[str], frontend_root: Path) -> list[str]:
        """Return frontend-relative TS/JS targets for explicit-file linting."""
        root_relative = typescript_files(files)
        if not root_relative:
            return []
        return _frontend_relative_targets(root_relative, self._project_root, frontend_root)

    def describe_pipeline(self) -> list[str]:
        """Return the pipeline step names (for diagnostics/help text)."""
        return PythonLintPipeline(self._project_root).describe()
