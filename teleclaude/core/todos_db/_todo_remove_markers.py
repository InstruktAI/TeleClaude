"""Marker cleanup coordinated with one todo soft-removal transition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.next_machine.delivery import _run_git_cmd, git_name_set, parse_git_porcelain_paths
from teleclaude.docs_reconcile import SnippetMarkerCleanupPlan, plan_marker_cleanup_for_removed_slug

logger = get_logger(__name__)

MARKER_CLEANUP_EVENT = "todo.remove.marker_cleanup"
MARKER_CLEANUP_LOG_MESSAGE = "Todo removal marker cleanup completed"
UTF8_ENCODING = "utf-8"
GIT_STATUS_ARGS_PREFIX = ("status", "--porcelain", "--")
GIT_CACHED_NAME_ARGS = ("diff", "--cached", "--name-only")
GIT_ADD_ARGS_PREFIX = ("add", "--")
GIT_RESTORE_STAGED_ARGS_PREFIX = ("restore", "--staged", "--")
GIT_COMMIT_ARGS_PREFIX = ("commit", "-m")
GIT_PATHSPEC_SEPARATOR = "--"
GIT_STATUS_FAILED_MESSAGE = "git status failed while preparing todo marker cleanup"
SOURCE_CHANGED_BEFORE_WRITE_TEMPLATE = "Marker cleanup source changed before write: {path}"
WRITE_VERIFICATION_FAILED_TEMPLATE = "Marker cleanup write verification failed: {path}"
SOURCE_CHANGED_BEFORE_ROLLBACK_TEMPLATE = "Marker cleanup source changed before rollback: {path}"
ROLLBACK_VERIFICATION_FAILED_TEMPLATE = "Marker cleanup rollback verification failed: {path}"
COMMIT_MESSAGE_TEMPLATE = "chore(todo): abandon pending markers for {slug}"


class MarkerCleanupOutcome(StrEnum):
    """Completed marker-cleanup outcomes."""

    NO_MARKERS = "no_markers"
    COMMITTED = "committed"
    LEFT_UNCOMMITTED = "left_uncommitted"


class MarkerCleanupReason(StrEnum):
    """Stable reasons for completed marker-cleanup outcomes."""

    NO_MARKERS = "no_markers"
    ALL_PATHS_PRE_CLEAN = "all_paths_pre_clean"
    PREEXISTING_DIRTY_PATHS = "preexisting_dirty_paths"
    GIT_ADD_FAILED = "git_add_failed"
    STAGED_SET_MISMATCH = "staged_set_mismatch"
    GIT_COMMIT_FAILED = "git_commit_failed"
    POST_COMMIT_VERIFICATION_FAILED = "post_commit_verification_failed"


@dataclass(frozen=True)
class MarkerCleanupSnapshot:
    """Pre-removal marker rewrite and cleanliness state for one todo."""

    project_root: Path
    todo_id: str
    slug: str
    plans: tuple[SnippetMarkerCleanupPlan, ...]
    affected_paths: tuple[str, ...]
    preexisting_dirty_paths: frozenset[str]


@dataclass(frozen=True)
class MarkerCleanupResult:
    """The durable-removal outcome of marker cleanup."""

    outcome: MarkerCleanupOutcome
    reason: MarkerCleanupReason


def _repo_relative_path(project_root: Path, path: Path) -> str:
    return path.relative_to(project_root).as_posix()


def _unstage_paths(project_root: Path, paths: tuple[str, ...]) -> None:
    _run_git_cmd([*GIT_RESTORE_STAGED_ARGS_PREFIX, *paths], cwd=str(project_root))


def prepare_marker_cleanup(
    project_root: Path,
    todo_id: str,
    slug: str,
) -> MarkerCleanupSnapshot:
    """Capture affected paths and their Git cleanliness before any marker write."""
    plans = tuple(plan_marker_cleanup_for_removed_slug(project_root, slug))
    affected_paths = tuple(_repo_relative_path(project_root, plan.path) for plan in plans)
    if not affected_paths:
        return MarkerCleanupSnapshot(
            project_root=project_root,
            todo_id=todo_id,
            slug=slug,
            plans=plans,
            affected_paths=affected_paths,
            preexisting_dirty_paths=frozenset(),
        )
    returncode, stdout, stderr = _run_git_cmd(
        [*GIT_STATUS_ARGS_PREFIX, *affected_paths],
        cwd=str(project_root),
    )
    if returncode != 0:
        raise RuntimeError(stderr.strip() or GIT_STATUS_FAILED_MESSAGE)
    dirty_paths = parse_git_porcelain_paths(stdout) & set(affected_paths)
    return MarkerCleanupSnapshot(
        project_root=project_root,
        todo_id=todo_id,
        slug=slug,
        plans=plans,
        affected_paths=affected_paths,
        preexisting_dirty_paths=frozenset(dirty_paths),
    )


def apply_marker_cleanup(snapshot: MarkerCleanupSnapshot) -> None:
    """Apply a snapshot only while each source remains exactly as captured."""
    written_plans: list[SnippetMarkerCleanupPlan] = []
    try:
        for plan in snapshot.plans:
            if plan.path.read_text(encoding=UTF8_ENCODING) != plan.original_content:
                raise RuntimeError(SOURCE_CHANGED_BEFORE_WRITE_TEMPLATE.format(path=plan.path))
            plan.path.write_text(plan.cleaned_content, encoding=UTF8_ENCODING)
            if plan.path.read_text(encoding=UTF8_ENCODING) != plan.cleaned_content:
                raise RuntimeError(WRITE_VERIFICATION_FAILED_TEMPLATE.format(path=plan.path))
            written_plans.append(plan)
    except Exception:
        _restore_written_plans(written_plans)
        raise


def _restore_written_plans(plans: list[SnippetMarkerCleanupPlan]) -> None:
    for plan in reversed(plans):
        if plan.path.read_text(encoding=UTF8_ENCODING) != plan.cleaned_content:
            raise RuntimeError(SOURCE_CHANGED_BEFORE_ROLLBACK_TEMPLATE.format(path=plan.path))
        plan.path.write_text(plan.original_content, encoding=UTF8_ENCODING)
        if plan.path.read_text(encoding=UTF8_ENCODING) != plan.original_content:
            raise RuntimeError(ROLLBACK_VERIFICATION_FAILED_TEMPLATE.format(path=plan.path))


def rollback_marker_cleanup(snapshot: MarkerCleanupSnapshot) -> None:
    """Restore exact pre-removal sources while the todo transaction is uncommitted."""
    _restore_written_plans(list(snapshot.plans))


def _affected_paths_are_clean(snapshot: MarkerCleanupSnapshot) -> bool:
    returncode, stdout, _stderr = _run_git_cmd(
        [*GIT_STATUS_ARGS_PREFIX, *snapshot.affected_paths],
        cwd=str(snapshot.project_root),
    )
    return returncode == 0 and not stdout.strip()


def finalize_marker_cleanup(snapshot: MarkerCleanupSnapshot) -> MarkerCleanupResult:
    """Commit clean-path marker cleanup while preserving all unrelated index state."""
    if not snapshot.affected_paths:
        return MarkerCleanupResult(MarkerCleanupOutcome.NO_MARKERS, MarkerCleanupReason.NO_MARKERS)
    if snapshot.preexisting_dirty_paths:
        return MarkerCleanupResult(MarkerCleanupOutcome.LEFT_UNCOMMITTED, MarkerCleanupReason.PREEXISTING_DIRTY_PATHS)

    pre_staged = git_name_set(snapshot.project_root, list(GIT_CACHED_NAME_ARGS))
    if pre_staged is None:
        return MarkerCleanupResult(MarkerCleanupOutcome.LEFT_UNCOMMITTED, MarkerCleanupReason.GIT_ADD_FAILED)
    returncode, _stdout, _stderr = _run_git_cmd(
        [*GIT_ADD_ARGS_PREFIX, *snapshot.affected_paths],
        cwd=str(snapshot.project_root),
    )
    if returncode != 0:
        _unstage_paths(snapshot.project_root, snapshot.affected_paths)
        return MarkerCleanupResult(MarkerCleanupOutcome.LEFT_UNCOMMITTED, MarkerCleanupReason.GIT_ADD_FAILED)

    staged = git_name_set(snapshot.project_root, list(GIT_CACHED_NAME_ARGS))
    expected_staged = pre_staged | set(snapshot.affected_paths)
    if staged != expected_staged:
        _unstage_paths(snapshot.project_root, snapshot.affected_paths)
        return MarkerCleanupResult(MarkerCleanupOutcome.LEFT_UNCOMMITTED, MarkerCleanupReason.STAGED_SET_MISMATCH)

    message = COMMIT_MESSAGE_TEMPLATE.format(slug=snapshot.slug)
    returncode, _stdout, _stderr = _run_git_cmd(
        [*GIT_COMMIT_ARGS_PREFIX, message, GIT_PATHSPEC_SEPARATOR, *snapshot.affected_paths],
        cwd=str(snapshot.project_root),
    )
    if returncode != 0:
        _unstage_paths(snapshot.project_root, snapshot.affected_paths)
        return MarkerCleanupResult(MarkerCleanupOutcome.LEFT_UNCOMMITTED, MarkerCleanupReason.GIT_COMMIT_FAILED)

    post_staged = git_name_set(snapshot.project_root, list(GIT_CACHED_NAME_ARGS))
    if post_staged != pre_staged or not _affected_paths_are_clean(snapshot):
        return MarkerCleanupResult(MarkerCleanupOutcome.COMMITTED, MarkerCleanupReason.POST_COMMIT_VERIFICATION_FAILED)
    return MarkerCleanupResult(MarkerCleanupOutcome.COMMITTED, MarkerCleanupReason.ALL_PATHS_PRE_CLEAN)


def emit_marker_cleanup_result(snapshot: MarkerCleanupSnapshot, result: MarkerCleanupResult) -> None:
    """Record one completed removal's marker-cleanup decision without document details."""
    logger.info(
        MARKER_CLEANUP_LOG_MESSAGE,
        event=MARKER_CLEANUP_EVENT,
        todo_id=snapshot.todo_id,
        slug=snapshot.slug,
        affected_path_count=len(snapshot.affected_paths),
        preexisting_dirty_path_count=len(snapshot.preexisting_dirty_paths),
        outcome=result.outcome.value,
        reason=result.reason.value,
    )
