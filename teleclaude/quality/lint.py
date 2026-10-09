"""Lint runner and pipeline — the ``telec code lint`` implementation.

Orchestrates context-aware file scoping and deterministic pipeline
execution for language-aware linting. See design doc
``sdlc/design/workspace-scoping`` for the scoping
contract: worktrees use dirty existing files, shared branches session-scope,
explicit files bypass scoping.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from teleclaude.config.tree_homes import group_paths_by_owning_home
from teleclaude.git import hook_free_environment
from teleclaude.git_tree import TreeSource
from teleclaude.paths import REPO_ROOT, ConfigFileName
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    WorkspaceScopeResolution,
    get_project_languages,
    git_inventory_paths,
    markdown_files,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)
from teleclaude.quality.selection import (
    QualityCheckFamily,
    group_paths_by_grading_root,
    resolve_repository_grading_root,
)
from teleclaude.resource_validation import validate_all_artifacts, validate_jobs_config

__all__ = [
    "GuardrailsLane",
    "GuardrailsStep",
    "LintRunner",
    "get_project_languages",
    "run_pipeline",
    "validate_scoped_paths",
]

logger = logging.getLogger(__name__)
_CONTENT_ROOT_FLAG = "--content-root"
_PLATFORM_HOME_SUBJECT_FLAG = "--platform-home-subject"
_SKIP_SNIPPETS_FLAG = "--skip-snippets"
_NO_FILES_FLAG = "--no-files"
_FULL_RUN_FLAG = "--full-run"
_CONTENT_ROOT_FULL_RUN_ERROR = "A content-root validation must be path-scoped."
_CONTENT_ROOT_GRADING_ROOT_MISSING_ERROR = "Candidate validation has no readable repository grading root."
_EMPTY_STRING = ""


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


def _run_tool(
    cmd: list[str],
    project_root: Path,
    step_name: str,
    child_env: Mapping[str, str] | None = None,
) -> None:
    """Run an external tool and raise SystemExit on failure.

    Justified subprocess: guardrail scripts and shell checks are standalone
    entry points so they can also run from hooks and direct maintainer calls.
    """
    logger.info("Running %s", step_name)
    env = dict(child_env) if child_env is not None else hook_free_environment(project_root)
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
    _child_env: Mapping[str, str] | None = None

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
        _run_tool(cmd, self._project_root, self.name, self._child_env)


@dataclass
class _MarkdownStep:
    """Markdown and frontmatter validation step."""

    name: str = "markdown"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _content_root: Path | None = None
    _platform_home_subject: bool = False
    _validate_snippets: bool = True
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Execute markdown validation.

        File-scoped: passes only .md targets to the script so foreign
        in-flight docs are ignored. Full-run: passes the Git-derived Markdown
        inventory so filesystem-only files stay outside the grading scope.
        """
        script = str(REPO_ROOT / "tools" / "lint" / "markdown.py")
        md: list[str] = []
        if self._run_all:
            cmd = [_bundled_python(), script]
            cmd.append(_FULL_RUN_FLAG)
            md = markdown_files(targets)
            if md:
                cmd.extend(md)
            else:
                cmd.append(_NO_FILES_FLAG)
        else:
            md = markdown_files(targets)
            if not md:
                return
            cmd = [_bundled_python(), script]
        if self._content_root is not None:
            cmd.extend([_CONTENT_ROOT_FLAG, str(self._content_root)])
            if self._platform_home_subject:
                cmd.append(_PLATFORM_HOME_SUBJECT_FLAG)
        if not self._validate_snippets:
            cmd.append(_SKIP_SNIPPETS_FLAG)
        if not self._run_all:
            cmd.extend(md)
        _run_tool(cmd, self._project_root, self.name, self._child_env)


@dataclass
class _HomePathsStep:
    """Reject hardcoded HOME paths under .teleclaude in staged markdown."""

    name: str = "home_paths"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Execute home-paths scan against selected markdown files."""
        script = str(REPO_ROOT / "tools" / "lint" / "home_paths.py")
        cmd = [_bundled_python(), script, "--project-root", str(self._project_root)]
        if self._run_all:
            cmd.append("--repo-wide")
            cmd.extend(["--working-tree-files", *markdown_files(targets)])
        else:
            md = markdown_files(targets)
            if not md:
                return
            cmd.extend(["--working-tree-files", *md])
        _run_tool(cmd, self._project_root, self.name, self._child_env)


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


def _selected_raw_sql_inputs(targets: list[str], project_root: Path) -> list[str]:
    selected = _normalize_targets(targets, project_root)
    return sorted(path for path in selected if path in _RAW_SQL_INPUTS)


@dataclass
class _RawSqlStep:
    """Raw-SQL marker validation for DB-access modules."""

    name: str = "raw_sql"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Run repo-wide on full runs, or only for selected raw-SQL inputs."""
        script = str(REPO_ROOT / "tools" / "checks" / "check-raw-sql.sh")
        cmd = [script, "--project-root", str(self._project_root)]
        selected = _selected_raw_sql_inputs(targets, self._project_root)
        if not selected:
            return
        cmd.extend(selected)
        _run_tool(cmd, self._project_root, self.name, self._child_env)


@dataclass
class _SourceValidationStep:
    """Validate selected sources, reporting findings to the CLI and log."""

    name: str = "source_validation"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _content_root: Path | None = None
    _validate_artifacts: bool = True

    def run(self, targets: list[str]) -> None:
        """Reject malformed artifacts and selected jobs declarations."""
        if self._run_all and self._content_root is not None:
            logger.error(_CONTENT_ROOT_FULL_RUN_ERROR)
            sys.stderr.write(f"{_CONTENT_ROOT_FULL_RUN_ERROR}{os.linesep}")
            raise SystemExit(1)
        findings = self._validate_path_scoped(
            targets, content_root=self._content_root, validate_artifacts=self._validate_artifacts
        )
        if not findings:
            return
        for finding in findings:
            logger.error(finding)
            sys.stderr.write(f"{finding}{os.linesep}")
        raise SystemExit(1)

    def _validate_path_scoped(
        self,
        targets: list[str],
        *,
        content_root: Path | None,
        validate_artifacts: bool,
    ) -> list[str]:
        """Validate each path-scoped source against its selected root."""
        source = TreeSource.active_index(self._project_root)
        normalized_targets = sorted(_normalize_targets(targets, self._project_root))
        grouped_paths: dict[Path, list[str]] = {}
        if content_root is None:
            owner_groups = group_paths_by_owning_home(normalized_targets, source)
            for owner, repository_paths in owner_groups.items():
                grouped_paths[owner.root] = [owner.relative_path(path) for path in repository_paths]
        else:
            grading_root = resolve_repository_grading_root(self._project_root, source)
            if grading_root is None:
                raise ValueError(_CONTENT_ROOT_GRADING_ROOT_MISSING_ERROR)
            grading_groups = group_paths_by_grading_root(normalized_targets, source, grading_root)
            for grading_root_entry, repository_paths in grading_groups.items():
                grouped_paths[grading_root_entry.root] = [
                    grading_root_entry.relative_path(path) for path in repository_paths
                ]
        findings: list[str] = []
        validation_root = content_root.resolve() if content_root is not None else self._project_root.resolve()
        for relative_root, home_paths in grouped_paths.items():
            home_root = validation_root / relative_root
            if validate_artifacts:
                findings.extend(validate_all_artifacts(home_root, paths=home_paths))
            if str(ConfigFileName.OVERLAY) in home_paths:
                findings.extend(validate_jobs_config(home_root))
        if content_root is None:
            return findings
        prefix = f"{validation_root}{os.sep}"
        return [finding.replace(prefix, _EMPTY_STRING) for finding in findings]


@dataclass
class _SnapshotTestingStep:
    """Snapshot-testing assertion policy enforcement."""

    name: str = "snapshot_testing"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Run Python snapshot assertion checks against selected or all tests."""
        script = str(REPO_ROOT / "tools" / "lint" / "snapshot_testing.py")
        args = targets if targets else (["--all"] if self._run_all else [])
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name, self._child_env)


@dataclass
class _ForbidUnitTestsStep:
    """Python no-unit-test policy enforcement."""

    name: str = "forbid_unit_tests"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Run selected-file or repo-wide Python unit-test guard."""
        script = str(REPO_ROOT / "tools" / "lint" / "forbid_unit_tests.py")
        args = targets if targets else (["--all"] if self._run_all else [])
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name, self._child_env)


@dataclass
class _ForbidTsUnitTestsStep:
    """TypeScript no-unit-test policy enforcement."""

    name: str = "forbid_ts_unit_tests"
    _project_root: Path = field(default_factory=Path)
    _run_all: bool = False
    _child_env: Mapping[str, str] | None = None

    def run(self, targets: list[str]) -> None:
        """Run selected-file or repo-wide TypeScript unit-test guard."""
        script = str(REPO_ROOT / "tools" / "lint" / "forbid_ts_unit_tests.py")
        args = ["--all"] if self._run_all else targets
        _run_tool([_bundled_python(), script, *args], self._project_root, self.name, self._child_env)


# ---------------------------------------------------------------------------
# Pipeline — deterministic step ordering
# ---------------------------------------------------------------------------


class GuardrailsLane:
    """Capability-selected policy checks with deterministic step ordering.

    Steps are accessible via the ``steps`` attribute and each exposes a
    ``name`` for diagnostics and a ``run(targets)`` method.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        run_all: bool = False,
        content_root: Path | None = None,
        platform_home_subject: bool = False,
        child_env: Mapping[str, str] | None = None,
        check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
    ) -> None:
        root = project_root
        self.steps: list[PipelineStep] = []
        if QualityCheckFamily.CODE in check_families:
            self.steps.append(GuardrailsStep(_project_root=root, _child_env=child_env))
            self.steps.append(_RawSqlStep(_project_root=root, _run_all=run_all, _child_env=child_env))
            self.steps.append(_SnapshotTestingStep(_project_root=root, _run_all=run_all, _child_env=child_env))
            self.steps.append(_ForbidUnitTestsStep(_project_root=root, _run_all=run_all, _child_env=child_env))
            self.steps.append(_ForbidTsUnitTestsStep(_project_root=root, _run_all=run_all, _child_env=child_env))
        self.steps.extend(
            [
                _MarkdownStep(
                    _project_root=root,
                    _run_all=run_all,
                    _content_root=content_root,
                    _platform_home_subject=platform_home_subject,
                    _validate_snippets=QualityCheckFamily.DOCUMENTATION in check_families,
                    _child_env=child_env,
                ),
                _HomePathsStep(_project_root=root, _run_all=run_all, _child_env=child_env),
                _SourceValidationStep(
                    _project_root=root,
                    _run_all=run_all,
                    _content_root=content_root,
                    _validate_artifacts=QualityCheckFamily.AGENTS in check_families,
                ),
            ]
        )

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


# ---------------------------------------------------------------------------
# Module-level run_pipeline — called by LintRunner, mockable by tests
# ---------------------------------------------------------------------------


def run_pipeline(
    targets: list[str],
    *,
    project_root: Path,
    run_all: bool = False,
    content_root: Path | None = None,
    platform_home_subject: bool = False,
    child_env: Mapping[str, str] | None = None,
    check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
) -> None:
    """Run the guardrails lane against the given targets, rooted at ``project_root``."""
    pipeline = GuardrailsLane(
        project_root=project_root,
        run_all=run_all,
        content_root=content_root,
        platform_home_subject=platform_home_subject,
        child_env=child_env,
        check_families=check_families,
    )
    for step in pipeline.steps:
        step.run(targets)


# ---------------------------------------------------------------------------
# LintRunner — the main entry point
# ---------------------------------------------------------------------------


class LintRunner:
    """Orchestrates context-aware, capability-selected lint execution.

    File target resolution follows the workspace-scoping design:
    explicit files bypass scoping, worktrees use dirty existing files,
    and shared branches session-scope to avoid touching other agents' files.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        content_root: Path | None = None,
        platform_home_subject: bool = False,
        child_env: Mapping[str, str] | None = None,
        check_families: frozenset[QualityCheckFamily] = frozenset(QualityCheckFamily),
    ) -> None:
        self._project_root = project_root
        self._content_root = content_root
        self._platform_home_subject = platform_home_subject
        self._child_env = child_env
        self._check_families = check_families

    def run(self, files: list[str] | None = None, *, run_all: bool = False) -> None:
        """Run all configured lint pipelines with context-aware file scoping.

        Args:
            files: Explicit file targets. When provided, all scoping is
                   bypassed — these files are validated and passed directly
                   to the pipeline. With run_all, they are the complete
                   Git-derived inventory for a full run.
            run_all: When True, skip scoping and use the Git-derived full
                     inventory when no candidate list is supplied.
        """
        file_scoped = False

        if files is not None:
            targets = validate_scoped_paths(files, self._project_root)
            if not targets and files and not run_all:
                logger.error("All provided files rejected by path validation")
                sys.exit(1)
            if not targets and not run_all:
                logger.info("No files provided — nothing to lint")
                return
            logger.info("Explicit files provided — bypassing scoping (%d files)", len(targets))
            file_scoped = not run_all
        elif run_all:
            logger.info("--all flag — running guardrails repo-wide")
            targets = git_inventory_paths(self._project_root)
        else:
            scope_resolution = self._resolve_workspace_scope_resolution()
            targets = self._targets_from_workspace_scope(scope_resolution)
            if self._is_file_scoped_resolution(scope_resolution):
                file_scoped = True

        if run_all and not targets:
            logger.info("Git inventory is empty — no guardrails candidates")
            return

        run_pipeline(
            targets,
            project_root=self._project_root,
            run_all=not file_scoped,
            content_root=self._content_root,
            platform_home_subject=self._platform_home_subject,
            child_env=self._child_env,
            check_families=self._check_families,
        )

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

        if scope_resolution.declared_nothing_over_dirty_tree:
            logger.error(
                "Nothing declared, and the workspace holds dirty paths. Declare what you "
                "are working on with `telec code add <path>...`, or pass files explicitly: "
                "telec code lint <files...>"
            )
            sys.exit(1)

        targets = validate_scoped_paths(list(scope_resolution.scoped_existing_paths), self._project_root)
        if not targets:
            logger.info("No files in scope after validation — skipping")
            sys.exit(0)
        return targets

    def _is_file_scoped_resolution(self, scope_resolution: WorkspaceScopeResolution) -> bool:
        return scope_resolution.kind is WorkspaceScopeKind.WORKTREE or scope_resolution.has_session_identity
