"""Maintenance loops for cleanup and polling."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.adapters.ui_adapter import UiAdapter
from teleclaude.config import config
from teleclaude.constants import RESTART_CONTINUATION_STIMULUS, TodoStatus
from teleclaude.core import polling_coordinator, session_cleanup, tmux_bridge, tmux_io
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.next_machine.delivery import _run_git_cmd
from teleclaude.core.operations import get_operations_service
from teleclaude.core.output_poller import OutputPoller
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.todos_db import get_todos_db
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.daemon_session import AGENT_PROMPT_READY_TIMEOUT_S
from teleclaude.docs_reconcile import SnippetWriteResult, reconcile_snippets_for_purged_slugs
from teleclaude.events import get_event_db
from teleclaude.hooks.receiver._session import prune_session_map
from teleclaude.resource_validation._todo_status import build_todo_status_map

if TYPE_CHECKING:
    from teleclaude.core.models import Session
    from teleclaude.core.todos_db import TodosDb
    from teleclaude.core.todos_db._todo import ExpiredRemovedRow, PurgedRemovedRow

logger = get_logger(__name__)

# Customer sessions trigger memory extraction after this idle threshold (seconds).
# Unlike admin idle timeout, this does NOT terminate the session.
COMPACTION_IDLE_THRESHOLD_S = 30 * 60  # 30 minutes — applies to any long-lived session

# Closed agent-runtime sessions are retained for 90 days so recent
# creator-session links (TUI revive/jump affordances) stay resolvable.
# Soft-removed todo entries purge after 7 days. The two windows are
# deliberately independent — see project/spec/domain/agent_runtime and
# project/spec/domain/workflow.
CLOSED_SESSION_RETENTION_WINDOW = timedelta(days=90)
REMOVED_TODO_RETENTION_WINDOW = timedelta(days=7)
VOICE_TEMP_AUDIO_PREFIX = "voice_"
VOICE_TEMP_AUDIO_RACE_SAFETY = timedelta(minutes=10)
PURGE_REASON_COMMIT_FAILURE = "commit_failure"
PURGE_REASON_FOREIGN_EDIT_ON_FRESH_PASS = "foreign_edit_on_fresh_pass"
PURGE_REASON_GIT_ADD_FAILURE = "git_add_failure"
PURGE_REASON_GIT_COMMAND_FAILURE = "git_command_failure"
PURGE_REASON_LAYER_2_STAGED_SET_MISMATCH = "layer_2_staged_set_mismatch"
PURGE_REASON_LAYER_3_POST_COMMIT_VERIFICATION_FAILURE = "layer_3_post_commit_verification_failure"


def _repo_relative_path(project_root: Path, path: Path | str) -> str:
    path_obj = Path(path)
    if not path_obj.is_absolute():
        return path_obj.as_posix()
    return path_obj.relative_to(project_root).as_posix()


def _parse_git_name_list(stdout: str) -> set[str]:
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _parse_git_porcelain_paths(stdout: str) -> set[str]:
    paths: set[str] = set()
    for line in stdout.splitlines():
        if not line.strip():
            continue
        raw_path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[1]
        paths.add(raw_path.strip('"'))
    return paths


def _git_name_set(project_root: Path, args: list[str]) -> set[str] | None:
    rc, stdout, stderr = _run_git_cmd(args, cwd=str(project_root))
    if rc != 0:
        logger.info(
            "Removed-todo purge git command failed",
            project_root=str(project_root),
            reason=PURGE_REASON_GIT_COMMAND_FAILURE,
            git_args=args,
            stderr=stderr,
        )
        return None
    return _parse_git_name_list(stdout)


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
    return _parse_git_porcelain_paths(stdout) & set(paths)


def _paths_match_head(project_root: Path, paths: list[str]) -> bool:
    if not paths:
        return True
    rc, _stdout, _stderr = _run_git_cmd(["diff", "--quiet", "HEAD", "--", *paths], cwd=str(project_root))
    return rc == 0


def _write_snippet_plans(plans: list[SnippetWriteResult]) -> None:
    for plan in plans:
        if not plan.write_required and plan.path.read_text(encoding="utf-8") == plan.rendered_content:
            continue
        plan.path.write_text(plan.rendered_content, encoding="utf-8")
        if plan.path.read_text(encoding="utf-8") != plan.rendered_content:
            raise RuntimeError(f"Snippet purge write verification failed for {plan.path}")


def _plans_for_paths(plans: list[SnippetWriteResult], paths: list[str], project_root: Path) -> list[SnippetWriteResult]:
    wanted = set(paths)
    return [plan for plan in plans if _repo_relative_path(project_root, plan.path) in wanted]


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
    todos_db: TodosDb,
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
    dirty_offenders = _parse_git_porcelain_paths(stdout) - pre_staged - pending_set
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
    todos_db: TodosDb,
    row: ExpiredRemovedRow,
    *,
    pending_paths: list[str],
) -> PurgedRemovedRow | None:
    pending_set = set(pending_paths)
    pre_staged = _git_name_set(project_root, ["diff", "--cached", "--name-only"])
    if pre_staged is None:
        return None

    rc, _stdout, stderr = _run_git_cmd(["add", "--", *pending_paths], cwd=str(project_root))
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

    message = f"chore(todo): purge {row['slug']}; reconcile delivered_by in {len(pending_paths)} snippets"
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
    todos_db: TodosDb,
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

        plans = reconcile_snippets_for_purged_slugs(project_root, [row["slug"]], todo_status_map)
        _write_snippet_plans(_plans_for_paths(plans, pending_paths, project_root))
        return await _commit_and_finalize_removed_row(
            project_root,
            todos_db,
            row,
            pending_paths=pending_paths,
        )

    plans = reconcile_snippets_for_purged_slugs(project_root, [row["slug"]], todo_status_map)
    candidate_paths = [_repo_relative_path(project_root, plan.path) for plan in plans]
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
    _write_snippet_plans(plans)
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
    ) -> None:
        self._client = client
        self._output_poller = output_poller
        self._poller_watch_interval_s = poller_watch_interval_s
        self._restoring_sessions: set[str] = set()

    async def periodic_cleanup(self) -> None:
        """Clean up inactive sessions and orphans (runs forever)."""
        first_run = True
        while True:
            try:
                if not first_run:
                    await asyncio.sleep(3600)
                first_run = False

                await self._cleanup_inactive_sessions()
                await self._cleanup_removed_todos()
                await session_cleanup.emit_recently_closed_session_events()
                await session_cleanup.cleanup_orphan_tmux_sessions()
                await session_cleanup.cleanup_orphan_workspaces()
                await session_cleanup.cleanup_orphan_session_tmpdirs()
                await asyncio.to_thread(prune_session_map)
                now = datetime.now(UTC)
                runtime_cutoff_iso = (now - timedelta(days=7)).isoformat()
                now_iso = now.isoformat()
                await db.cleanup_stale_voice_assignments()
                await db.cleanup_terminal_voice_transcriptions(runtime_cutoff_iso)
                await _cleanup_orphan_voice_audio_files(now=now)
                await db.cleanup_inbound(runtime_cutoff_iso)
                await db.cleanup_orphan_inbound(now_iso)
                await db.cleanup_terminal_operations(runtime_cutoff_iso)
                await db.cleanup_webhook_outbox(runtime_cutoff_iso)
                await db.cleanup_hook_outbox(runtime_cutoff_iso)
                await db.cleanup_orphan_session_tokens()
                await db.cleanup_orphan_session_listeners()
                try:
                    event_db = await get_event_db()
                    await event_db.cleanup_runtime_events(older_than=now - timedelta(days=7))
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
                await self._check_idle_compaction()
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
            if await polling_coordinator.is_polling(session.session_id):
                continue

            if session.tmux_session_name not in active_tmux_sessions:
                if session.session_id not in self._restoring_sessions:
                    self._restoring_sessions.add(session.session_id)
                    asyncio.create_task(self._restore_tmux_session(session), name=f"restore-tmux-{session.session_id}")
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
                    await db.update_session(session.session_id, lifecycle_status="closed")
                # Purge closed sessions older than the 90-day cutoff.
                if session.closed_at < cutoff_time:
                    logger.info(
                        "Purging old closed session %s (closed %s ago)",
                        session.session_id,
                        datetime.now(UTC) - session.closed_at,
                    )
                    await session_cleanup.terminate_session(
                        session.session_id,
                        self._client,
                        reason="closed_expired",
                        session=session,
                        kill_tmux=False,
                        delete_db=True,
                    )
                continue

            # Open sessions are never auto-closed. Users and agents close them explicitly.
            # The cleanup routine only purges closed sessions past the retention window.

    async def _cleanup_removed_todos(self) -> None:
        """Finalize soft-removed todos past the retention window across every project DB.

        Discovers project todo stores via the same trusted-dirs pattern that
        powers ``list_projects`` (the per-project ``.teleclaude/todos.db``
        location is the canonical workflow store; the daemon's operational DB
        knows nothing about per-project todos). For each expired removed row,
        reconcile snippet lifecycle frontmatter before hard-delete and commit
        the documentation change with verification.
        """
        cutoff_iso = (datetime.now(UTC) - REMOVED_TODO_RETENTION_WINDOW).isoformat()
        for trusted_dir in config.computer.get_all_trusted_dirs():
            expanded_path = os.path.expanduser(os.path.expandvars(trusted_dir.path))
            project_root = Path(expanded_path)
            if not project_root.exists():
                continue
            if not (project_root / ".teleclaude" / "todos.db").exists():
                continue
            try:
                todos_db = await get_todos_db(str(project_root))
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

    async def _check_idle_compaction(self) -> None:
        """Detect idle long-lived sessions and mark them for memory extraction.

        Any session with a human_role (customer, member, etc.) is eligible for
        idle compaction. When idle beyond COMPACTION_IDLE_THRESHOLD_S, the daemon:
        1. Updates last_memory_extraction_at to mark the extraction window
        2. A separate extraction job reads the transcript and saves memories
        3. After extraction, /compact is injected to keep the session lean

        Session termination is handled separately by _cleanup_inactive_sessions.
        """
        now = datetime.now(UTC)
        idle_threshold = timedelta(seconds=COMPACTION_IDLE_THRESHOLD_S)
        sessions = await db.get_active_sessions()

        for session in sessions:
            # Only compact sessions with a human role (long-lived interactive sessions)
            if not session.human_role:
                continue

            if not session.last_activity:
                continue

            idle_duration = now - session.last_activity
            if idle_duration < idle_threshold:
                continue

            # Skip if extraction was already triggered recently (within the idle threshold)
            if session.last_memory_extraction_at:
                if (now - session.last_memory_extraction_at) < idle_threshold:
                    continue

            # Mark the session for memory extraction
            extraction_marker = now.isoformat()
            await db.update_session(
                session.session_id,
                last_memory_extraction_at=extraction_marker,
            )
            logger.info(
                "Session idle compaction triggered",
                session_id=session.session_id,
                idle_seconds=idle_duration.total_seconds(),
                human_role=session.human_role,
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

    async def _restore_tmux_session(self, session: Session) -> None:
        """Recreate a missing tmux session and restart the agent. Runs as a background task.

        Critical: only inject the launcher when the tmux session is actually missing.
        If the tmux session already exists, the foreground is the live agent TUI and
        any send-keys would land in its input buffer as paste-text rather than
        starting a fresh shell. The poller_watch can spuriously trigger restoration
        when ``tmux list-sessions`` is briefly slow, so an early-exit guard here is
        load-bearing — without it, the launcher command shows up as a user prompt.
        """
        try:
            if await tmux_bridge.session_exists(session.tmux_session_name, log_missing=False):
                return

            working_dir = resolve_working_dir(session.project_path, session.subdir)
            env_vars = await self._build_tmux_env_vars(session)
            if not await ensure_tmux_with_identity(session, session.tmux_session_name, working_dir, env_vars):
                return

            if not (session.active_agent and session.native_session_id):
                return

            cmd = get_agent_command(
                agent=session.active_agent,
                thinking_mode=session.thinking_mode,
                exec=False,
                native_session_id=session.native_session_id,
            )

            # Subscribe BEFORE the restore paste — the agent's SessionStart
            # hook can race the paste pipeline and emit AGENT_READY before
            # this coroutine subscribes. event_bus has no replay.
            loop = asyncio.get_running_loop()
            ready_future: asyncio.Future[None] = loop.create_future()

            async def _on_ready(_event_type: str, ctx: SessionLifecycleContext) -> None:
                if ctx.session_id == session.session_id and not ready_future.done():
                    ready_future.set_result(None)

            ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)
            try:
                if not await tmux_bridge.send_keys_existing_tmux(
                    session_name=session.tmux_session_name,
                    text=cmd,
                    active_agent=session.active_agent,
                ):
                    logger.warning(
                        "Failed to restore agent %s for session %s",
                        session.active_agent,
                        session.session_id,
                    )
                    return

                logger.info(
                    "Restored agent %s for session %s (native=%s)",
                    session.active_agent,
                    session.session_id,
                    session.native_session_id,
                )

                try:
                    await asyncio.wait_for(ready_future, timeout=AGENT_PROMPT_READY_TIMEOUT_S)
                except TimeoutError:
                    logger.warning(
                        "Restored tmux for session %s but agent did not reach ready prompt; stimulus not sent.",
                        session.session_id,
                    )
                    return
            finally:
                event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

            delivered = await tmux_io.inject_user_turn(
                session,
                RESTART_CONTINUATION_STIMULUS,
                active_agent=session.active_agent,
            )
            if not delivered:
                logger.warning(
                    "Restored agent %s for session %s but continuation stimulus was not confirmed.",
                    session.active_agent,
                    session.session_id,
                )
        finally:
            self._restoring_sessions.discard(session.session_id)

    async def _build_tmux_env_vars(self, session: Session) -> dict[str, str]:
        voice = await db.get_voice(session.session_id)
        return build_agent_session_environment(
            project_path=session.project_path,
            platform_env=get_voice_env_vars(voice) if voice else {},
        )
