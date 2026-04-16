"""Lint runner and pipeline — the ``telec lint`` implementation.

Orchestrates worktree detection, scope resolution, path validation,
and deterministic pipeline execution for language-aware linting.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from teleclaude.quality.scope import (
    get_project_language,
    is_worktree,
    resolve_project_root,
    resolve_session_scope,
    validate_scoped_paths,
)
from teleclaude.quality.toolchain import get_toolchain

__all__ = [
    "GuardrailsStep",
    "LintRunner",
    "PythonLintPipeline",
    "get_project_language",
    "is_worktree",
    "resolve_project_root",
    "resolve_session_scope",
    "run_pipeline",
    "validate_scoped_paths",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline steps — each wraps one lint tool with a name for diagnostics.
# Modeled as dataclasses so pylint doesn't complain about method count.
# ---------------------------------------------------------------------------


class PipelineStep(Protocol):  # pylint: disable=too-few-public-methods
    """Structural type for pipeline steps — name + run."""

    name: str

    def run(self, targets: list[str]) -> None:
        """Execute the step against targets."""
        ...  # pylint: disable=unnecessary-ellipsis


def _python_files(targets: list[str]) -> list[str]:
    """Filter targets to Python source files only (.py, .pyi)."""
    return [t for t in targets if t.endswith((".py", ".pyi"))]


def _run_tool(cmd: list[str], project_root: Path, step_name: str) -> None:
    """Run an external tool and raise SystemExit on failure.

    Justified subprocess: external binaries (ruff, pyright, mypy, pylint)
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
        py = _python_files(targets) or targets
        cmd = ["ruff", "check", "--fix", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _RuffFormatStep:
    """Ruff format step."""

    name: str = "ruff_format"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute ruff format against Python targets."""
        py = _python_files(targets) or targets
        cmd = ["ruff", "format", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _PyrightStep:
    """Pyright type-checking step."""

    name: str = "pyright"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute pyright type-checking against Python targets."""
        py = _python_files(targets) or targets
        cmd = ["pyright", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _MypyStep:
    """Mypy type-checking step."""

    name: str = "mypy"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute mypy type-checking against Python targets."""
        py = _python_files(targets) or targets
        cmd = ["mypy", *py]
        _run_tool(cmd, self._project_root, self.name)


@dataclass
class _PylintStep:
    """Pylint static analysis step."""

    name: str = "pylint"
    _project_root: Path = field(default_factory=Path)

    def run(self, targets: list[str]) -> None:
        """Execute pylint static analysis against Python targets."""
        py = _python_files(targets) or targets
        cmd = ["pylint", *py]
        _run_tool(cmd, self._project_root, self.name)


# ---------------------------------------------------------------------------
# Pipeline — deterministic step ordering
# ---------------------------------------------------------------------------


class PythonLintPipeline:  # pylint: disable=too-few-public-methods
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
            _PylintStep(_project_root=root),
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
    """Orchestrates worktree-aware lint execution.

    Determines the appropriate target scope (session files in a worktree,
    source directories otherwise) and dispatches to the lint pipeline.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def run(self) -> None:
        """Run the lint pipeline with automatic worktree scoping."""
        _pipeline_ctx[0] = self._project_root

        if is_worktree(self._project_root):
            logger.info("Worktree detected — scoping to session-touched files")
            try:
                scoped_files = resolve_session_scope(self._project_root)
            except (RuntimeError, OSError) as exc:
                logger.error("Scope resolution failed in worktree context: %s", exc)
                sys.exit(1)
            targets = validate_scoped_paths(scoped_files, self._project_root)
            if not targets:
                logger.info("No files in scope after validation — skipping")
                sys.exit(0)
        else:
            logger.info("Non-worktree context — using source directories")
            lang = get_project_language(self._project_root)
            if lang:
                toolchain = get_toolchain(lang, self._project_root)
                targets = list(toolchain.source_dirs)
            else:
                targets = [str(self._project_root)]

        run_pipeline(targets)

    def run_step(self, step_name: str, files: list[str]) -> None:
        """Run a single named pipeline step against the given files.

        Pre-commit hooks invoke ``telec lint --step <name> [files]`` to route
        per-hook file lists through the shared pipeline. Files are validated
        against the project root (no traversal, no absolute paths outside).

        Raises SystemExit(2) when ``step_name`` does not match any pipeline
        step, with the valid step names in the error message.
        """
        _pipeline_ctx[0] = self._project_root

        pipeline = PythonLintPipeline(project_root=self._project_root)
        step_by_name = {s.name: s for s in pipeline.steps}
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

    def describe_pipeline(self) -> list[str]:
        """Return the pipeline step names (for diagnostics/help text)."""
        return PythonLintPipeline(self._project_root).describe()
