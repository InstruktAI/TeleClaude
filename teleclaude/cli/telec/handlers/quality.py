"""CLI handlers for ``telec code lint``, ``telec code test``, and ``telec code format``."""

from __future__ import annotations

from teleclaude.project_root import resolve_invocation_cwd, resolve_workspace_root
from teleclaude.quality.format import FormatRunner
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import get_project_languages
from teleclaude.quality.test_runner import TestRunner


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec code lint`` command.

    No args → full pipeline with context-aware scoping.
    ``--all`` → run against all source directories (bypass scoping).
    ``<files...>`` → full pipeline against explicit files (bypass scoping).
    ``--step <name> [files...]`` → single pipeline step against given files.
    """
    run_all = "--all" in args
    filtered = [a for a in args if a != "--all"]
    project_root = resolve_workspace_root(resolve_invocation_cwd())
    runner = LintRunner(project_root=project_root)

    step_name, files = _parse_step_args(filtered)
    if step_name is not None:
        runner.run_step(step_name, files)
        return

    runner.run(files=files or None, run_all=run_all)


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
    """Handle the ``telec code test`` command.

    No args → context-aware scoping to resolve test targets.
    ``<files...>`` → run against explicit files (bypass scoping).
    ``--expensive`` �� include expensive-marked tests.
    """
    run_all = "--all" in args
    include_expensive = "--expensive" in args
    files = [a for a in args if a not in ("--expensive", "--all")]
    project_root = resolve_workspace_root(resolve_invocation_cwd())
    runner = TestRunner(project_root=project_root, include_expensive=include_expensive)
    targets = runner.resolve_targets(files=files or None, run_all=run_all)
    runner.run(targets=targets)


def handle_format(args: list[str]) -> None:
    """Handle the ``telec code format`` command.

    No args → format default directories based on configured languages.
    Positional args → format those specific files (pre-commit mode).
    """
    run_all = "--all" in args
    project_root = resolve_workspace_root(resolve_invocation_cwd())
    languages = get_project_languages(project_root)
    runner = FormatRunner(project_root=project_root, languages=languages)
    files = [a for a in args if not a.startswith("-")]
    runner.run(files=files if files else None, run_all=run_all)
