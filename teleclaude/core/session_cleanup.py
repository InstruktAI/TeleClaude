"""Session cleanup utilities for handling stale and orphan sessions.

Stale session: exists in DB as active, but tmux session is gone.
Orphan tmux session: tmux session exists with tc_ prefix, but no DB entry.

This can happen when:
- User manually closes Telegram topic
- tmux session is killed externally
- Daemon crashes without proper cleanup
- DB is cleared but tmux sessions remain
"""

import asyncio
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from instrukt_ai_logging import get_logger

from teleclaude.api.auth import invalidate_session_cache, invalidate_token_cache
from teleclaude.core import tmux_bridge
from teleclaude.core.dates import ensure_utc
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionEscalatedPayload, SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.session_listeners import cleanup_caller_listeners, cleanup_session_links, pop_listeners
from teleclaude.core.session_utils import OUTPUT_DIR, get_session_output_dir
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session
from teleclaude.core.inbound_queue import get_inbound_queue_manager

logger = get_logger(__name__)

# TeleClaude tmux session prefix - used to identify owned sessions
TMUX_SESSION_PREFIX = "tc_"
TMUX_TUI_SESSION_NAME = "tc_tui"

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
    safe_id = tmux_bridge.safe_session_tmp_component(session_id)
    return tmux_bridge.get_session_tmpdir_base() / safe_id


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
    session: "Session",
    adapter_client: "AdapterClient",
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


async def _end_escalation_if_active(session: "Session") -> None:
    """Clear relay state and emit escalation_ended if session was escalated."""
    if session.relay_status != "active":
        return
    await db.update_session(
        session.session_id,
        relay_status=None,
        relay_channel_id=None,
        relay_started_at=None,
    )
    event_bus.emit(
        "session.escalation_ended",  # type: ignore[arg-type]
        SessionEscalatedPayload(session_id=session.session_id),
        visibility=EventVisibility.CLUSTER,
    )
    logger.info("Escalation ended (session close) for %s", session.session_id)


async def terminate_session(
    session_id: str,
    adapter_client: "AdapterClient",
    *,
    reason: str,
    session: Optional["Session"] = None,
    kill_tmux: bool | None = None,
    delete_channel: bool = True,
    delete_db: bool = False,
) -> bool:
    """Terminate a session and mark it closed in the DB.

    Args:
        session_id: Session identifier
        adapter_client: AdapterClient for deleting channels
        reason: Reason for termination (for logs)
        session: Optional pre-fetched session object
        kill_tmux: Whether to kill tmux (defaults to True)
        delete_channel: Whether to delete adapter channels/topics

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
            delete_db=delete_db,
        )
    finally:
        _cleanup_in_flight.discard(session_id)


async def _terminate_session_inner(
    session_id: str,
    adapter_client: "AdapterClient",
    *,
    reason: str,
    session: Optional["Session"] = None,
    kill_tmux: bool | None = None,
    delete_channel: bool = True,
    delete_db: bool = False,
) -> bool:
    """Inner implementation of terminate_session (called only when not in flight)."""
    session = session or await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found for termination", session_id)
        return False
    already_closed = bool(session.closed_at)
    if already_closed and not delete_db:
        logger.debug("Session %s already closed; proceeding with cleanup", session_id)

    logger.info("Terminating session %s (%s)", session_id, reason)

    # Revoke session tokens early so any in-flight CLI calls with the old token are rejected.
    try:
        await db.revoke_session_tokens(session_id)
        invalidate_token_cache(session_id)
    except Exception as exc:
        logger.error("Failed to revoke tokens for session %s: %s", session_id, exc)

    if not already_closed:
        await db.update_session(session_id, lifecycle_status="closing")

    # Drop any cached pre-close session record AFTER the DB write so the next auth
    # cache miss reads the fresh closing/closed lifecycle state. Without this the
    # defense-in-depth check in _verify_token_identity can be bypassed for up to
    # the session-cache TTL after close starts.
    invalidate_session_cache(session_id)

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

            try:
                killed = await tmux_bridge.kill_session(session.tmux_session_name)
                if killed:
                    logger.info("Killed tmux session %s", session.tmux_session_name)
                else:
                    logger.warning("Failed to kill tmux session %s", session.tmux_session_name)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to kill tmux session %s: %s", session.tmux_session_name, exc)

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

        # Expire any pending inbound messages before marking the session closed.
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
        if delete_db:
            await db.delete_session(session.session_id)
            logger.info("Deleted session %s from database", session.session_id)
        elif not already_closed:
            await db.close_session(session.session_id)
            logger.info("Closed session %s in database", session.session_id)
        # Final cache invalidation after the lifecycle write so any token-auth
        # request after this point sees the closed state on its next DB read.
        invalidate_session_cache(session.session_id)
        invalidate_token_cache(session.session_id)
    return not already_closed or delete_db


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


async def cleanup_stale_session(session_id: str, adapter_client: "AdapterClient") -> bool:
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
        delete_db=True,
    )
    if cleaned:
        logger.info("Cleaned up stale session %s", session_id)
    return cleaned


async def cleanup_all_stale_sessions(adapter_client: "AdapterClient") -> int:
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
