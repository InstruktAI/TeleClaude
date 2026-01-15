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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.session_listeners import cleanup_caller_listeners, pop_listeners
from teleclaude.core.session_utils import OUTPUT_DIR, get_session_output_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# TeleClaude tmux session prefix - used to identify owned sessions
TMUX_SESSION_PREFIX = "tc_"
TMUX_TUI_SESSION_NAME = "tc_tui"
_MCP_WRAPPER_MATCH = "bin/mcp-wrapper.py"


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

    # Remove listeners waiting on this session (target listeners)
    target_listeners = pop_listeners(session_id)
    if target_listeners:
        logger.debug(
            "Cleaned up %d listener(s) for terminated target session %s",
            len(target_listeners),
            session_id[:8],
        )

    # Clean up any listeners this session registered (as a caller waiting for other sessions)
    cleanup_caller_listeners(session_id)

    if delete_channel:
        # Delete channel/topic in all adapters (broadcasts to observers)
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
) -> bool:
    """Terminate a session and delete its DB record.

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

    logger.info("Terminating session %s (%s)", session_id[:8], reason)

    if kill_tmux is None:
        kill_tmux = True

    if kill_tmux:
        try:
            killed = await terminal_bridge.kill_session(session.tmux_session_name)
            if killed:
                logger.info("Killed tmux session %s", session.tmux_session_name)
            else:
                logger.warning("Failed to kill tmux session %s", session.tmux_session_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to kill tmux session %s: %s", session.tmux_session_name, exc)

    await cleanup_session_resources(session, adapter_client, delete_channel=delete_channel)

    await db.delete_session(session.session_id)
    logger.info("Deleted session %s from database", session.session_id[:8])
    return True


async def cleanup_stale_session(session_id: str, adapter_client: "AdapterClient") -> bool:
    """Detect stale sessions (tmux missing) without deleting DB state.

    Returns:
        True if tmux is missing, False otherwise.
    """
    session = await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found in database", session_id[:8])
        return False

    # Don't flag sessions that are still being created (race condition guard)
    if session.created_at:
        session_age = (datetime.now(timezone.utc) - session.created_at).total_seconds()
        if session_age < 10.0:
            logger.debug("Session %s is too young (%.1fs), skipping stale check", session_id[:8], session_age)
            return False

    exists = await terminal_bridge.session_exists(session.tmux_session_name)
    if exists:
        return False

    logger.warning(
        "Found stale session %s (tmux %s no longer exists); keeping DB session",
        session_id[:8],
        session.tmux_session_name,
    )
    return True


async def cleanup_all_stale_sessions(adapter_client: "AdapterClient") -> int:
    """Scan for tmux-missing sessions without deleting DB state.

    Returns:
        Number of sessions detected as stale (tmux missing).
    """
    logger.info("Starting stale session scan (tmux-missing detection only)")

    active_sessions = await db.get_active_sessions()
    if not active_sessions:
        logger.debug("No active sessions to check")
        return 0

    logger.info("Checking %d active sessions for staleness", len(active_sessions))

    stale_count = 0
    for session in active_sessions:
        is_stale = await cleanup_stale_session(session.session_id, adapter_client)
        if is_stale:
            stale_count += 1

    if stale_count > 0:
        logger.info("Detected %d stale sessions (tmux missing, DB kept)", stale_count)
    else:
        logger.debug("No stale sessions found")

    return stale_count


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
            if ppid_str != "1":
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
    tmux_sessions = await terminal_bridge.list_tmux_sessions()
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
            success = await terminal_bridge.kill_session(tmux_name)
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
