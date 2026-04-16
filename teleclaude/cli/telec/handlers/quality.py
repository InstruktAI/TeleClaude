"""CLI handlers for ``telec lint`` and ``telec test``."""

from __future__ import annotations

from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import resolve_invocation_cwd, resolve_project_root
from teleclaude.quality.test_runner import TestRunner


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec lint`` command."""
    _ = args  # reserved for future flags
    project_root = resolve_project_root(resolve_invocation_cwd())
    runner = LintRunner(project_root=project_root)
    runner.run()


def handle_test(args: list[str]) -> None:
    """Handle the ``telec test`` command."""
    include_expensive = "--expensive" in args
    project_root = resolve_project_root(resolve_invocation_cwd())
    runner = TestRunner(project_root=project_root, include_expensive=include_expensive)
    targets = runner.resolve_targets()
    runner.run(targets=targets)
