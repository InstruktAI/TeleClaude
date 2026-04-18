"""Lint runner and pipeline — the ``telec code lint`` implementation.

Orchestrates context-aware file scoping and deterministic pipeline
execution for language-aware linting. See design doc
``software-development/design/session-file-scoping`` for the scoping
contract: worktrees run repo-wide, shared branches session-scope,
explicit files bypass scoping.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from teleclaude.quality.scope import (
    get_project_languages,
    is_worktree,
    python_files,
    resolve_project_root,
    resolve_session_scope,
    typescript_files,
    validate_scoped_paths,
)
from teleclaude.quality.toolchain import get_toolchain

__all__ = [
    "GuardrailsStep",
    "LintRunner",
    "PythonLintPipeline",
    "TypeScriptLintPipeline",
    "get_project_languages",
    "is_worktree",
    "resolve_project_root",
    "resolve_session_scope",
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
        """Execute guardrail enforcement against targets."""
        cmd = [sys.executable, "tools/lint/guardrails.py", *targets]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _MarkdownStep:
    """Markdown and frontmatter validation step."""

    name: str = "markdown"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute markdown validation (repo-wide, not file-scoped)."""
        _ = targets  # markdown validation is repo-wide
        cmd = [sys.executable, "tools/lint/markdown.py"]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _ResourceValidationStep:
    """Resource validation step (telec sync --validate-only)."""

    name: str = "resource_validation"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute resource validation (repo-wide, not file-scoped)."""
        _ = targets  # resource validation is repo-wide
        cmd = [sys.executable, "-m", "teleclaude.cli.telec", "sync", "--warn-only", "--validate-only"]
        _run_tool(cmd, self._project_root, self.name)


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
        cmd = ["pyright", *py]
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
        cmd = ["mypy", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _JscpdStep:
    """Copy-paste detection via jscpd (replaces pylint duplicate-code)."""

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
            "--exitCode",
            "1",
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

    def __init__(self, project_root: Path) -> None:
        root = project_root
        self.steps: list[PipelineStep] = [
            GuardrailsStep(_project_root=root),
            _MarkdownStep(_project_root=root),
            _ResourceValidationStep(_project_root=root),
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

    def __init__(self, project_root: Path, frontend_root: Path) -> None:
        self.steps: list[PipelineStep] = [
            _EslintStep(_frontend_root=frontend_root),
            _TscStep(_frontend_root=frontend_root),
        ]

    def describe(self) -> list[str]:
        """Return ordered step names for diagnostics."""
        return [s.name for s in self.steps]


# ---------------------------------------------------------------------------
# Module-level run_pipeline — called by LintRunner, mockable by tests
# ---------------------------------------------------------------------------

_pipeline_ctx: list[Path | None] = [None]  # mutable container for active project root


def run_pipeline(targets: list[str]) -> None:
    """Run the Python lint pipeline against the given targets.

    Uses the project root set by the active LintRunner, falling back to cwd.
    """
    root = _pipeline_ctx[0] or Path.cwd()
    pipeline = PythonLintPipeline(project_root=root)
    for step in pipeline.steps:
        step.run(targets)


# ---------------------------------------------------------------------------
# LintRunner — the main entry point
# ---------------------------------------------------------------------------


class LintRunner:
    """Orchestrates context-aware lint execution.

    File target resolution follows the session-file-scoping design:
    explicit files bypass scoping, worktrees run repo-wide, shared
    branches session-scope to avoid touching other agents' files.
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

        if files is not None:
            targets = validate_scoped_paths(files, self._project_root)
            if not targets and files:
                logger.error("All provided files rejected by path validation")
                sys.exit(1)
            if not targets:
                logger.info("No files provided — nothing to lint")
                return
            logger.info("Explicit files provided — bypassing scoping (%d files)", len(targets))
        elif run_all:
            logger.info("--all flag — running against source directories")
            targets = self._resolve_source_dirs(languages)
        elif is_worktree(self._project_root):
            logger.info("Worktree detected — running against source directories")
            targets = self._resolve_source_dirs(languages)
        else:
            targets = self._resolve_shared_branch_targets(languages)

        run_pipeline(targets)

        if "typescript" in languages:
            self._run_typescript_pipeline(files=targets if files is not None else None)

    def _resolve_source_dirs(self, languages: list[str]) -> list[str]:
        """Resolve source directories from language toolchain config."""
        if languages:
            all_dirs: list[str] = []
            for lang in languages:
                if lang == "typescript":
                    continue  # TS has its own pipeline dispatch
                try:
                    toolchain = get_toolchain(lang, self._project_root)
                    all_dirs.extend(toolchain.source_dirs)
                except KeyError:
                    logger.warning("No toolchain registered for language %r — skipping", lang)
            return all_dirs or [str(self._project_root)]
        return [str(self._project_root)]

    def _resolve_shared_branch_targets(self, languages: list[str]) -> list[str]:
        """Resolve targets on a shared branch: session-scoped or source dirs.

        With a session identity, scope to transcript-touched files.
        Without a session identity (human/CI), fall back to source dirs.
        With a session identity but scope failure, exit with guidance.
        """
        from teleclaude.session_identity import (  # pylint: disable=import-outside-toplevel  # deferred: heavy transitive imports
            get_session_id,
        )

        session_id = get_session_id()
        if not session_id:
            logger.info("No session identity — running against source directories")
            return self._resolve_source_dirs(languages)

        logger.info("Shared branch with session — scoping to session-touched files")
        try:
            scoped_files = resolve_session_scope(self._project_root)
        except (RuntimeError, OSError) as exc:
            logger.error(
                "Session scope unavailable. Pass files explicitly: telec code lint <files...>\nReason: %s",
                exc,
            )
            sys.exit(1)
        targets = validate_scoped_paths(scoped_files, self._project_root)
        if not targets:
            logger.info("No files in scope after validation — skipping")
            sys.exit(0)
        return targets

    def run_step(self, step_name: str, files: list[str]) -> None:
        """Run a single named pipeline step against the given files.

        Pre-commit hooks invoke ``telec code lint --step <name> [files]`` to route
        per-hook file lists through the shared pipeline. Files are validated
        against the project root (no traversal, no absolute paths outside).

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

        targets = validate_scoped_paths(files, self._project_root)
        if not targets and files:
            # All paths rejected by validation — fail-fast per R1's
            # never-silently-fall-back contract.
            logger.error("All provided files rejected by path validation")
            sys.exit(1)

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

    def _collect_all_steps(self) -> dict[str, PipelineStep]:
        """Collect steps from all configured language pipelines."""
        steps: dict[str, PipelineStep] = {}
        for s in PythonLintPipeline(self._project_root).steps:
            steps[s.name] = s
        languages = get_project_languages(self._project_root)
        if "typescript" in languages:
            frontend_root = self._resolve_frontend_root()
            for s in TypeScriptLintPipeline(self._project_root, frontend_root).steps:
                steps[s.name] = s
        return steps

    def _resolve_frontend_root(self) -> Path:
        """Read frontend_root from teleclaude.yml, defaulting to 'frontend'."""
        config_path = self._project_root / "teleclaude.yml"
        if config_path.exists():
            import yaml

            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                fr = data.get("frontend_root")
                if fr:
                    return self._project_root / str(fr)
        return self._project_root / "frontend"

    def _resolve_typescript_targets(self, files: list[str], frontend_root: Path) -> list[str]:
        """Return frontend-relative TS/JS targets for explicit-file linting."""
        root_relative = typescript_files(files)
        if not root_relative:
            return []

        resolved_targets: list[str] = []
        for path in root_relative:
            file_path = Path(path)
            if file_path.is_absolute():
                try:
                    relative = file_path.relative_to(frontend_root)
                except ValueError:
                    continue
            else:
                relative_to_project = (self._project_root / file_path).resolve()
                try:
                    relative = relative_to_project.relative_to(frontend_root.resolve())
                except ValueError:
                    continue
            resolved_targets.append(str(relative))
        return resolved_targets

    def describe_pipeline(self) -> list[str]:
        """Return the pipeline step names (for diagnostics/help text)."""
        return PythonLintPipeline(self._project_root).describe()
