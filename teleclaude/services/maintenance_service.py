"""Maintenance loops for cleanup and polling."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config.machine import config
from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.constants import (
    REMOVED_TODO_RETENTION_WINDOW,
    RESTART_CONTINUATION_STIMULUS,
    RUNTIME_RECORD_RETENTION_WINDOW,
    TodoStatus,
)
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_readiness import AGENT_START_STABILIZE_QUIET_S, await_agent_readiness
from teleclaude.core.agents import get_agent_command
from teleclaude.core.control_delivery import ControlDeliveryWakeDecision, handoff_control_payload
from teleclaude.core.db import db
from teleclaude.core.inbound_errors import SessionMessageRejectedError
from teleclaude.core.injected_text import (
    EnvelopeName,
    InjectedTextSourceFeature,
    semantic_envelope,
)
from teleclaude.core.next_machine.delivery import (
    _run_git_cmd,
    git_name_set,
    parse_git_porcelain_paths,
    reclaim_worktree_trash,
)
from teleclaude.core.operations.service import get_operations_service
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.runtime_readiness import RuntimeReadinessKey
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_cleanup import TMUX_SESSION_NAME_UNBOUND
from teleclaude.core.session_compaction import (
    SessionCompactionOwner,
    session_compaction_owner,
)
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_runtime_gate import session_runtime_owner
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.shutdown_drain import ShutdownRefusal, get_shutdown_drain
from teleclaude.core.task_registry import TaskRegistry
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.core.workflow_store.github_store import refresh_github_workflow_store
from teleclaude.core.workflow_store.selection import inspect_workflow_store_presence, selected_workflow_store_backend
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.core.workflow_store.types import StorePresenceKind
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.docs_reconcile import (
    ReconciliationMode,
    ReconciliationPlan,
    ReconciliationWrite,
    apply_reconciliation_plan,
    plan_snippet_reconciliation,
)
from teleclaude.events import get_event_db
from teleclaude.events.consumers import HANDLED_RECORD_RETENTION
from teleclaude.hooks.session_map import prune_session_map
from teleclaude.project_manifest import load_roots
from teleclaude.project_root import is_project_checkout
from teleclaude.resource_validation._todo_status import build_todo_status_map
from teleclaude.runtime.environment import runtime_run_command

if TYPE_CHECKING:
    from teleclaude.core.models import Session
    from teleclaude.core.workflow_store.store import WorkflowStore
    from teleclaude.core.workflow_store.types import ExpiredRemovedItem as ExpiredRemovedRow
    from teleclaude.core.workflow_store.types import PurgedItem as PurgedRemovedRow

logger = get_logger(__name__)
_GITHUB_STORE_REFRESH_COMPLETED = "github_store_refresh_completed"
_GITHUB_STORE_REFRESH_FAILED = "github_store_refresh_failed"
_INVALID_WORKFLOW_STORE_SWEEP = "Removed-todo retention sweep skipped invalid workflow store"

_SOFT_DELETING_EXPIRED_EVENT = "maintenance.expired_session.soft_deleting"


# Closed agent-runtime session retention keeps recent creator-session links
# (TUI revive/jump affordances) resolvable; removed-todo retention bounds how
# long a soft-removed entry survives before purge. Each window is owned by its
# constant below and the two are deliberately independent — see
# local/projects/teleclaude/spec/domain/agent_runtime and local/projects/teleclaude/spec/domain/workflow.
CLOSED_SESSION_RETENTION_WINDOW = timedelta(days=90)
VOICE_TEMP_AUDIO_PREFIX = "voice_"
VOICE_TEMP_AUDIO_RACE_SAFETY = timedelta(minutes=10)
PURGE_REASON_COMMIT_FAILURE = "commit_failure"
PURGE_REASON_FOREIGN_EDIT_ON_FRESH_PASS = "foreign_edit_on_fresh_pass"
PURGE_REASON_GIT_ADD_FAILURE = "git_add_failure"
PURGE_REASON_GIT_COMMAND_FAILURE = "git_command_failure"
PURGE_REASON_LAYER_2_STAGED_SET_MISMATCH = "layer_2_staged_set_mismatch"
PURGE_REASON_LAYER_3_POST_COMMIT_VERIFICATION_FAILURE = "layer_3_post_commit_verification_failure"
_UTF8_ENCODING = "utf-8"
_ROW_SLUG_KEY: Final = "slug"
_NO_STAGING_ERROR = ""
_GIT_ADD_PATHS_ARGS = ("add", "--")
_GIT_REMOVE_CACHED_PATHS_ARGS = ("rm", "--cached", "--quiet", "--ignore-unmatch", "--")
_PURGE_WRITE_VERIFICATION_FAILED_TEMPLATE = "Snippet purge write verification failed for {path}"
_PURGE_COMMIT_MESSAGE_TEMPLATE = "chore(todo): purge {slug}; reconcile pending documentation in {count} paths"
_RESTORE_TMUX_FAILURE_LOG = "Automatic tmux restoration reached terminal outcome"
_TMUX_RESTORE_WORK = "tmux-restore"


class _RestoreTmuxFailureReason(StrEnum):
    """Closed reasons for an unsuccessful automatic tmux restoration."""

    TMUX_CREATION_FAILED = "tmux_creation_failed"
    MISSING_AGENT_IDENTITY = "missing_agent_identity"
    RESTORE_COMMAND_REJECTED = "restore_command_rejected"
    SESSION_CLOSED = "session_closed"
    READY_TIMEOUT = "ready_timeout"
    CONTINUATION_REJECTED = "continuation_rejected"
    UNEXPECTED_EXCEPTION = "unexpected_exception"


class _RestoreTmuxFailureEvent(StrEnum):
    """Stable event token for automatic tmux restoration failures."""

    TERMINAL = "agent_runtime.restore_tmux.failed"


class _RestoreTmuxFailureOutcome(StrEnum):
    """Closed outcomes for automatic tmux restoration failures."""

    FAILED = "failed"


class _RestoreTmuxRetryDisposition(StrEnum):
    """Closed automatic-retry dispositions after a restoration failure."""

    STOPPED_HEADLESS = "stopped_headless"
    PANE_SURVIVES = "pane_survives"


def _log_git_name_set_failure(args: list[str], stderr: str, *, project_root: Path) -> None:
    logger.info(
        "Removed-todo purge git command failed",
        project_root=str(project_root),
        reason=PURGE_REASON_GIT_COMMAND_FAILURE,
        git_args=args,
        stderr=stderr,
    )


def _git_name_set(project_root: Path, args: list[str]) -> set[str] | None:
    return git_name_set(
        project_root,
        args,
        on_failure=partial(_log_git_name_set_failure, project_root=project_root),
    )


def _candidate_dirty_paths(project_root: Path, paths: list[str]) -> set[str] | None:
    if not paths:
        return set()
    rc, stdout, stderr = _run_git_cmd(["status", "--porcelain", "--", *paths], cwd=str(project_root))
    if rc != 0:
        logger.info(
            "Removed-todo purge git command failed",
            project_root=str(project_root),
            reason=PURGE_REASON_GIT_COMMAND_FAILURE,
            git_args=["status", "--porcelain", "--", *paths],
            stderr=stderr,
        )
        return None
    return parse_git_porcelain_paths(stdout) & set(paths)


def _paths_match_head(project_root: Path, paths: list[str]) -> bool:
    if not paths:
        return True
    rc, _stdout, _stderr = _run_git_cmd(["diff", "--quiet", "HEAD", "--", *paths], cwd=str(project_root))
    return rc == 0


def _write_matches_plan(write: ReconciliationWrite) -> bool:
    if write.rendered_content is None:
        return not write.path.exists()
    return write.path.read_text(encoding=_UTF8_ENCODING) == write.rendered_content


def _apply_purge_writes(plan: ReconciliationPlan, writes: list[ReconciliationWrite]) -> None:
    apply_reconciliation_plan(ReconciliationPlan(plan.slug, plan.mode, tuple(writes)))
    for write in writes:
        if not _write_matches_plan(write):
            raise RuntimeError(_PURGE_WRITE_VERIFICATION_FAILED_TEMPLATE.format(path=write.path))


def _writes_for_paths(plan: ReconciliationPlan, paths: list[str]) -> list[ReconciliationWrite]:
    wanted = set(paths)
    return [write for write in plan.writes if write.relative_path in wanted]


def _stage_pending_paths(project_root: Path, pending_paths: list[str]) -> tuple[int, str]:
    """Stage exactly the pending paths; a deletion stages repeatably, whether or not it is already staged."""
    present = [path for path in pending_paths if (project_root / path).exists()]
    absent = [path for path in pending_paths if path not in present]
    if present:
        rc, _stdout, stderr = _run_git_cmd([*_GIT_ADD_PATHS_ARGS, *present], cwd=str(project_root))
        if rc != 0:
            return rc, stderr
    if absent:
        rc, _stdout, stderr = _run_git_cmd([*_GIT_REMOVE_CACHED_PATHS_ARGS, *absent], cwd=str(project_root))
        if rc != 0:
            return rc, stderr
    return 0, _NO_STAGING_ERROR


def _voice_temp_audio_dir() -> Path:
    return Path(tempfile.gettempdir()) / "teleclaude_voice"


def _path_is_under_directory(path: Path, base_dir: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_base = base_dir.resolve()
    except OSError:
        return False
    return resolved_path == resolved_base or resolved_base in resolved_path.parents


async def _cleanup_orphan_voice_audio_files(
    *,
    base_dir: Path | None = None,
    now: datetime | None = None,
) -> int:
    """Delete old voice temp files that are no longer referenced by recoverable rows."""
    temp_dir = base_dir or _voice_temp_audio_dir()
    if not temp_dir.exists() or not temp_dir.is_dir() or temp_dir.is_symlink():
        return 0

    live_audio_paths = set()
    for raw_path in await db.list_live_voice_transcription_audio_paths():
        try:
            live_audio_paths.add(Path(raw_path).resolve())
        except OSError:
            continue

    current_time = now or datetime.now(UTC)
    minimum_age = max(REMOVED_TODO_RETENTION_WINDOW, VOICE_TEMP_AUDIO_RACE_SAFETY)
    removed = 0

    try:
        candidates = list(temp_dir.iterdir())
    except OSError as exc:
        logger.warning("Voice temp audio sweep skipped for %s: %s", temp_dir, exc)
        return 0

    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if not candidate.name.startswith(VOICE_TEMP_AUDIO_PREFIX):
            continue
        if not _path_is_under_directory(candidate, temp_dir):
            continue
        try:
            modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if current_time - modified_at < minimum_age:
            continue
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            continue
        if resolved_candidate in live_audio_paths:
            continue
        try:
            candidate.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("Failed to remove orphan voice temp audio %s: %s", candidate, exc)

    if removed:
        logger.info("Removed %d orphan voice temp audio file(s)", removed)
    return removed


async def _finalize_removed_row(
    todos_db: WorkflowStore,
    row: ExpiredRemovedRow,
) -> PurgedRemovedRow | None:
    await todos_db.clear_pending_purge_paths(row["id"])
    return await todos_db.purge_one_removed(row["id"])


def _verify_layer3(
    project_root: Path,
    row: ExpiredRemovedRow,
    *,
    pre_staged: set[str],
    pending_paths: list[str],
) -> bool:
    pending_set = set(pending_paths)
    cached = _git_name_set(project_root, ["diff", "--cached", "--name-only"])
    if cached is None:
        return False
    staged_offenders = (cached - pre_staged) | (cached & pending_set)
    if staged_offenders:
        logger.info(
            "Removed-todo purge retained pending paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=sorted(pending_set),
            reason=PURGE_REASON_LAYER_3_POST_COMMIT_VERIFICATION_FAILURE,
            offending_entries=sorted(staged_offenders),
        )
        return False

    rc, stdout, stderr = _run_git_cmd(["status", "--porcelain"], cwd=str(project_root))
    if rc != 0:
        logger.info(
            "Removed-todo purge git command failed",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            reason=PURGE_REASON_GIT_COMMAND_FAILURE,
            git_args=["status", "--porcelain"],
            stderr=stderr,
        )
        return False
    dirty_offenders = parse_git_porcelain_paths(stdout) - pre_staged - pending_set
    if dirty_offenders:
        logger.info(
            "Removed-todo purge retained pending paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=sorted(pending_set),
            reason=PURGE_REASON_LAYER_3_POST_COMMIT_VERIFICATION_FAILURE,
            offending_entries=sorted(dirty_offenders),
        )
        return False
    return True


async def _commit_and_finalize_removed_row(
    project_root: Path,
    todos_db: WorkflowStore,
    row: ExpiredRemovedRow,
    *,
    pending_paths: list[str],
) -> PurgedRemovedRow | None:
    pending_set = set(pending_paths)
    pre_staged = _git_name_set(project_root, ["diff", "--cached", "--name-only"])
    if pre_staged is None:
        return None

    rc, stderr = _stage_pending_paths(project_root, pending_paths)
    if rc != 0:
        logger.info(
            "Removed-todo purge retained pending paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=pending_paths,
            reason=PURGE_REASON_GIT_ADD_FAILURE,
            stderr=stderr,
        )
        return None

    staged = _git_name_set(project_root, ["diff", "--cached", "--name-only"])
    if staged is None:
        return None
    expected = pre_staged | pending_set
    if staged != expected:
        logger.info(
            "Removed-todo purge retained pending paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=pending_paths,
            reason=PURGE_REASON_LAYER_2_STAGED_SET_MISMATCH,
            expected=sorted(expected),
            actual=sorted(staged),
        )
        return None

    message = _PURGE_COMMIT_MESSAGE_TEMPLATE.format(slug=row[_ROW_SLUG_KEY], count=len(pending_paths))
    rc, _stdout, stderr = _run_git_cmd(["commit", "-m", message, "--", *pending_paths], cwd=str(project_root))
    if rc != 0:
        logger.info(
            "Removed-todo purge retained pending paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=pending_paths,
            reason=PURGE_REASON_COMMIT_FAILURE,
            stderr=stderr,
        )
        return None

    if not _verify_layer3(project_root, row, pre_staged=pre_staged, pending_paths=pending_paths):
        return None
    return await _finalize_removed_row(todos_db, row)


async def _cleanup_removed_todo_row(
    project_root: Path,
    todos_db: WorkflowStore,
    row: ExpiredRemovedRow,
    todo_status_map: Mapping[str, str],
) -> PurgedRemovedRow | None:
    row_status = todo_status_map.get(row["slug"])
    if row_status is not None and row_status != TodoStatus.REMOVED:
        return await todos_db.purge_one_removed(row["id"])

    pending_paths = row["pending_purge_paths"]
    if pending_paths is not None:
        if not pending_paths:
            return await _finalize_removed_row(todos_db, row)

        if _paths_match_head(project_root, pending_paths):
            pre_staged = _git_name_set(project_root, ["diff", "--cached", "--name-only"])
            if pre_staged is None:
                return None
            if not _verify_layer3(project_root, row, pre_staged=pre_staged, pending_paths=pending_paths):
                return None
            return await _finalize_removed_row(todos_db, row)

        plan = plan_snippet_reconciliation(project_root, row[_ROW_SLUG_KEY], ReconciliationMode.ABANDON)
        _apply_purge_writes(plan, _writes_for_paths(plan, pending_paths))
        return await _commit_and_finalize_removed_row(
            project_root,
            todos_db,
            row,
            pending_paths=pending_paths,
        )

    plan = plan_snippet_reconciliation(project_root, row[_ROW_SLUG_KEY], ReconciliationMode.ABANDON)
    candidate_paths = [write.relative_path for write in plan.writes]
    if not candidate_paths:
        return await todos_db.purge_one_removed(row["id"])

    dirty_paths = _candidate_dirty_paths(project_root, candidate_paths)
    if dirty_paths is None:
        return None
    if dirty_paths:
        logger.info(
            "Removed-todo purge skipped dirty candidate paths",
            project_root=str(project_root),
            todo_id=row["id"],
            slug=row["slug"],
            paths=sorted(dirty_paths),
            reason=PURGE_REASON_FOREIGN_EDIT_ON_FRESH_PASS,
        )
        return None

    await todos_db.set_pending_purge_paths(row["id"], candidate_paths)
    row["pending_purge_paths"] = candidate_paths
    _apply_purge_writes(plan, list(plan.writes))
    return await _commit_and_finalize_removed_row(
        project_root,
        todos_db,
        row,
        pending_paths=candidate_paths,
    )


class MaintenanceService:
    """Background maintenance loops."""

    def __init__(
        self,
        *,
        client: AdapterClient,
        output_poller: OutputPoller,
        poller_watch_interval_s: float,
        task_registry: TaskRegistry,
        compaction_owner: SessionCompactionOwner | None = None,
    ) -> None:
        self._client = client
        self._output_poller = output_poller
        self._poller_watch_interval_s = poller_watch_interval_s
        self._task_registry = task_registry
        self._compaction_owner = compaction_owner or session_compaction_owner
        self._restoring_sessions: set[str] = set()

    async def periodic_cleanup(self) -> None:
        """Clean up inactive sessions and orphans (runs forever)."""
        first_run = True
        while True:
            try:
                if not first_run:
                    await asyncio.sleep(3600)
                first_run = False

                await self._cleanup_worktree_trash()
                await self._cleanup_inactive_sessions()
                await self._refresh_github_workflow_stores()
                await self._cleanup_removed_todos()
                await session_cleanup.retry_recently_closed_session_cleanup(self._client)
                await session_cleanup.cleanup_orphan_tmux_sessions()
                await session_cleanup.cleanup_orphan_workspaces()
                await session_cleanup.cleanup_orphan_session_tmpdirs()
                await asyncio.to_thread(prune_session_map)
                now = datetime.now(UTC)
                runtime_cutoff_iso = (now - RUNTIME_RECORD_RETENTION_WINDOW).isoformat()
                now_iso = now.isoformat()
                await db.cleanup_stale_voice_assignments()
                await db.cleanup_terminal_voice_transcriptions(runtime_cutoff_iso)
                await _cleanup_orphan_voice_audio_files(now=now)
                # Binding-aware: rows with no durable accepted-turn binding survive
                # the sweep regardless of age — see db.cleanup_inbound.
                await db.cleanup_inbound(runtime_cutoff_iso)
                await db.cleanup_orphan_inbound(now_iso)
                await db.cleanup_terminal_operations(runtime_cutoff_iso)
                await db.prune_runtime_retention(now)
                await db.cleanup_hook_outbox(runtime_cutoff_iso)
                await db.cleanup_orphan_session_listeners()
                try:
                    event_db = await get_event_db()
                    await event_db.prune_handled_events(older_than=now - HANDLED_RECORD_RETENTION)
                except Exception:
                    logger.warning("Event DB runtime cleanup skipped", exc_info=True)
                try:
                    await db.compact_runtime_databases_if_needed()
                except Exception:
                    logger.warning("SQLite runtime compaction skipped", exc_info=True)
                try:
                    await get_operations_service().expire_stale_operations()
                except Exception:
                    logger.debug("Operations service not available for stale sweep", exc_info=True)
                await self._cleanup_adapter_resources()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in periodic cleanup: %s", exc, exc_info=True)

    async def poller_watch_loop(self) -> None:
        """Watch tmux foreground commands and ensure pollers are running when needed."""
        while True:
            try:
                await self._poller_watch_iteration()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in poller watch loop: %s", exc, exc_info=True)
            await asyncio.sleep(self._poller_watch_interval_s)

    async def _poller_watch_iteration(self) -> None:
        sessions = await db.get_active_sessions()
        if not sessions:
            return

        try:
            active_tmux_sessions = set(await tmux_bridge.list_tmux_sessions())
        except Exception as exc:
            logger.warning("Failed to list tmux sessions during poller watch: %s", exc)
            return

        for session in sessions:
            attempt = self._compaction_owner.active_attempt(session)
            if attempt is not None:
                if session.tmux_session_name in active_tmux_sessions:
                    continue
                if session.session_id not in self._restoring_sessions:
                    try:
                        restore_unit = get_shutdown_drain().begin_work(_TMUX_RESTORE_WORK)
                    except ShutdownRefusal:
                        continue
                    self._restoring_sessions.add(session.session_id)
                    self._task_registry.spawn(
                        restore_unit.carry(self._restore_tmux_session(session)),
                        name=f"restore-tmux-{session.session_id}",
                    )
                continue
            if await polling_coordinator.is_polling(session.session_id):
                continue

            if session.tmux_session_name not in active_tmux_sessions:
                if session.session_id not in self._restoring_sessions:
                    try:
                        restore_unit = get_shutdown_drain().begin_work(_TMUX_RESTORE_WORK)
                    except ShutdownRefusal:
                        continue
                    self._restoring_sessions.add(session.session_id)
                    self._task_registry.spawn(
                        restore_unit.carry(self._restore_tmux_session(session)),
                        name=f"restore-tmux-{session.session_id}",
                    )
                continue

            if await tmux_bridge.is_pane_dead(session.tmux_session_name):
                logger.debug(
                    "Skipping poller recovery for session %s: tmux pane is dead",
                    session.session_id,
                )
                continue

            await polling_coordinator.schedule_polling(
                session_id=session.session_id,
                tmux_session_name=session.tmux_session_name,
                output_poller=self._output_poller,
                adapter_client=self._client,
            )

    async def _cleanup_inactive_sessions(self) -> None:
        cutoff_time = datetime.now(UTC) - CLOSED_SESSION_RETENTION_WINDOW
        sessions = await db.list_sessions(include_closed=True, include_headless=True)

        for session in sessions:
            if not session.last_activity:
                logger.warning("No last_activity for session %s", session.session_id)
                continue

            if session.closed_at:
                # Historical rows can have closed_at set but lifecycle_status still "active".
                # Normalize once and skip repeated cleanup/deletion attempts.
                if session.lifecycle_status != "closed":
                    await transition_session(
                        db,
                        session.session_id,
                        LifecycleTransition(SessionLifecycleStatus.CLOSED, LifecycleTransitionReason.CLOSED),
                    )
                # Soft-delete closed sessions past the retention window; the record is retained.
                if session.closed_at < cutoff_time:
                    logger.info(
                        _SOFT_DELETING_EXPIRED_EVENT,
                        session_id=session.session_id,
                        closed_ago=str(datetime.now(UTC) - session.closed_at),
                    )
                    await session_cleanup.terminate_session(
                        session.session_id,
                        self._client,
                        reason="closed_expired",
                        session=session,
                        kill_tmux=False,
                        soft_delete=True,
                    )
                continue

            # Open sessions are never auto-closed. Users and agents close them explicitly.
            # The cleanup routine only soft-deletes closed sessions past the retention window.

    async def _cleanup_worktree_trash(self) -> None:
        """Reclaim released worktrees outside caller execution and the event loop."""
        for project_root in load_roots():
            if is_project_checkout(project_root):
                await asyncio.to_thread(reclaim_worktree_trash, str(project_root))

    async def _cleanup_removed_todos(self) -> None:
        """Finalize soft-removed todos past the retention window across every project DB.

        Discovers project todo stores through the selected adapter's read-only
        presence contract. The daemon's operational DB knows nothing about these todos. For each
        expired removed row, reconcile snippet lifecycle frontmatter before
        hard-delete and commit the documentation change with verification.
        """
        cutoff_iso = (datetime.now(UTC) - REMOVED_TODO_RETENTION_WINDOW).isoformat()
        for project_root in load_roots():
            if not project_root.exists():
                continue
            if not is_project_checkout(project_root):
                continue
            try:
                presence = inspect_workflow_store_presence(project_root)
                if presence.kind is StorePresenceKind.ABSENT:
                    continue
                if presence.kind is StorePresenceKind.INVALID:
                    logger.warning(
                        _INVALID_WORKFLOW_STORE_SWEEP,
                        project_root=str(project_root),
                    )
                    continue
                todos_db = await get_workflow_store(str(project_root))
                todo_status_map = build_todo_status_map(project_root)
                rows = await todos_db.list_expired_removed(cutoff_iso)
                for row in rows:
                    purged = await _cleanup_removed_todo_row(project_root, todos_db, row, todo_status_map)
                    if purged is None:
                        continue
                    removed_at = datetime.fromisoformat(row["removed_at"])
                    removed_age_seconds = max(0.0, (datetime.now(UTC) - removed_at).total_seconds())
                    logger.info(
                        "Purged removed todo past retention",
                        project_root=str(project_root),
                        todo_id=purged["id"],
                        slug=purged["slug"],
                        removed_at=purged["removed_at"],
                        removed_age_seconds=removed_age_seconds,
                    )
            except Exception:
                logger.warning(
                    "Removed-todo retention sweep failed for project",
                    project_root=str(project_root),
                    exc_info=True,
                )
                continue

    async def _refresh_github_workflow_stores(self) -> None:
        """Refresh each registered GitHub-backed project during startup and periodic cleanup."""
        for project_root in load_roots():
            if not project_root.exists() or not is_project_checkout(project_root):
                continue
            try:
                if selected_workflow_store_backend(project_root) is not TodoStoreBackend.GITHUB:
                    continue
                started = perf_counter()
                refreshed_items = await refresh_github_workflow_store(project_root, computer=config.computer.name)
                logger.info(
                    _GITHUB_STORE_REFRESH_COMPLETED,
                    project=project_root.name,
                    item_count=refreshed_items,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            except Exception as error:
                logger.warning(
                    _GITHUB_STORE_REFRESH_FAILED,
                    project=project_root.name,
                    reason=type(error).__name__,
                    exc_info=True,
                )

    async def _cleanup_adapter_resources(self) -> None:
        """Run cleanup on each registered UI adapter."""
        for adapter_type, adapter in self._client.adapters.items():
            if isinstance(adapter, UiAdapter):
                try:
                    cleaned = await adapter.cleanup_stale_resources()
                    if cleaned > 0:
                        logger.info("Adapter %s cleaned %d stale resources", adapter_type, cleaned)
                except Exception as exc:
                    logger.warning("Adapter %s cleanup failed: %s", adapter_type, exc)

    async def _restore_tmux_session_owned(self, session: Session) -> None:
        """Recreate a missing tmux session and restart the agent. Runs as a background task.

        The owning wrapper checks pane existence and maintenance purpose under the
        session runtime lease before this body creates a pane or sends a launcher.
        """
        release_guard = True
        resolving_failure = False

        async def _finish_failed_restore(
            reason: _RestoreTmuxFailureReason,
            *,
            error: Exception | None = None,
        ) -> None:
            nonlocal release_guard, resolving_failure
            release_guard = False
            resolving_failure = True
            await self._resolve_restore_tmux_failure(session, reason, error=error)
            current = await db.get_session(session.session_id)
            await self._compaction_owner.settle_restoring_under_owner(current)
            resolving_failure = False
            release_guard = True

        try:
            try:
                working_dir = resolve_working_dir(session.project_path, session.subdir)
                env_vars = await self._build_tmux_env_vars(session)
                if not await ensure_tmux_with_identity(session, session.tmux_session_name, working_dir, env_vars):
                    await _finish_failed_restore(_RestoreTmuxFailureReason.TMUX_CREATION_FAILED)
                    return

                if not (session.active_agent and session.native_session_id):
                    await _finish_failed_restore(_RestoreTmuxFailureReason.MISSING_AGENT_IDENTITY)
                    return

                launch = (
                    await resolve_launch_model(
                        session.active_agent,
                        session.thinking_mode,
                        ownership=launch_ownership(session.role),
                        session_id=session.session_id,
                    )
                    if session.thinking_mode
                    else None
                )
                launch_profile = resolve_session_launch_profile(session, session.active_agent)
                cmd = get_agent_command(
                    agent=session.active_agent,
                    thinking_mode=session.thinking_mode,
                    exec=False,
                    native_session_id=session.native_session_id,
                    profile=launch_profile.profile,
                    launch_flags=launch_profile.flags,
                    resolved_flags=launch.flags if launch else None,
                )
                runtime_run_id = str(uuid4())
                if not await db.install_runtime_run(session.session_id, runtime_run_id):
                    await _finish_failed_restore(_RestoreTmuxFailureReason.SESSION_CLOSED)
                    return
                cmd = runtime_run_command(cmd, runtime_run_id)
                readiness_key = RuntimeReadinessKey.ordinary(session.session_id, runtime_run_id)
                ready_future = self._client.runtime_readiness.register(readiness_key)
                try:
                    if not await tmux_bridge.send_keys_existing_tmux(
                        session_name=session.tmux_session_name,
                        text=cmd,
                    ):
                        await _finish_failed_restore(_RestoreTmuxFailureReason.RESTORE_COMMAND_REJECTED)
                        return

                    logger.info(
                        "Restored agent %s for session %s (native=%s)",
                        session.active_agent,
                        session.session_id,
                        session.native_session_id,
                    )

                    try:
                        await await_agent_readiness(
                            agent_name=session.active_agent,
                            session=session,
                            session_id=session.session_id,
                            ready_future=ready_future,
                            quiet_s=AGENT_START_STABILIZE_QUIET_S,
                            timeout_s=AGENT_PROMPT_READY_TIMEOUT_S,
                            readiness=self._client.runtime_readiness,
                        )
                    except TimeoutError:
                        await _finish_failed_restore(_RestoreTmuxFailureReason.READY_TIMEOUT)
                        return
                    current = await db.get_session(session.session_id)
                    await self._compaction_owner.settle_restoring_under_owner(current)
                finally:
                    self._client.runtime_readiness.release(readiness_key, ready_future)

                try:
                    occurrence_key = f"restore-continuation:{session.session_id}:{uuid4().hex}"
                    await handoff_control_payload(
                        session_id=session.session_id,
                        body=RESTART_CONTINUATION_STIMULUS,
                        source_key=occurrence_key,
                        envelope=semantic_envelope(EnvelopeName.RESTART_CONTINUATION),
                        wake_decision=ControlDeliveryWakeDecision.OBSERVED_IDLE,
                        wake_source_feature=InjectedTextSourceFeature.AGENT_RESTART,
                    )
                except SessionMessageRejectedError:
                    await _finish_failed_restore(_RestoreTmuxFailureReason.CONTINUATION_REJECTED)
                    return
                logger.info("Queued restore continuation stimulus for session %s", session.session_id)
            except Exception as exc:
                # This autonomous task owns all ordinary restoration failures.
                if resolving_failure:
                    raise
                await _finish_failed_restore(_RestoreTmuxFailureReason.UNEXPECTED_EXCEPTION, error=exc)
        except asyncio.CancelledError:
            release_guard = True
            raise
        finally:
            if release_guard:
                self._restoring_sessions.discard(session.session_id)

    async def _restore_tmux_session(self, session: Session) -> None:
        """Serialize restoration with restart, handoff, and terminal input delivery."""
        async with session_runtime_owner(session.session_id):
            current = await db.get_session(session.session_id)
            # Preserve the restore boundary's pane-existence guard before any
            # maintenance metadata transition or ordinary launch effect.
            if current is None or await tmux_bridge.session_exists(current.tmux_session_name, log_missing=False):
                return
            attempt = self._compaction_owner.active_attempt(current)
            if attempt is not None:
                await self._compaction_owner.begin_return_under_owner(current, attempt.attempt_id)
                current = await db.get_session(session.session_id) or current
            await self._restore_tmux_session_owned(current)

    async def _resolve_restore_tmux_failure(
        self,
        session: Session,
        reason: _RestoreTmuxFailureReason,
        *,
        error: Exception | None = None,
    ) -> None:
        """Record a restoration failure after resolving whether its host pane survived."""
        pane_exists = await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False)
        if pane_exists:
            retry_disposition = _RestoreTmuxRetryDisposition.PANE_SURVIVES
        else:
            await db.update_session(session.session_id, tmux_session_name=TMUX_SESSION_NAME_UNBOUND)
            await transition_session(
                db,
                session.session_id,
                LifecycleTransition(SessionLifecycleStatus.HEADLESS, LifecycleTransitionReason.HEADLESS_RESTORED),
            )
            retry_disposition = _RestoreTmuxRetryDisposition.STOPPED_HEADLESS

        if error is None:
            logger.info(
                _RESTORE_TMUX_FAILURE_LOG,
                event=_RestoreTmuxFailureEvent.TERMINAL,
                outcome=_RestoreTmuxFailureOutcome.FAILED,
                reason=reason,
                retry_disposition=retry_disposition,
                session_id=session.session_id,
            )
            return

        logger.info(
            _RESTORE_TMUX_FAILURE_LOG,
            event=_RestoreTmuxFailureEvent.TERMINAL,
            outcome=_RestoreTmuxFailureOutcome.FAILED,
            reason=reason,
            retry_disposition=retry_disposition,
            session_id=session.session_id,
            exc_info=(type(error), error, error.__traceback__),
        )

    async def _build_tmux_env_vars(self, session: Session) -> dict[str, str]:
        voice = await db.get_voice(session.session_id)
        return build_agent_session_environment(
            project_path=session.project_path,
            platform_env=get_voice_env_vars(voice) if voice else {},
        )
