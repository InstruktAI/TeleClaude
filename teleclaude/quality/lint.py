"""Lint runner and pipeline — the ``telec code lint`` implementation.

Orchestrates context-aware file scoping and deterministic pipeline
execution for language-aware linting. See design doc
``software-development/design/workspace-scoping`` for the scoping
contract: worktrees use dirty existing files, shared branches session-scope,
explicit files bypass scoping.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from teleclaude.paths import REPO_ROOT
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    get_project_languages,
    markdown_files,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)

__all__ = [
    "GuardrailsLane",
    "GuardrailsStep",
    "LintRunner",
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


def _bundled_python() -> str:
    """Resolve the interpreter carrying TeleClaude's runtime dependencies.

    Guardrails subprocesses import teleclaude (and its third-party runtime
    deps like pyyaml, pydantic). The interpreter that launched the current
    process (``sys.executable``) carries no such guarantee — it reflects
    only who invoked ``telec``. The bundled TeleClaude checkout's own venv
    is the one interpreter guaranteed to satisfy those deps, regardless of
    the launcher.
    """
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        logger.error(
            "Bundled TeleClaude venv interpreter not found at %s. "
            "Run the project installer to create it before running guardrails.",
            venv_python,
        )
        raise SystemExit(1)
    return str(venv_python)


def _run_tool(cmd: list[str], project_root: Path, step_name: str) -> None:
    """Run an external tool and raise SystemExit on failure.

    Justified subprocess: guardrail scripts and shell checks are standalone
    entry points so they can also run from hooks and direct maintainer calls.
    """
    logger.info("Running %s", step_name)
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{REPO_ROOT}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(REPO_ROOT)
    result = subprocess.run(cmd, cwd=str(project_root), env=env, check=False)
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
        cmd = [_bundled_python(), script, *targets]
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
            cmd = [_bundled_python(), script]
        else:
            md = markdown_files(targets)
            if not md:
                return
            cmd = [_bundled_python(), script, *md]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _HomePathsStep:
    """Reject hardcoded HOME paths under .teleclaude in staged markdown."""

    name: str = "home_paths"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Execute home-paths scan against selected markdown files."""
        script = str(REPO_ROOT / "tools" / "lint" / "home_paths.py")
        cmd = [_bundled_python(), script, "--project-root", str(self._project_root)]
        if self._run_all:
            cmd.append("--repo-wide")
        else:
            md = markdown_files(targets)
            if not md:
                return
            cmd.extend(["--working-tree-files", *md])
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
        cmd = [_bundled_python(), "-m", "teleclaude.cli.telec", "sync", "--skip-deploy"]
        _run_tool(cmd, self._project_root, self.name)


_CLI_HELP_INPUT_PREFIXES = ("teleclaude/cli/telec/handlers/",)
_CLI_HELP_INPUTS = frozenset({"teleclaude/cli/telec/surface.py"})
_RAW_SQL_INPUTS = frozenset(
    {
        "teleclaude/core/db/_base.py",
        "teleclaude/core/db/_sync.py",
        "teleclaude/memory/search.py",
        "teleclaude/memory/store.py",
        "teleclaude/memory/context/builder.py",
    }
)


def _normalize_targets(targets: list[str], project_root: Path) -> set[str]:
    """Normalize selected paths to project-relative POSIX paths."""
    normalized: set[str] = set()
    root = project_root.resolve()
    for target in targets:
        candidate = Path(target)
        resolved = (
            candidate.resolve(strict=False) if candidate.is_absolute() else (root / candidate).resolve(strict=False)
        )
        try:
            normalized.add(resolved.relative_to(root).as_posix())
        except ValueError:
            continue
    return normalized


def _targets_intersect_cli_help_inputs(targets: list[str], project_root: Path) -> bool:
    selected = _normalize_targets(targets, project_root)
    return any(path in _CLI_HELP_INPUTS or path.startswith(_CLI_HELP_INPUT_PREFIXES) for path in selected)


def _selected_raw_sql_inputs(targets: list[str], project_root: Path) -> list[str]:
    selected = _normalize_targets(targets, project_root)
    return sorted(path for path in selected if path in _RAW_SQL_INPUTS)


@dataclass
class _CliHelpStep:
    """CLI help validation for changes to the in-tree CLI surface."""

    name: str = "cli_help"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run only on full runs or selected CLI surface/handler changes."""
        if not self._run_all and not _targets_intersect_cli_help_inputs(targets, self._project_root):
            return
        script = str(REPO_ROOT / "tools" / "checks" / "check-cli-help.sh")
        _run_tool([script], self._project_root, self.name)


@dataclass
class _RawSqlStep:
    """Raw-SQL marker validation for DB-access modules."""

    name: str = "raw_sql"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run repo-wide on full runs, or only for selected raw-SQL inputs."""
        script = str(REPO_ROOT / "tools" / "checks" / "check-raw-sql.sh")
        cmd = [script, "--project-root", str(self._project_root)]
        if not self._run_all:
            selected = _selected_raw_sql_inputs(targets, self._project_root)
            if not selected:
                return
            cmd.extend(selected)
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _SnapshotTestingStep:
    """Snapshot-testing assertion policy enforcement."""

    name: str = "snapshot_testing"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run Python snapshot assertion checks against selected or all tests."""
        script = str(REPO_ROOT / "tools" / "lint" / "snapshot_testing.py")
        args = ["--all"] if self._run_all else targets
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name)


@dataclass
class _ProcessMarkerPlacementStep:
    """Process-marker test placement policy enforcement."""

    name: str = "process_marker_placement"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run selected-file or repo-wide process-marker placement guard."""
        script = str(REPO_ROOT / "tools" / "lint" / "process_marker_placement.py")
        args = ["--all"] if self._run_all else targets
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name)


@dataclass
class _ForbidUnitTestsStep:
    """Python no-unit-test policy enforcement."""

    name: str = "forbid_unit_tests"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run selected-file or repo-wide Python unit-test guard."""
        script = str(REPO_ROOT / "tools" / "lint" / "forbid_unit_tests.py")
        args = ["--all"] if self._run_all else targets
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name)


@dataclass
class _ForbidTsUnitTestsStep:
    """TypeScript no-unit-test policy enforcement."""

    name: str = "forbid_ts_unit_tests"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False

    def run(self, targets: list[str]) -> None:
        """Run selected-file or repo-wide TypeScript unit-test guard."""
        script = str(REPO_ROOT / "tools" / "lint" / "forbid_ts_unit_tests.py")
        args = ["--all"] if self._run_all else targets
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name)


# ---------------------------------------------------------------------------
# Pipeline — deterministic step ordering
# ---------------------------------------------------------------------------


class GuardrailsLane:
    """Always-run policy guardrails lane with deterministic step ordering.

    Steps are accessible via the ``steps`` attribute and each exposes a
    ``name`` for diagnostics and a ``run(targets)`` method.
    """

    def __init__(self, project_root: Path, *, run_all: bool = False) -> None:
        root = project_root
        self.steps: list[PipelineStep] = [
            GuardrailsStep(_project_root=root),
            _MarkdownStep(_project_root=root, _run_all=run_all),
            _HomePathsStep(_project_root=root, _run_all=run_all),
            _ResourceValidationStep(_project_root=root, _run_all=run_all),
            _CliHelpStep(_project_root=root, _run_all=run_all),
            _RawSqlStep(_project_root=root, _run_all=run_all),
            _SnapshotTestingStep(_project_root=root, _run_all=run_all),
            _ProcessMarkerPlacementStep(_project_root=root, _run_all=run_all),
            _ForbidUnitTestsStep(_project_root=root, _run_all=run_all),
            _ForbidTsUnitTestsStep(_project_root=root, _run_all=run_all),
        ]

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


# ---------------------------------------------------------------------------
# Module-level run_pipeline — called by LintRunner, mockable by tests
# ---------------------------------------------------------------------------

_pipeline_ctx: list[Path | None] = [None]  # mutable container for active project root


def run_pipeline(targets: list[str], *, run_all: bool = False) -> None:
    """Run the guardrails lane against the given targets.

    Uses the project root set by the active LintRunner, falling back to cwd.
    """
    root = _pipeline_ctx[0] or Path.cwd()
    pipeline = GuardrailsLane(project_root=root, run_all=run_all)
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
        elif run_all:
            logger.info("--all flag — running guardrails repo-wide")
            targets = []
        else:
            scope_resolution = self._resolve_workspace_scope_resolution()
            targets = self._targets_from_workspace_scope(scope_resolution)
            if self._is_file_scoped_resolution(scope_resolution):
                file_scoped = True

        run_pipeline(targets, run_all=not file_scoped)

    def _resolve_workspace_scope_resolution(self) -> WorkspaceScopeResolution:
        try:
            return resolve_workspace_scope_resolution(self._project_root)
        except (RuntimeError, OSError) as exc:
            logger.error(
                "Workspace scope unavailable. Pass files explicitly: telec code lint <files...>\nReason: %s",
                exc,
            )
            sys.exit(1)

    def _targets_from_workspace_scope(self, scope_resolution: WorkspaceScopeResolution) -> list[str]:
        if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.has_session_identity:
            logger.info("No session identity — running guardrails repo-wide")
            return []

        targets = validate_scoped_paths(list(scope_resolution.scoped_existing_paths), self._project_root)
        if not targets:
            logger.info("No files in scope after validation — skipping")
            sys.exit(0)
        return targets

    def _is_file_scoped_resolution(self, scope_resolution: WorkspaceScopeResolution) -> bool:
        return scope_resolution.kind is WorkspaceScopeKind.WORKTREE or scope_resolution.has_session_identity
