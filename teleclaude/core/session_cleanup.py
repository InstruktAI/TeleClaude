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
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.session_listeners import cleanup_caller_listeners
from teleclaude.core.session_utils import OUTPUT_DIR, get_session_output_dir

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.models import Session

logger = get_logger(__name__)

# TeleClaude tmux session prefix - used to identify owned sessions
TMUX_SESSION_PREFIX = "tc_"
_MCP_WRAPPER_MATCH = "bin/mcp-wrapper.py"


async def cleanup_session_resources(session: "Session", adapter_client: "AdapterClient") -> None:
    """Clean up session resources: channels, listeners, pending deletions, and workspace directory.

    Shared cleanup logic used by both explicit exit and stale session cleanup.
    Does NOT modify DB state - caller handles that.

    Args:
        session: Session object (must be fetched before DB deletion)
        adapter_client: AdapterClient for deleting channels
    """
    session_id = session.session_id

    # Clean up any listeners this session registered (as a caller waiting for other sessions)
    cleanup_caller_listeners(session_id)

    # Clear pending deletions - messages that would have been deleted on next user input
    # These are no longer relevant since the session is ending
    await db.clear_pending_deletions(session_id)
    await db.update_ux_state(session_id, pending_feedback_deletions=[])

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


async def cleanup_stale_session(session_id: str, adapter_client: "AdapterClient") -> bool:
    """Clean up a single stale session.

    Args:
        session_id: Session identifier
        adapter_client: AdapterClient for deleting channels

    Returns:
        True if session was stale and cleaned up, False if session is healthy
    """
    session = await db.get_session(session_id)
    if not session:
        logger.debug("Session %s not found in database", session_id[:8])
        return False

    if session.closed:
        logger.debug("Session %s already marked as closed", session_id[:8])
        return False

    # Check if tmux session exists
    exists = await terminal_bridge.session_exists(session.tmux_session_name)
    if exists:
        # Session is healthy
        return False

    # Session is stale - tmux gone but DB says active
    logger.warning(
        "Found stale session %s (tmux %s no longer exists), cleaning up",
        session_id[:8],
        session.tmux_session_name,
    )

    # Mark as closed in database
    await db.update_session(session_id, closed=True)

    # Clean up channels and workspace (shared logic)
    await cleanup_session_resources(session, adapter_client)

    logger.info("Cleaned up stale session %s", session_id[:8])
    return True


async def cleanup_all_stale_sessions(adapter_client: "AdapterClient") -> int:
    """Find and clean up all stale sessions.

    Args:
        adapter_client: AdapterClient for deleting channels

    Returns:
        Number of stale sessions cleaned up
    """
    logger.info("Starting stale session cleanup scan")

    # Get all active sessions
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

    # Filter to only TeleClaude-owned sessions
    tc_sessions = [s for s in tmux_sessions if s.startswith(TMUX_SESSION_PREFIX)]
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
    - Sessions are closed but workspace cleanup didn't happen

    Returns:
        Number of orphan workspace directories removed
    """
    if not OUTPUT_DIR.exists():
        logger.debug("Workspace directory does not exist")
        return 0

    # Get all active session IDs from DB
    all_sessions = await db.get_all_sessions()
    known_session_ids = {s.session_id for s in all_sessions if not s.closed}

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
