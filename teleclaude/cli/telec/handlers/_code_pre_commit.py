"""Run the single commit gate over the active index before Git records it."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.agent_artifacts import AGENT_ARTIFACT_ROOT_DIRNAME
from teleclaude.cli.telec.handlers._code_git_state import working_tree_snapshot
from teleclaude.git import (
    BadName,
    GitCommandError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    Repo,
    hook_free_environment,
)
from teleclaude.git_tree import TreeSource, list_tree_paths, materialize_tree
from teleclaude.paths import ConfigFileName, is_platform_home
from teleclaude.project_root import resolve_git_root, resolve_invocation_cwd
from teleclaude.quality.gate import (
    LintGateResult,
    QualityCheckFamily,
    QualityGateLeg,
    run_home_guardrail_gate,
    run_lint_gate,
    run_staged_declaration_gate,
)
from teleclaude.quality.runtime_acceptance import (
    active_index_identity,
    is_self_repository,
    run_cold_commit_acceptance,
)
from teleclaude.quality.selection import (
    GradingHomeSelection,
    GradingRoot,
    resolve_repository_grading_root,
    select_grading_homes,
)
from teleclaude.runtime.command_runner import run_concurrent_operations

_CACHED = "--cached"
_NAME_STATUS = "--name-status"
_NO_RENAMES = "--no-renames"
_DIFF_FILTER = "--diff-filter=ACMRD"
_NUL = "-z"
_NUL_CHARACTER = "\x00"
_EMPTY_STRING = ""
_EMPTY_BYTES = b""
_GIT_HASH_TREE_ARGUMENTS = ("-w", "-t", "tree", "--stdin")
_GIT_STAGED_DIFF_ARGUMENTS = (_CACHED, _NAME_STATUS, _NO_RENAMES, _NUL, _DIFF_FILTER)
_GIT_PATHSPEC_SEPARATOR = "--"
_PARTIAL_STAGING_ERROR = "ERROR: partially staged files detected:"
_PRE_COMMIT_GIT_ERROR = "ERROR: pre-commit safety check failed: {error}"
_PRE_COMMIT_USAGE = "Usage: telec repo pre-commit"
_PRE_COMMIT_GATE_ERROR = "ERROR: commit quality gate failed: {reason}"
_PRE_COMMIT_GATE_EVENT = "commit_quality_gate"
_PRE_COMMIT_HOOK_NAME = "pre-commit"
_ROOT_CONFIG_PATH = ConfigFileName.OVERLAY.value
_ROOT_DECLARATION_MISSING = "The repository root has no readable declaration in the candidate tree or on disk."
_STAGED_PATH_RECORD_MALFORMED = "Git returned a malformed staged path status record."
_STAGED_PATH_STATUS_INVALID = "Git returned an unsupported staged path status: {status}"
_STAGED_MARKDOWN_SUFFIX = ".md"
_FORMAT_SCOPED = False
_RESTAGE_INSTRUCTION = "Fully restage via: telec repo add <file>"
_PATH_PREFIX = "  "
_GIT_FAILURES = (
    BadName,
    GitCommandError,
    InvalidGitRepositoryError,
    NoSuchPathError,
    OSError,
    ValueError,
    yaml.YAMLError,
    subprocess.CalledProcessError,
)

logger = get_logger(__name__)


class StagedPathStatus(StrEnum):
    """Change kinds reported for one path in the active index diff."""

    ADDED = "A"
    COPIED = "C"
    MODIFIED = "M"
    RENAMED = "R"
    DELETED = "D"


_STAGED_ACMR_STATUSES = frozenset(
    {
        StagedPathStatus.ADDED,
        StagedPathStatus.COPIED,
        StagedPathStatus.MODIFIED,
        StagedPathStatus.RENAMED,
    }
)


@dataclass(frozen=True)
class StagedPath:
    """One changed path from the active index compared with its base tree."""

    status: StagedPathStatus
    path: str


@dataclass(frozen=True)
class HomeGate:
    """One grading root, its staged paths, and the quality legs it carries."""

    grading_root: GradingRoot
    root: Path
    changes: tuple[StagedPath, ...]
    legs: frozenset[QualityGateLeg]
    families: frozenset[QualityCheckFamily]


@dataclass
class GateDecision:
    """Structured facts recorded for one pre-commit gate invocation."""

    repository_root: str
    homes: list[str] = field(default_factory=list)
    legs: dict[str, list[str]] = field(default_factory=dict)
    exit_code: int = 1


def handle_code_pre_commit(args: list[str]) -> None:
    """Run the hook gate on staged paths, refusing every failed validation."""
    if args:
        print(_PRE_COMMIT_USAGE, file=sys.stderr)
        raise SystemExit(2)
    project_root = resolve_git_root(resolve_invocation_cwd())
    decision = GateDecision(repository_root=str(project_root))
    try:
        decision.exit_code = _run_commit_gate(project_root, decision)
        if decision.exit_code != 0:
            raise SystemExit(decision.exit_code)
    except SystemExit as exc:
        decision.exit_code = exc.code if isinstance(exc.code, int) else 1
        raise
    except _GIT_FAILURES as exc:
        print(_PRE_COMMIT_GIT_ERROR.format(error=exc), file=sys.stderr)
        decision.exit_code = 1
        raise SystemExit(1) from exc
    finally:
        _log_gate_decision(decision)


def _run_commit_gate(project_root: Path, decision: GateDecision) -> int:
    """Read the index once, validate staged declarations, and grade participating homes."""
    repo = Repo(str(project_root))
    tree_source = TreeSource.active_index(project_root)
    tree_paths = list_tree_paths(tree_source)
    grading_root = resolve_repository_grading_root(project_root, tree_source)
    if grading_root is None:
        raise ValueError(_ROOT_DECLARATION_MISSING)

    changes = _read_staged_paths(repo)
    declaration_paths = _staged_declaration_paths(changes)
    declaration_exit_code = run_staged_declaration_gate(project_root, declaration_paths)
    if declaration_exit_code != 0:
        return declaration_exit_code
    home_selections = select_grading_homes(
        project_root,
        [change.path for change in changes],
        tree_source,
        grading_root,
    )
    homes = _select_home_gates(changes, home_selections, decision)
    candidates = frozenset(change.path for change in changes if change.status in _STAGED_ACMR_STATUSES)
    participating_paths = frozenset(
        change.path for home in homes if home.legs for change in home.changes if change.status in _STAGED_ACMR_STATUSES
    )
    partial_staged = (
        sorted(working_tree_snapshot(project_root).partial_staged & candidates & participating_paths)
        if participating_paths
        else []
    )
    if partial_staged:
        print(_PARTIAL_STAGING_ERROR, file=sys.stderr)
        for path in partial_staged:
            print(_PATH_PREFIX + path, file=sys.stderr)
        print(_RESTAGE_INSTRUCTION, file=sys.stderr)
        return 1

    self_repository = is_self_repository(project_root)
    snapshot_needed = self_repository or any(_home_needs_snapshot(home) for home in homes)
    content_context = materialize_tree(tree_source) if snapshot_needed else nullcontext(None)
    child_environment = hook_free_environment(project_root)
    platform_home_subject = is_platform_home(project_root)
    with content_context as content_root:
        if self_repository:
            if content_root is None:
                raise ValueError(_ROOT_DECLARATION_MISSING)
            source_revision, source_tree = active_index_identity(project_root)
            acceptance_exit_code = run_cold_commit_acceptance(
                content_root,
                source_revision,
                source_tree,
            )
            if acceptance_exit_code != 0:
                return acceptance_exit_code
        failures = [
            _run_home_gate(
                project_root,
                home,
                tree_paths,
                content_root,
                platform_home_subject,
                child_environment,
            )
            for home in homes
        ]
    return next((failure for failure in failures if failure != 0), 0)


def _staged_declaration_paths(changes: list[StagedPath]) -> list[str]:
    """Select each changed staged declaration from the active-index diff."""
    declaration_paths: list[str] = []
    for change in changes:
        if change.status not in _STAGED_ACMR_STATUSES or Path(change.path).name != _ROOT_CONFIG_PATH:
            continue
        declaration_paths.append(change.path)
    return declaration_paths


def _read_staged_paths(repo: Repo) -> list[StagedPath]:
    """Read staged path status once against HEAD or the empty tree."""
    base_tree = (
        repo.head.commit.hexsha
        if repo.head.is_valid()
        else repo.git.hash_object(
            *_GIT_HASH_TREE_ARGUMENTS,
            istream=_EMPTY_BYTES,
        )
    )
    output = repo.git.diff(*_GIT_STAGED_DIFF_ARGUMENTS, base_tree, _GIT_PATHSPEC_SEPARATOR)
    fields = output.split(_NUL_CHARACTER)
    if fields and fields[-1] == _EMPTY_STRING:
        fields.pop()
    if len(fields) % 2 != 0:
        raise ValueError(_STAGED_PATH_RECORD_MALFORMED)
    changes: list[StagedPath] = []
    for status_text, path in zip(fields[::2], fields[1::2], strict=True):
        try:
            status = StagedPathStatus(status_text)
        except ValueError as exc:
            raise ValueError(_STAGED_PATH_STATUS_INVALID.format(status=status_text)) from exc
        changes.append(StagedPath(status=status, path=path))
    return changes


def _select_home_gates(
    changes: list[StagedPath],
    selections: tuple[GradingHomeSelection, ...],
    decision: GateDecision,
) -> list[HomeGate]:
    """Record the selected gate decisions and map staged paths to their homes."""
    change_by_path = {change.path: change for change in changes}
    homes: list[HomeGate] = []
    for selection in selections:
        home_changes = tuple(change_by_path[path] for path in selection.paths if path in change_by_path)
        if not home_changes:
            continue
        owner_name = selection.grading_root.root.as_posix()
        decision.homes.append(owner_name)
        decision.legs[owner_name] = sorted(leg.value for leg in selection.legs)
        homes.append(
            HomeGate(
                grading_root=selection.grading_root,
                root=selection.root,
                changes=home_changes,
                legs=selection.legs,
                families=selection.families,
            )
        )
    return homes


def _home_needs_snapshot(home: HomeGate) -> bool:
    """Return whether staged content or a deletion requires snapshot validators."""
    if QualityGateLeg.GUARDRAILS not in home.legs or not (
        QualityCheckFamily.DOCUMENTATION in home.families or QualityCheckFamily.AGENTS in home.families
    ):
        return False
    for change in home.changes:
        if change.status is StagedPathStatus.DELETED or _is_snapshot_target(change.path):
            return True
    return False


def _is_snapshot_target(relative_path: str) -> bool:
    """Identify paths whose validators read committed documentation or artifact content."""
    path = Path(relative_path)
    return (
        path.suffix == _STAGED_MARKDOWN_SUFFIX
        or path.name == _ROOT_CONFIG_PATH
        or AGENT_ARTIFACT_ROOT_DIRNAME in path.parts
    )


def _run_home_gate(
    project_root: Path,
    home: HomeGate,
    tree_paths: list[str],
    content_root: Path | None,
    platform_home_subject: bool,
    child_environment: dict[str, str],
) -> int:
    """Run native and guardrail checks for one selected home."""
    native_paths = sorted(
        home.grading_root.relative_path(change.path)
        for change in home.changes
        if change.status in _STAGED_ACMR_STATUSES
    )

    operations: list[Callable[[], LintGateResult | None]] = []
    if QualityGateLeg.NATIVE in home.legs and native_paths:
        operations.append(
            partial(
                run_lint_gate,
                home.root,
                None,
                native_paths,
                _FORMAT_SCOPED,
                child_environment,
                selection=frozenset({QualityGateLeg.NATIVE}),
                request_subject_checkout_grading=True,
            )
        )

    if QualityGateLeg.GUARDRAILS in home.legs:
        changed_paths = [change.path for change in home.changes if change.status in _STAGED_ACMR_STATUSES]
        deletion_tree_paths = (
            tree_paths if any(change.status is StagedPathStatus.DELETED for change in home.changes) else []
        )
        operations.append(
            partial(
                run_home_guardrail_gate,
                project_root,
                home.grading_root.root,
                changed_paths,
                deletion_tree_paths,
                child_environment,
                check_families=home.families,
                content_root=content_root,
                platform_home_subject=platform_home_subject,
            )
        )

    first_failure = 0
    for result in run_concurrent_operations(operations):
        if result is not None:
            first_failure = _record_gate_result(result.exit_code, result.failure_reason, first_failure)
    return first_failure


def _record_gate_result(exit_code: int, reason: str | None, first_failure: int) -> int:
    """Report a failed home gate while preserving the first nonzero status."""
    if exit_code == 0:
        return first_failure
    if reason:
        print(_PRE_COMMIT_GATE_ERROR.format(reason=reason), file=sys.stderr)
    return first_failure or exit_code


def _log_gate_decision(decision: GateDecision) -> None:
    """Write the one structured decision record for this hook invocation."""
    logger.info(
        _PRE_COMMIT_GATE_EVENT,
        hook=_PRE_COMMIT_HOOK_NAME,
        repository_root=decision.repository_root,
        homes=decision.homes,
        legs=decision.legs,
        exit_code=decision.exit_code,
    )
