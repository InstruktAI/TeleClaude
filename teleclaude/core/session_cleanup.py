"""Session cleanup utilities for handling stale and orphan sessions.

Stale session: exists in DB as active, but tmux session is gone.
Orphan tmux session: tmux session exists with tc_ prefix, but no DB entry.

This can happen when:
- User manually closes Telegram topic
- tmux session is killed externally
- Daemon crashes without proper cleanup
- DB is cleared but tmux sessions remain
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from stat import S_ISDIR
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AgentName
from teleclaude.caller_identity import is_desk_role
from teleclaude.core import tmux_bridge
from teleclaude.core.dates import ensure_utc
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload, SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.models import RelayStatus, encode_relay_exchange
from teleclaude.core.session_ended import report_session_ended
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_links import cleanup_session_links
from teleclaude.core.session_listeners import cleanup_caller_listeners, pop_listeners
from teleclaude.core.session_runtime_gate import clear_relaunch_awaiting_readiness
from teleclaude.core.session_status import SessionLifecycleStatus, is_close_started
from teleclaude.core.session_utils import OUTPUT_DIR, get_session_output_dir
from teleclaude.events.envelope import EventVisibility
from teleclaude.paths import session_tmp_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session
    from teleclaude.core.reminders import ReminderService
from teleclaude.core.inbound_queue import get_inbound_queue_manager

logger = get_logger(__name__)

_SOFT_DELETED_IN_DATABASE_EVENT = "session_cleanup.soft_deleted"
_LEGACY_RESTRICTED_SESSION_ENDED_EVENT = "legacy_restricted_session_ended"
_LEGACY_RESTRICTED_SESSION_REASON = "legacy_restricted_session"

# TeleClaude tmux session prefix - used to identify owned sessions
TMUX_SESSION_PREFIX = "tc_"
TMUX_TUI_SESSION_NAME = "tc_tui"
TMUX_SESSION_NAME_UNBOUND = ""
_HOST_RELEASE_OBSERVATION_FAILED_EVENT = "session_host_release_observation_failed"
_HOST_BINDING_RELEASE_FAILED_EVENT = "session_host_binding_release_failed"
_HOST_BINDING_RELEASE_ROW_MISSING_REASON = "session row missing during host binding release"
_PROCEDURE_EVENT_SESSION_CLOSED_REASON = "session_closed"
_PROCEDURE_EVENT_SESSION_CLEANUP_EVENT = "procedure_event_session_cleanup"


def host_pane_name(session_id: str) -> str:
    """Return the TeleClaude-prefixed tmux host-pane name for a session id."""
    return f"{TMUX_SESSION_PREFIX}{session_id}"


async def _publish_host_release(session: Session, *, kill_succeeded: bool) -> None:
    """Publish host release only after successful termination or strict absence."""
    if not kill_succeeded:
        try:
            snapshot = await tmux_bridge.collect_pane_snapshot(session.tmux_session_name, capture_lines=1)
        except Exception as exc:
            logger.error(
                _HOST_RELEASE_OBSERVATION_FAILED_EVENT,
                session_id=session.session_id,
                tmux_session_name=session.tmux_session_name,
                error=str(exc),
                exc_info=True,
            )
            return
        if snapshot.session_exists:
            return

    try:
        updated = await db.update_session(session.session_id, tmux_session_name=TMUX_SESSION_NAME_UNBOUND)
    except Exception as exc:
        logger.error(
            _HOST_BINDING_RELEASE_FAILED_EVENT,
            session_id=session.session_id,
            tmux_session_name=session.tmux_session_name,
            error=str(exc),
            exc_info=True,
        )
        return
    if updated is None:
        logger.error(
            _HOST_BINDING_RELEASE_FAILED_EVENT,
            session_id=session.session_id,
            tmux_session_name=session.tmux_session_name,
            reason=_HOST_BINDING_RELEASE_ROW_MISSING_REASON,
        )


# Lookback window for replaying cleanup for closed sessions from an earlier process instance.
# Only sessions with unresolved channel references (e.g. topic_id still set) are replayed.
# One minute covers the restart window without replaying hours of old sessions.
RECENTLY_CLOSED_SESSION_SECONDS = 60
SESSION_TMPDIR_RACE_SAFETY = timedelta(minutes=10)

# Bound for waiting on the host pane's process tree to exit before the
# per-session tmpdir is removed. A reap that exceeds this bound logs the
# surviving pids and continues rather than stranding the lifecycle write.
SESSION_PROCESS_REAP_TIMEOUT = 5.0

# Concurrency guard: session IDs whose cleanup is currently in flight.
# Prevents duplicate terminate_session calls from parallel SESSION_CLOSE_REQUESTED events.
_cleanup_in_flight: set[str] = set()
_reminder_service: ReminderService | None = None


def configure_reminder_service(service: ReminderService) -> None:
    """Wire the daemon-owned reminder service into the shared cleanup path."""
    global _reminder_service
    _reminder_service = service


async def _clear_session_reminders(session_id: str) -> None:
    if _reminder_service is None:
        return
    try:
        await _reminder_service.clear_session(session_id=session_id, operation_id=str(uuid4()))
    except Exception as exc:
        logger.error(
            "session_close_reminder_clear_failed",
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )


async def _suspend_procedure_events_on_session_close(session_id: str, *, soft_delete: bool) -> None:
    """Suspend responsibility work before close, retaining only live session state for revival."""
    suspended_count = await db.suspend_procedure_events_for_session(
        session_id=session_id,
        reason=_PROCEDURE_EVENT_SESSION_CLOSED_REASON,
    )
    logger.info(
        _PROCEDURE_EVENT_SESSION_CLEANUP_EVENT,
        session_id=session_id,
        suspended_count=suspended_count,
    )
    if soft_delete:
        await db.remove_procedure_event_delivery_session(session_id=session_id)


def _is_uuid_name(value: str) -> bool:
    """Return whether a directory name is a canonical UUID."""
    try:
        parsed = UUID(value)
    except ValueError:
        return False
    return str(parsed) == value.lower()


def _path_is_under_base(path: Path, base: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_base = base.resolve()
    except OSError:
        return False
    return resolved_path == resolved_base or resolved_base in resolved_path.parents


def _session_tmpdir_path(session_id: str) -> Path:
    return session_tmp_dir(session_id)


def _rmtree_ignore_vanished(func: object, path: str, exc: BaseException) -> None:
    # Node's compile-cache (and similar) may delete files mid-walk; treat
    # FileNotFoundError as benign so cleanup doesn't strand the session.
    del func, path
    if isinstance(exc, FileNotFoundError):
        return
    raise exc


async def cleanup_session_tmpdir(session_id: str) -> bool:
    """Delete the configured per-session TMPDIR for a closed session."""
    base_dir = tmux_bridge.get_session_tmpdir_base()
    session_tmpdir = _session_tmpdir_path(session_id)
    if not session_tmpdir.exists():
        return False
    if session_tmpdir.is_symlink() or not session_tmpdir.is_dir():
        logger.warning("Skipping unsafe session TMPDIR cleanup path: %s", session_tmpdir)
        return False
    if not _path_is_under_base(session_tmpdir, base_dir):
        logger.warning("Skipping session TMPDIR outside configured base: %s", session_tmpdir)
        return False
    await asyncio.to_thread(shutil.rmtree, session_tmpdir, onexc=_rmtree_ignore_vanished)
    logger.debug("Deleted session TMPDIR for %s", session_id)
    return True


# Claude Code keeps per-session scratchpads and task outputs under
# <temp base>/claude-<uid>/<project-slug>/<native session id>/.
CLAUDE_TEMP_BASES = (Path("/private/tmp"), Path("/tmp"))
CLAUDE_TEMP_DIR_PREFIX = "claude-"
_CLAUDE_TMPDIR_REMOVED_EVENT = "session_close_claude_tmpdir_removed"
_CLAUDE_TMPDIR_CLEANUP_FAILED_EVENT = "session_close_claude_tmpdir_cleanup_failed"


def _claude_temp_root() -> Path | None:
    """Return the current user's Claude Code temp root.

    The world-writable parent lets anyone pre-create this path, so only a real
    directory owned by the current user is accepted — never a symlink.
    """
    uid = os.getuid()
    for base in CLAUDE_TEMP_BASES:
        candidate = base / (CLAUDE_TEMP_DIR_PREFIX + str(uid))
        try:
            stat = candidate.lstat()
        except FileNotFoundError:
            continue
        if S_ISDIR(stat.st_mode) and stat.st_uid == uid:
            return candidate
    return None


async def cleanup_claude_session_tmpdir(session: Session) -> int:
    """Delete Claude Code's temp directory for a purged Claude session.

    Returns the number of directories removed.
    """
    native_session_id = session.native_session_id
    if session.active_agent != AgentName.CLAUDE or not native_session_id or not _is_uuid_name(native_session_id):
        return 0
    root = _claude_temp_root()
    if root is None:
        return 0

    removed = 0
    for project_dir in root.iterdir():
        if project_dir.is_symlink() or not project_dir.is_dir():
            continue
        candidate = project_dir / native_session_id
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        await asyncio.to_thread(shutil.rmtree, candidate, onexc=_rmtree_ignore_vanished)
        removed += 1
        logger.info(_CLAUDE_TMPDIR_REMOVED_EVENT, session_id=session.session_id, path=str(candidate))
    return removed


async def cleanup_orphan_session_tmpdirs(
    *,
    race_safety_age: timedelta = SESSION_TMPDIR_RACE_SAFETY,
) -> int:
    """Reconcile per-session TMPDIRs against DB truth."""
    base_dir = tmux_bridge.get_session_tmpdir_base()
    if not base_dir.exists() or not base_dir.is_dir() or base_dir.is_symlink():
        return 0

    now = datetime.now(UTC)
    sessions = await db.get_all_sessions()
    live_session_ids = {
        session.session_id
        for session in sessions
        if not session.closed_at and (session.lifecycle_status or "active") != "closed"
    }

    removed_count = 0
    for candidate in base_dir.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if not _is_uuid_name(candidate.name):
            continue
        try:
            modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if now - modified_at < race_safety_age:
            continue
        if candidate.name in live_session_ids:
            continue
        if not _path_is_under_base(candidate, base_dir):
            continue
        try:
            await asyncio.to_thread(shutil.rmtree, candidate)
            removed_count += 1
            logger.info("Removed orphan session TMPDIR: %s", candidate)
        except OSError as exc:
            logger.warning("Failed to remove orphan session TMPDIR %s: %s", candidate, exc)

    return removed_count


async def cleanup_session_resources(
    session: Session,
    adapter_client: AdapterClient,
    *,
    delete_channel: bool = True,
) -> None:
    """Clean up session resources: channels, listeners, and workspace directory.

    Shared cleanup logic used by both explicit exit and stale session cleanup.
    Does NOT modify DB state - caller handles that.

    Args:
        session: Session object (must be fetched before DB deletion)
        adapter_client: AdapterClient for deleting channels
    """
    session_id = session.session_id

    closed_links = await cleanup_session_links(session_id)
    if closed_links:
        logger.debug(
            "Closed %d conversation link(s) for terminated session %s",
            closed_links,
            session_id,
        )

    # Remove listeners waiting on this session (target listeners)
    target_listeners = await pop_listeners(session_id)
    if target_listeners:
        logger.debug(
            "Cleaned up %d listener(s) for terminated target session %s",
            len(target_listeners),
            session_id,
        )

    # Clean up any listeners this session registered (as a caller waiting for other sessions)
    await cleanup_caller_listeners(session_id)

    if delete_channel:
        # Delete channel/topic in all UI adapters
        try:
            await adapter_client.delete_channel(session)
            logger.info("Deleted channels for session %s", session_id)
        except Exception as e:
            logger.warning("Failed to delete channels for session %s: %s", session_id, e)

    # Clean up entire workspace directory (workspace/{session_id}/)
    workspace_dir = get_session_output_dir(session_id)
    if workspace_dir.exists():
        try:
            await asyncio.to_thread(shutil.rmtree, workspace_dir)
            logger.debug("Deleted workspace directory for session %s", session_id)
        except Exception as e:
            logger.warning("Failed to delete workspace for session %s: %s", session_id, e)


async def _end_escalation_if_active(session: Session) -> None:
    """Clear relay state and emit escalation_ended if session was escalated."""
    if session.relay_status != RelayStatus.ACTIVE:
        return
    await db.update_session(
        session.session_id,
        relay_status=None,
        relay_channel_id=None,
        relay_started_at=None,
    )
    await db.update_session(session.session_id, relay_exchange=encode_relay_exchange(()))
    event_bus.emit(
        "session.escalation_ended",  # type: ignore[arg-type]
        SessionEscalatedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )
    logger.info("Escalation ended (session close) for %s", session.session_id)


async def terminate_session(
    session_id: str,
    adapter_client: AdapterClient,
    *,
    reason: str,
    session: Session | None = None,
    kill_tmux: bool | None = None,
    delete_channel: bool = True,
    soft_delete: bool = False,
    expire_inbound: bool = True,
) -> bool:
    """Terminate a session and mark it closed in the DB.

    Args:
        session_id: Session identifier
        adapter_client: AdapterClient for deleting channels
        reason: Reason for termination (for logs)
        session: Optional pre-fetched session object
        kill_tmux: Whether to kill tmux (defaults to True)
        delete_channel: Whether to delete adapter channels/topics
        soft_delete: Whether the retained record is also removed from ordinary navigation
        expire_inbound: Whether input still queued for the session is dropped; a close that
            keeps the conversation (the idle close) leaves it queued, and its delivery resumes the session

    Returns:
        True if session was terminated, False if session not found or already in flight
    """
    if session_id in _cleanup_in_flight:
        logger.debug("Session %s cleanup already in flight; skipping duplicate", session_id)
        return False
    _cleanup_in_flight.add(session_id)
    try:
        return await _terminate_session_inner(
            session_id,
            adapter_client,
            reason=reason,
            session=session,
            kill_tmux=kill_tmux,
            delete_channel=delete_channel,
            soft_delete=soft_delete,
            expire_inbound=expire_inbound,
        )
    finally:
        _cleanup_in_flight.discard(session_id)


async def _write_session_end(session: Session, *, soft_delete: bool, already_closed: bool) -> None:
    """Write the end of a session — close its retained record, or also soft-delete it — and report an ending that happens now.

    The record held here is what the report states, so the soft-deletion variant reports from it too. A
    session that was already closed was reported when it closed.
    """
    if not already_closed:
        await db.close_session(session.session_id)
        logger.info("Closed session %s in database", session.session_id)
    if soft_delete:
        await db.soft_delete_session(session.session_id)
        logger.info(_SOFT_DELETED_IN_DATABASE_EVENT, session_id=session.session_id)
    if not already_closed:
        await report_session_ended(session)


async def _terminate_session_inner(
    session_id: str,
    adapter_client: AdapterClient,
    *,
    reason: str,
    session: Session | None = None,
    kill_tmux: bool | None = None,
    delete_channel: bool = True,
    soft_delete: bool = False,
    expire_inbound: bool = True,
) -> bool:
    """Inner implementation of terminate_session (called only when not in flight)."""
    session = session or await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found for termination", session_id)
        return False
    already_closed = bool(session.closed_at)
    if already_closed and not soft_delete:
        logger.debug("Session %s already closed; proceeding with cleanup", session_id)

    logger.info("Terminating session %s (%s)", session_id, reason)

    if not already_closed and not is_close_started(lifecycle_status=session.lifecycle_status):
        await transition_session(
            db,
            session_id,
            LifecycleTransition(SessionLifecycleStatus.CLOSING, LifecycleTransitionReason.CLOSE_STARTED),
        )

    if kill_tmux is None:
        kill_tmux = True

    # Once tmux is killed, the session is unrecoverable from the user's view.
    # Best-effort all subsequent cleanup so a single hiccup (e.g. an rmtree race
    # on a per-session tmpdir) cannot strand the record at lifecycle=closing —
    # the DB close at the end must always run.
    try:
        # Headless sessions have no tmux — skip kill to avoid errors.
        if kill_tmux and session.tmux_session_name:
            # Captured before kill_session: get_pane_pid cannot resolve a
            # destroyed tmux session, so the process set must be known first.
            process_tree = await tmux_bridge.get_pane_process_tree(session.tmux_session_name)

            killed = False
            try:
                killed = await tmux_bridge.kill_session(session.tmux_session_name)
                if killed:
                    logger.info("Killed tmux session %s", session.tmux_session_name)
                else:
                    logger.warning("Failed to kill tmux session %s", session.tmux_session_name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to kill tmux session %s: %s", session.tmux_session_name, exc)

            await _publish_host_release(session, kill_succeeded=killed)

            if process_tree is None:
                logger.warning(
                    "Pane process tree for %s could not be resolved before tmpdir cleanup; removal is unguarded",
                    session.tmux_session_name,
                )
            elif process_tree:
                surviving = await tmux_bridge.wait_for_processes_exit(process_tree, SESSION_PROCESS_REAP_TIMEOUT)
                if surviving:
                    logger.warning(
                        "Pane processes for %s outlived the %.1fs reap bound: pids=%s",
                        session.tmux_session_name,
                        SESSION_PROCESS_REAP_TIMEOUT,
                        [proc.pid for proc in surviving],
                    )
        elif session.tmux_session_name and not already_closed and not soft_delete:
            await _publish_host_release(session, kill_succeeded=False)

        try:
            await cleanup_session_resources(session, adapter_client, delete_channel=delete_channel)
        except Exception as exc:
            logger.error(
                "session_close_resource_cleanup_failed",
                session_id=session.session_id,
                error=str(exc),
                exc_info=True,
            )

        try:
            await cleanup_session_tmpdir(session.session_id)
        except Exception as exc:
            logger.error(
                "session_close_tmpdir_cleanup_failed",
                session_id=session.session_id,
                error=str(exc),
                exc_info=True,
            )

        # A closed session stays revivable with its Claude scratchpad until it is
        # soft-deleted, so the Claude temp directory goes only with the removal.
        if soft_delete:
            try:
                await cleanup_claude_session_tmpdir(session)
            except Exception as exc:
                logger.error(
                    _CLAUDE_TMPDIR_CLEANUP_FAILED_EVENT,
                    session_id=session.session_id,
                    error=str(exc),
                    exc_info=True,
                )

        await _suspend_procedure_events_on_session_close(session.session_id, soft_delete=soft_delete)

        # Expire any pending inbound messages before marking the session closed. A close that keeps
        # the conversation leaves them queued: their delivery resumes the session.
        if expire_inbound:
            try:
                await get_inbound_queue_manager().expire_session(session.session_id)
            except RuntimeError:
                pass  # Queue manager not initialized (e.g. tests) — skip
            except Exception as exc:
                logger.error(
                    "session_close_inbound_expire_failed",
                    session_id=session.session_id,
                    error=str(exc),
                    exc_info=True,
                )

        removed_control_payloads = await db.discard_pending_control_payloads(session_id=session.session_id)
        logger.info(
            "control_delivery_session_cleanup",
            session_id=session.session_id,
            removed_count=removed_control_payloads,
        )

        await _clear_session_reminders(session.session_id)

        try:
            await _end_escalation_if_active(session)
        except Exception as exc:
            logger.error(
                "session_close_end_escalation_failed",
                session_id=session.session_id,
                error=str(exc),
                exc_info=True,
            )
    finally:
        await _write_session_end(session, soft_delete=soft_delete, already_closed=already_closed)
        clear_relaunch_awaiting_readiness(session.session_id)
    return not already_closed or soft_delete


async def emit_recently_closed_session_events(
    *,
    seconds: float = RECENTLY_CLOSED_SESSION_SECONDS,
    include_headless: bool = True,
) -> int:
    """Replay SESSION_CLOSE_REQUESTED for closed sessions with unresolved channel cleanup.

    Used by maintenance to recover cleanup missed across daemon restarts. Only replays
    sessions that are closed in DB but still have a Telegram topic_id (or other adapter
    channel reference) persisted — indicating the channel deletion never completed.

    Emits SESSION_CLOSE_REQUESTED (not SESSION_CLOSED) so that terminate_session runs
    exactly once and clears the channel reference on success.

    Retained: most callers of terminate_session close a session with no command
    behind them, so no durable operation row exists to answer for their channel
    cleanup after a daemon restart. Only a CloseSessionCommand-originated close is
    now covered by the operation row; this sweep is still what recovers the rest.

    Returns:
        Number of sessions for which a SESSION_CLOSE_REQUESTED event was emitted.
    """
    if seconds <= 0:
        return 0

    cutoff = datetime.now(UTC) - timedelta(seconds=seconds)
    sessions = await db.list_sessions(
        include_closed=True,
        include_initializing=True,
        include_headless=include_headless,
    )

    emitted = 0
    for session in sessions:
        if not session.closed_at:
            continue
        if session.closed_at < cutoff:
            continue

        # Only replay if channel cleanup is still pending (topic_id or discord channel still set).
        # If already cleared, the cleanup already completed — skip to avoid duplicate deletes.
        telegram_topic_id = session.get_origin_section("telegram").get("topic_id")
        discord_channel_id = session.get_origin_section("discord").get("channel_id")
        if telegram_topic_id is None and discord_channel_id is None:
            logger.debug(
                "Skipping replay for session %s: channel already cleared",
                session.session_id,
            )
            continue

        event_bus.emit(
            TeleClaudeEvents.SESSION_CLOSE_REQUESTED,
            SessionLifecycleContext(session_id=session.session_id),
            visibility=EventVisibility.CLUSTER,
        )
        emitted += 1
        logger.info(
            "Replayed session_close_requested for session %s (closed_at=%s, pending cleanup)",
            session.session_id,
            session.closed_at.isoformat(),
        )

    return emitted


def is_legacy_restricted_session(session: Session) -> bool:
    """Whether a session sits at the help desk without the confinement recorded at its creation.

    Every desk session created under desk confinement carries the stamp in
    the write that created it, so a desk-role session without it predates the
    confinement and is never delivered to.
    """
    return is_desk_role(session.system_role or None, session.human_role) and session.confinement_profile is None


async def end_legacy_restricted_sessions(adapter_client: AdapterClient) -> int:
    """End every open desk-role session that lacks the creation-time confinement stamp."""
    sessions = await db.list_sessions(include_initializing=True, include_headless=True)
    ended = 0
    for session in sessions:
        if not is_legacy_restricted_session(session):
            continue
        if await terminate_session(
            session.session_id, adapter_client, reason=_LEGACY_RESTRICTED_SESSION_REASON, session=session
        ):
            ended += 1
    logger.info(_LEGACY_RESTRICTED_SESSION_ENDED_EVENT, count=ended)
    return ended


async def cleanup_stale_session(session_id: str, adapter_client: AdapterClient) -> bool:
    """Clean up a single stale session.

    Returns:
        True if session was stale and cleaned up, False if session is healthy.
    """
    session = await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found in database", session_id)
        return False

    # Don't flag sessions that are still being created (race condition guard)
    if session.created_at:
        session_age = (datetime.now(UTC) - ensure_utc(session.created_at)).total_seconds()
        if session_age < 10.0:
            logger.debug("Session %s is too young (%.1fs), skipping stale check", session_id, session_age)
            return False

    # Headless sessions have no tmux — they are never "stale" by tmux check;
    # they get cleaned up only when explicitly closed by user or agent.
    if not session.tmux_session_name:
        return False

    exists = await tmux_bridge.session_exists(session.tmux_session_name)
    if exists:
        return False

    logger.warning(
        "Found stale session %s (tmux %s no longer exists), cleaning up",
        session_id,
        session.tmux_session_name,
    )
    cleaned = await terminate_session(
        session_id,
        adapter_client,
        reason="stale",
        session=session,
        kill_tmux=False,
    )
    if cleaned:
        logger.info("Cleaned up stale session %s", session_id)
    return cleaned


async def cleanup_all_stale_sessions(adapter_client: AdapterClient) -> int:
    """Find and clean up all stale sessions.

    Returns:
        Number of stale sessions cleaned up.
    """
    logger.info("Starting stale session cleanup scan")

    active_sessions = await db.get_active_sessions()
    if not active_sessions:
        logger.debug("No active sessions to check")
        return 0

    logger.info("Checking %d active sessions for staleness", len(active_sessions))

    cleaned_count = 0
    for session in active_sessions:
        was_stale = await cleanup_stale_session(session.session_id, adapter_client)
        if was_stale:
            cleaned_count += 1

    if cleaned_count > 0:
        logger.info("Cleaned up %d stale sessions", cleaned_count)
    else:
        logger.debug("No stale sessions found")

    return cleaned_count


async def cleanup_orphan_tmux_sessions() -> int:
    """Kill TeleClaude tmux sessions that have no corresponding DB entry.

    Orphan sessions can occur when:
    - Database is cleared but tmux sessions remain
    - Session creation fails after tmux is created but before DB insert
    - Manual intervention leaves tmux sessions behind

    Only kills sessions with the tc_ prefix (TeleClaude-owned).

    The known set a row owns is either its recorded tmux_session_name, or,
    for a row that is still creating its first host pane (lifecycle status
    initializing with no recorded name yet), the host pane its creation path
    will bind — sparing that pane from being reaped mid-bootstrap.

    Returns:
        Number of orphan tmux sessions killed
    """
    tmux_sessions = await tmux_bridge.list_tmux_sessions()
    if not tmux_sessions:
        logger.debug("No tmux sessions found")
        return 0

    # Filter to only TeleClaude-owned sessions (exclude TUI wrapper session)
    tc_sessions = [s for s in tmux_sessions if s.startswith(TMUX_SESSION_PREFIX) and s != TMUX_TUI_SESSION_NAME]
    if not tc_sessions:
        logger.debug("No TeleClaude tmux sessions found")
        return 0

    # Get all known tmux session names from DB
    all_sessions = await db.get_all_sessions()
    known_tmux_names = {s.tmux_session_name for s in all_sessions}
    known_tmux_names.update(
        host_pane_name(s.session_id)
        for s in all_sessions
        if not s.tmux_session_name and s.lifecycle_status == SessionLifecycleStatus.INITIALIZING
    )

    killed_count = 0
    for tmux_name in tc_sessions:
        if tmux_name not in known_tmux_names:
            logger.warning("Found orphan tmux session: %s (not in DB), killing", tmux_name)
            success = await tmux_bridge.kill_session(tmux_name)
            if success:
                killed_count += 1
                logger.info("Killed orphan tmux session: %s", tmux_name)
            else:
                logger.error("Failed to kill orphan tmux session: %s", tmux_name)

    if killed_count > 0:
        logger.info("Killed %d orphan tmux sessions", killed_count)

    return killed_count


async def cleanup_orphan_workspaces() -> int:
    """Remove workspace directories that have no corresponding active DB entry.

    Orphan workspaces can occur when:
    - Database is cleared but workspace directories remain
    - Session cleanup fails to remove workspace
    - Manual intervention or crashes leave directories behind
    - Sessions were terminated but workspace cleanup didn't happen

    Returns:
        Number of orphan workspace directories removed
    """
    if not OUTPUT_DIR.exists():
        logger.debug("Workspace directory does not exist")
        return 0

    # Get all active session IDs from DB
    all_sessions = await db.get_all_sessions()
    known_session_ids = {s.session_id for s in all_sessions}

    removed_count = 0
    for workspace_dir in OUTPUT_DIR.iterdir():
        if workspace_dir.is_symlink() or not workspace_dir.is_dir():
            continue
        if not _is_uuid_name(workspace_dir.name):
            continue

        session_id = workspace_dir.name
        if session_id not in known_session_ids:
            logger.warning("Found orphan workspace: %s (not active in DB), removing", session_id)
            try:
                await asyncio.to_thread(shutil.rmtree, workspace_dir)
                removed_count += 1
                logger.info("Removed orphan workspace: %s", session_id)
            except Exception as e:
                logger.error("Failed to remove orphan workspace %s: %s", session_id, e)

    if removed_count > 0:
        logger.info("Removed %d orphan workspace directories", removed_count)

    return removed_count
