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
import os
import shutil
import signal
import subprocess
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.dates import ensure_utc
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionLifecycleContext, TeleClaudeEvents
from teleclaude.core.next_machine.core import release_finalize_lock
from teleclaude.core.session_listeners import cleanup_caller_listeners, cleanup_session_links, pop_listeners
from teleclaude.core.session_utils import OUTPUT_DIR, get_session_output_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# TeleClaude tmux session prefix - used to identify owned sessions
TMUX_SESSION_PREFIX = "tc_"
TMUX_TUI_SESSION_NAME = "tc_tui"
_MCP_WRAPPER_MATCH = "bin/mcp-wrapper.py"

# Lookback window for replaying session_closed events for rows marked closed by an earlier
# process instance. Replays are safe but intentionally bounded.
RECENTLY_CLOSED_SESSION_HOURS = 12


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

    # Release any finalize lock held by this session (prevents stale locks on session death).
    project_path = getattr(session, "project_path", None)
    if project_path:
        release_finalize_lock(project_path, session_id)

    closed_links = await cleanup_session_links(session_id)
    if closed_links:
        logger.debug(
            "Closed %d conversation link(s) for terminated session %s",
            closed_links,
            session_id[:8],
        )

    # Remove listeners waiting on this session (target listeners)
    target_listeners = await pop_listeners(session_id)
    if target_listeners:
        logger.debug(
            "Cleaned up %d listener(s) for terminated target session %s",
            len(target_listeners),
            session_id[:8],
        )

    # Clean up any listeners this session registered (as a caller waiting for other sessions)
    await cleanup_caller_listeners(session_id)

    if delete_channel:
        # Delete channel/topic in all UI adapters
        try:
            await adapter_client.delete_channel(session)
            logger.info("Deleted channels for session %s", session_id[:8])
        except Exception as e:
            logger.warning("Failed to delete channels for session %s: %s", session_id[:8], e)

    # Clean up entire workspace directory (workspace/{session_id}/)
    workspace_dir = get_session_output_dir(session_id)
    if workspace_dir.exists():
        try:
            await asyncio.to_thread(shutil.rmtree, workspace_dir)
            logger.debug("Deleted workspace directory for session %s", session_id[:8])
        except Exception as e:
            logger.warning("Failed to delete workspace for session %s: %s", session_id[:8], e)


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
        True if session was terminated, False if session not found
    """
    session = session or await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found for termination", session_id[:8])
        return False
    already_closed = bool(session.closed_at)
    if already_closed and not delete_db:
        logger.debug("Session %s already closed; proceeding with cleanup", session_id[:8])

    logger.info("Terminating session %s (%s)", session_id[:8], reason)

    if not already_closed:
        await db.update_session(session_id, lifecycle_status="closing")

    if kill_tmux is None:
        kill_tmux = True

    # Headless sessions have no tmux — skip kill to avoid errors.
    if kill_tmux and session.tmux_session_name:
        try:
            killed = await tmux_bridge.kill_session(session.tmux_session_name)
            if killed:
                logger.info("Killed tmux session %s", session.tmux_session_name)
            else:
                logger.warning("Failed to kill tmux session %s", session.tmux_session_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to kill tmux session %s: %s", session.tmux_session_name, exc)

    await cleanup_session_resources(session, adapter_client, delete_channel=delete_channel)

    if delete_db:
        await db.delete_session(session.session_id)
        logger.info("Deleted session %s from database", session.session_id[:8])
    else:
        if not already_closed:
            await db.close_session(session.session_id)
            logger.info("Closed session %s in database", session.session_id[:8])
    return not already_closed or delete_db


async def emit_recently_closed_session_events(
    *,
    hours: float = RECENTLY_CLOSED_SESSION_HOURS,
    include_headless: bool = True,
) -> int:
    """Replay session_closed for closed sessions from the last *hours* window.

    Used by maintenance to recover closed sessions from daemon restarts or missed
    event delivery paths (for example, when sessions reach "closed" in DB before
    channel cleanup runs).

    Returns:
        Number of sessions for which a session_closed event was emitted.
    """
    if hours <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
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

        event_bus.emit(
            TeleClaudeEvents.SESSION_CLOSED,
            SessionLifecycleContext(session_id=session.session_id),
        )
        emitted += 1
        logger.info(
            "Replayed session_closed for session %s (closed_at=%s)",
            session.session_id[:8],
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
        logger.debug("Session %s not found in database", session_id[:8])
        return False

    # Don't flag sessions that are still being created (race condition guard)
    if session.created_at:
        session_age = (datetime.now(timezone.utc) - ensure_utc(session.created_at)).total_seconds()
        if session_age < 10.0:
            logger.debug("Session %s is too young (%.1fs), skipping stale check", session_id[:8], session_age)
            return False

    # Headless sessions have no tmux — they are never "stale" by tmux check;
    # they get cleaned up by the 72h inactivity sweep instead.
    if not session.tmux_session_name:
        return False

    exists = await tmux_bridge.session_exists(session.tmux_session_name)
    if exists:
        return False

    logger.warning(
        "Found stale session %s (tmux %s no longer exists), cleaning up",
        session_id[:8],
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
        logger.info("Cleaned up stale session %s", session_id[:8])
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


async def cleanup_orphan_mcp_wrappers() -> int:
    """Kill orphaned MCP wrapper processes (ppid=1).

    Returns:
        Number of wrapper processes signaled.
    """

    def _collect_orphans() -> list[int]:
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,command="],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to list processes for MCP wrapper cleanup: %s", e)
            return []

        orphans: list[int] = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 3:
                continue
            pid_str, ppid_str, command = parts
            try:
                ppid = int(ppid_str)
            except ValueError:
                continue
            if ppid != 1:
                continue
            if _MCP_WRAPPER_MATCH not in command:
                continue
            try:
                orphans.append(int(pid_str))
            except ValueError:
                continue
        return orphans

    orphan_pids = await asyncio.to_thread(_collect_orphans)
    if not orphan_pids:
        return 0

    killed = 0
    for pid in orphan_pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except ProcessLookupError:
            continue
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to terminate orphan MCP wrapper %s: %s", pid, e)

    if killed:
        logger.warning("Terminated %d orphan MCP wrapper process(es)", killed)
    return killed


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
        if not workspace_dir.is_dir():
            continue

        session_id = workspace_dir.name
        if session_id not in known_session_ids:
            logger.warning("Found orphan workspace: %s (not active in DB), removing", session_id[:8])
            try:
                shutil.rmtree(workspace_dir)
                removed_count += 1
                logger.info("Removed orphan workspace: %s", session_id[:8])
            except Exception as e:
                logger.error("Failed to remove orphan workspace %s: %s", session_id[:8], e)

    if removed_count > 0:
        logger.info("Removed %d orphan workspace directories", removed_count)

    return removed_count
