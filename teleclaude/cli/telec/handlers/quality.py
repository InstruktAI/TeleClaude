"""CLI handlers for ``telec code lint``, ``telec code test``, and ``telec code format``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import CODE_FORMAT, CODE_LINT, CODE_TEST
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.quality.gate import run_lint_gate, run_make_target
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec code lint`` command.

    A scoped interactive run formats first (best-effort), then runs the
    project-native make lint check leg and the TeleClaude guardrails lane.
    The full/CI run (``--all``, ``CI``, or a no-session shared branch) never
    formats: a rewrite CI discards is indistinguishable from a pass and would
    mask drift, so it stays check-only. ``--step`` is retired.
    """
    parsed = parse_command_args(CODE_LINT, args)
    run_all = parsed.has(F.FLAG_CODE_ALL_LINT)
    files = list(parsed.positionals)
    project_root = resolve_invocation_roots().repository_root

    scoped_files = _resolve_quality_scope(project_root, files=files, run_all=run_all)
    if scoped_files == []:
        return

    result = run_lint_gate(
        project_root,
        None,
        scoped_files,
        scoped_files is not None,
        None,
        request_subject_checkout_grading=True,
    )
    if result.exit_code != 0:
        if result.failure_reason:
            print(f"ERROR: {result.failure_reason}", file=sys.stderr)
        raise SystemExit(result.exit_code)


def handle_test(args: list[str]) -> None:
    """Handle the ``telec code test`` command.

    ``--update-snapshots`` → accept reviewed snapshot diffs.
    """
    parsed = parse_command_args(CODE_TEST, args)
    if parsed.positionals:
        print("ERROR: telec code test does not accept file operands", file=sys.stderr)
        raise SystemExit(2)
    update_snapshots = parsed.has(F.FLAG_CODE_UPDATE_SNAPSHOTS)
    project_root = resolve_invocation_roots().repository_root
    variables = {"SNAPSHOT_UPDATE": "1"} if update_snapshots else None
    exit_code = _run_make("test", project_root, variables=variables)
    if exit_code != 0:
        raise SystemExit(exit_code)


def handle_format(args: list[str]) -> None:
    """Handle the ``telec code format`` command.

    No args → project-native make format.
    Positional args → make format scoped via FILES_FROM.
    """
    parsed = parse_command_args(CODE_FORMAT, args)
    run_all = parsed.has(F.FLAG_CODE_ALL_FORMAT)
    project_root = resolve_invocation_roots().repository_root
    files = list(parsed.positionals)
    scoped_files = None
    if files:
        scoped_files = _validate_or_exit(files, project_root)
        if not scoped_files:
            return
    elif run_all:
        scoped_files = None

    exit_code = _run_make("format", project_root, files=scoped_files)
    if exit_code != 0:
        raise SystemExit(exit_code)


def _resolve_quality_scope(project_root: Path, *, files: list[str], run_all: bool) -> list[str] | None:
    if files:
        return _validate_or_exit(files, project_root)
    if run_all or os.environ.get("CI"):  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        return None

    scope_resolution = resolve_workspace_scope_resolution(project_root)
    if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.has_session_identity:
        return None

    scoped = _validate_or_exit(list(scope_resolution.scoped_existing_paths), project_root)
    if not scoped:
        return []
    return scoped


def _validate_or_exit(files: list[str], project_root: Path) -> list[str]:
    scoped = validate_scoped_paths(files, project_root)
    if len(scoped) != len(files):
        print("ERROR: one or more paths were rejected by scoped path validation", file=sys.stderr)
        raise SystemExit(1)
    return scoped


def _run_make(
    target: str,
    project_root: Path,
    *,
    files: list[str] | None = None,
    variables: dict[str, str] | None = None,
) -> int:
    return run_make_target(target, project_root, files=files, variables=variables)
