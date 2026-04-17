"""CLI handlers for ``telec code`` namespace."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from teleclaude.cli.telec.handlers.quality import handle_format, handle_lint, handle_test
from teleclaude.cli.telec.help import _usage
from teleclaude.project_root import resolve_invocation_cwd
from teleclaude.quality.format import FormatRunner
from teleclaude.quality.lint import LintRunner
from teleclaude.quality.scope import get_project_languages, resolve_project_root


def handle_code(args: list[str]) -> None:
    """Route ``telec code <subcommand>`` to the correct handler."""
    if not args:
        _usage("code")
        return
    sub = args[0]
    rest = args[1:]
    if sub == "lint":
        handle_lint(rest)
    elif sub == "test":
        handle_test(rest)
    elif sub == "format":
        handle_format(rest)
    elif sub == "commit":
        handle_code_commit(rest)
    else:
        _usage("code")


def handle_code_commit(args: list[str]) -> None:
    """Stage session-scoped files, run format + lint, then git commit."""
    no_scope = "--no-scope" in args
    no_lint = "--no-lint" in args
    no_format = "--no-format" in args
    filtered = [a for a in args if a not in ("--no-scope", "--no-lint", "--no-format")]
    if "--" in filtered:
        sep = filtered.index("--")
        git_args = filtered[sep + 1 :]
    else:
        git_args = filtered

    project_root = resolve_project_root(resolve_invocation_cwd())

    if not no_scope:
        scoped_files = _resolve_scoped_files(project_root)
        if scoped_files:
            _stage_files(scoped_files)

    staged = _get_staged_files()
    if not staged:
        print("Nothing staged for commit.", file=sys.stderr)
        raise SystemExit(1)

    _check_partial_staging()

    if not no_format:
        languages = get_project_languages(project_root)
        runner = FormatRunner(project_root=project_root, languages=languages)
        runner.run(files=staged)
        for f in staged:
            result = subprocess.run(["git", "diff", "--quiet", "--", f], capture_output=True)
            if result.returncode != 0:
                subprocess.run(["git", "add", "--", f], check=True)

    if not no_lint:
        staged = _get_staged_files()
        lint_runner = LintRunner(project_root=project_root)
        lint_runner.run(files=staged)

    result = subprocess.run(["git", "commit"] + git_args)
    raise SystemExit(result.returncode)


def _resolve_scoped_files(project_root: str | Path) -> list[str]:
    """Resolve session-scoped files via tools/session_scope.py."""
    scope_script = os.path.join(project_root, "tools", "session_scope.py")
    scope_python = os.path.join(project_root, ".venv", "bin", "python3")
    if not os.path.isfile(scope_script) or not os.access(scope_python, os.X_OK):
        return []
    result = subprocess.run(
        [scope_python, scope_script, "--mode", "lint", "--project-root", project_root],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def _stage_files(files: list[str]) -> None:
    """Stage files via git add."""
    subprocess.run(["git", "add", "--"] + files, check=True)


def _get_staged_files() -> list[str]:
    """Return list of staged file paths."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    return [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]


def _check_partial_staging() -> None:
    """Block commits with partially staged files."""
    staged = set(
        subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    unstaged = set(
        subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    overlap = staged & unstaged
    if overlap:
        print("ERROR: partially staged files detected.", file=sys.stderr)
        print("Pre-commit stash/restore would corrupt these files.\n", file=sys.stderr)
        for f in sorted(overlap):
            print(f"  {f}", file=sys.stderr)
        print("\nStage remaining hunks (git add -p) or use --no-scope.", file=sys.stderr)
        raise SystemExit(1)
