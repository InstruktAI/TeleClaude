"""CLI handlers for ``telec lint`` and ``telec test``."""

from __future__ import annotations

from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import resolve_invocation_cwd, resolve_project_root
from teleclaude.quality.test_runner import TestRunner


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec lint`` command.

    No args → full pipeline with automatic worktree scoping.
    ``--step <name> [files...]`` → run a single pipeline step against the
    given files (used by pre-commit hooks, which pass staged filenames).
    """
    project_root = resolve_project_root(resolve_invocation_cwd())
    runner = LintRunner(project_root=project_root)

    step_name, files = _parse_step_args(args)
    if step_name is not None:
        runner.run_step(step_name, files)
        return

    runner.run()


def _parse_step_args(args: list[str]) -> tuple[str | None, list[str]]:
    """Extract --step value and positional filenames from args.

    Returns ``(step_name, files)``. ``step_name`` is None when the flag is
    absent. Accepts ``--step NAME`` and ``--step=NAME`` forms.
    """
    step_name: str | None = None
    files: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--step":
            if i + 1 >= len(args):
                msg = "--step requires a value (step name)"
                raise SystemExit(msg)
            step_name = args[i + 1]
            i += 2
            continue
        if arg.startswith("--step="):
            step_name = arg[len("--step=") :]
            i += 1
            continue
        files.append(arg)
        i += 1
    return step_name, files


def handle_test(args: list[str]) -> None:
    """Handle the ``telec test`` command."""
    include_expensive = "--expensive" in args
    project_root = resolve_project_root(resolve_invocation_cwd())
    runner = TestRunner(project_root=project_root, include_expensive=include_expensive)
    targets = runner.resolve_targets()
    runner.run(targets=targets)
