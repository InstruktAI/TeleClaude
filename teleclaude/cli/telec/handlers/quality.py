"""CLI handlers for ``telec code lint``, ``telec code test``, and ``telec code format``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from teleclaude.capabilities import resolve_tier_permissions
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.handlers._code_invocation import resolve_invocation_state
from teleclaude.cli.telec.surface import CODE_FORMAT, CODE_LINT, CODE_TEST
from teleclaude.config.context_root import OwningHome, group_paths_by_owning_home
from teleclaude.git import Repo
from teleclaude.git_tree import TreeSource, list_tree_paths
from teleclaude.paths import ConfigFileName, is_platform_home
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.quality.gate import (
    LintGateResult,
    QualityGateLeg,
    run_lint_gate,
    run_make_target,
    select_quality_check_families,
    select_quality_gate_legs,
)
from teleclaude.quality.scope import (
    WorkspaceScopeKind,
    git_inventory_paths,
    resolve_workspace_scope_resolution,
    validate_scoped_paths,
)

_EMPTY_SCOPE_ERROR = (
    "ERROR: none of your declared paths are dirty, so there is nothing in your scope. "
    "Declare what you are working on with `telec code add <path>...`, or pass files explicitly."
)
_LINT_GATE_UNAVAILABLE = "ERROR: telec code lint requires a code or documentation gate in this context."
_LINT_FAILURE_TEMPLATE = "ERROR: {reason}"
_FULL_LINT_UNBORN_HEAD = (
    "ERROR: full lint needs a committed tree to discover owning homes. "
    "Pass files explicitly or commit the initial staged set through the commit gate."
)
_ROOT_HOME = Path(".")
_GIT_DIRECTORY = ".git"


def handle_lint(args: list[str]) -> None:
    """Handle the ``telec code lint`` command.

    Scoped and full runs select checks from each owning home's capabilities.
    Native checks run only for code homes; TeleClaude checks are split by
    code, docs, and agents subscriptions. Full/CI runs are check-only and use
    a Git-derived inventory.
    """
    parsed = parse_command_args(CODE_LINT, args)
    run_all = parsed.has(F.FLAG_CODE_ALL_LINT)
    files = list(parsed.positionals)
    state = resolve_invocation_state()
    project_root = state.repository_root

    scoped_files = _resolve_quality_scope(project_root, files=files, run_all=run_all)
    if scoped_files == []:
        return
    if scoped_files is None:
        results = _run_full_lint_gates(project_root)
    else:
        results = _run_scoped_lint_gates(project_root, scoped_files)
    if not results:
        print(_LINT_GATE_UNAVAILABLE, file=sys.stderr)
        raise SystemExit(2)
    _raise_for_lint_failures(results)


def _run_scoped_lint_gates(project_root: Path, paths: list[str]) -> list[LintGateResult]:
    """Run the quality legs carried by each owning home in a scoped path set."""
    source = TreeSource.active_index(project_root)
    grouped = group_paths_by_owning_home(paths, source)
    results: list[LintGateResult] = []
    for owner, repository_paths in sorted(grouped.items(), key=lambda item: item[0].root.as_posix()):
        home_root = (project_root / owner.root).resolve()
        permissions = resolve_tier_permissions(home_root)
        legs = select_quality_gate_legs(permissions.project_subscriptions, permissions)
        families = select_quality_check_families(permissions.project_subscriptions, permissions)
        if not legs:
            continue
        home_paths = [owner.relative_path(path) for path in repository_paths]
        if QualityGateLeg.NATIVE in legs:
            results.append(
                run_lint_gate(
                    home_root,
                    None,
                    home_paths,
                    True,
                    None,
                    selection=frozenset({QualityGateLeg.NATIVE}),
                    request_subject_checkout_grading=True,
                )
            )
        if QualityGateLeg.GUARDRAILS in legs:
            results.append(
                run_lint_gate(
                    project_root,
                    None,
                    repository_paths,
                    False,
                    None,
                    selection=frozenset({QualityGateLeg.GUARDRAILS}),
                    check_families=families,
                    request_subject_checkout_grading=True,
                    platform_home_subject=is_platform_home(project_root),
                )
            )
    return results


def _run_full_lint_gates(project_root: Path) -> list[LintGateResult]:
    """Run a full lint over committed homes and each home's Git-visible files."""
    repo = Repo(str(project_root))
    if not repo.head.is_valid():
        print(_FULL_LINT_UNBORN_HEAD, file=sys.stderr)
        raise SystemExit(2)
    source = TreeSource.recorded_commit(project_root, repo.head.commit.hexsha)
    tree_paths = list_tree_paths(source)
    tree_path_set = set(tree_paths)
    declaration_paths = [path for path in tree_paths if Path(path).name == ConfigFileName.OVERLAY.value]
    homes: set[OwningHome] = set()
    for path in declaration_paths:
        homes.update(group_paths_by_owning_home([path], source, tree_paths=tree_path_set))

    inventory = git_inventory_paths(project_root)
    grouped_inventory = group_paths_by_owning_home(inventory, source, tree_paths=tree_path_set)
    results: list[LintGateResult] = []
    for owner in sorted(homes, key=lambda item: item.root.as_posix()):
        home_root = (project_root / owner.root).resolve()
        permissions = resolve_tier_permissions(home_root)
        legs = select_quality_gate_legs(permissions.project_subscriptions, permissions)
        if not legs:
            continue
        families = select_quality_check_families(permissions.project_subscriptions, permissions)

        # A separately checked-out home owns its own Git inventory and native suite.
        if owner.root != _ROOT_HOME and (home_root / _GIT_DIRECTORY).exists():
            home_paths = git_inventory_paths(home_root)
            execution_root = home_root
        else:
            home_paths = sorted(set(grouped_inventory.get(owner, [])))
            execution_root = project_root

        if QualityGateLeg.NATIVE in legs:
            results.append(
                run_lint_gate(
                    home_root,
                    None,
                    None,
                    False,
                    None,
                    selection=frozenset({QualityGateLeg.NATIVE}),
                    request_subject_checkout_grading=True,
                )
            )
        if QualityGateLeg.GUARDRAILS in legs:
            results.append(
                run_lint_gate(
                    execution_root,
                    None,
                    home_paths,
                    False,
                    None,
                    selection=frozenset({QualityGateLeg.GUARDRAILS}),
                    check_families=families,
                    full_run=True,
                    request_subject_checkout_grading=True,
                    platform_home_subject=is_platform_home(execution_root),
                )
            )
    return results


def _raise_for_lint_failures(results: list[LintGateResult]) -> None:
    """Report each failed lint leg and stop with its first nonzero status."""
    failure_code = 0
    for result in results:
        if result.exit_code == 0:
            continue
        if result.failure_reason:
            print(_LINT_FAILURE_TEMPLATE.format(reason=result.failure_reason), file=sys.stderr)
        if failure_code == 0:
            failure_code = result.exit_code
    if failure_code != 0:
        raise SystemExit(failure_code)


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

    Scoped like ``telec code lint``: explicit files, else the workspace scope
    (the session's declared dirty files on a shared branch); ``--all``, CI, or a
    no-session shared branch runs the full project-native make format.
    """
    parsed = parse_command_args(CODE_FORMAT, args)
    run_all = parsed.has(F.FLAG_CODE_ALL_FORMAT)
    project_root = resolve_invocation_roots().repository_root
    files = list(parsed.positionals)
    scoped_files = _resolve_quality_scope(project_root, files=files, run_all=run_all)
    if scoped_files == []:
        return

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
    if scope_resolution.kind is WorkspaceScopeKind.SHARED_BRANCH and not scope_resolution.scoped_dirty_paths:
        # Reads only this session's own declared-and-dirty set (deletions included), never
        # other sessions' dirt: an empty scoped run must not read as a pass.
        print(_EMPTY_SCOPE_ERROR, file=sys.stderr)
        raise SystemExit(1)
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
