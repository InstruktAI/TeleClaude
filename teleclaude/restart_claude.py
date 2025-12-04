#!/usr/bin/env python3
"""Restart Claude Code in its TeleClaude tmux session.

For TeleClaude sessions:
- Reads Claude session ID from database (updated by SessionStart hook)
- Sends CTRL+C and restart command via tmux

NOTE: Auto-restart only works for TeleClaude tmux sessions.
For local terminals, user must manually restart Claude after daemon restart
(MCP connection cannot be restored programmatically in local terminals).

Uses the db module properly with async initialization.
"""

import asyncio
import json
import logging
import os
import sys

from teleclaude.config import config
from teleclaude.constants import DEFAULT_CLAUDE_COMMAND
from teleclaude.core import terminal_bridge
from teleclaude.core.db import Db
from teleclaude.core.models import Session
from teleclaude.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def revive_claude_in_session(session: Session) -> bool:
    """Revive Claude Code in a TeleClaude session (for daemon use).

    This function is designed to be called from the daemon with an already-fetched
    Session object. It does not manage database connections.

    Args:
        session: Session object from database

    Returns:
        True if revival command was sent successfully, False otherwise
    """
    logger.info("Reviving Claude in session %s (tmux: %s)", session.session_id[:8], session.tmux_session_name)

    # Extract Claude Code session ID from ux_state (updated by SessionStart hook via MCP)
    claude_session_id = None
    if session.ux_state:
        try:
            ux_state = json.loads(session.ux_state)
            claude_session_id = ux_state.get("claude_session_id")
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning("Failed to parse ux_state for session %s: %s", session.session_id[:8], e)

    # Kill any existing Claude process (send CTRL+C twice like /cancel2x)
    logger.debug("Sending CTRL+C twice to kill any existing Claude Code...")
    success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

    if success:
        await asyncio.sleep(0.2)
        await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
        await asyncio.sleep(1.0)  # Wait for Claude to exit (shorter for bulk revival)

    # Get base command from config with fallback to constant
    base_cmd = config.mcp.claude_command.strip() if config.mcp.claude_command else DEFAULT_CLAUDE_COMMAND

    # Prepend --model flag if session has claude_model set (AI-initiated sessions)
    if session.claude_model:
        base_cmd = f"{base_cmd} --model={session.claude_model}"

    # Build restart command using Claude session ID from database
    if claude_session_id:
        restart_cmd = (
            f"{base_cmd} --resume {claude_session_id} "
            "'you were just restarted - continue if you were in the middle of something or stay silent.'"
        )
        logger.info("Resuming Claude session %s (from database)", claude_session_id[:8])
    else:
        restart_cmd = base_cmd
        logger.info("Starting fresh Claude session (no session ID in database)")

    # Send restart command via tmux
    success, _ = await terminal_bridge.send_keys(
        session_name=session.tmux_session_name,
        text=restart_cmd,
        working_dir=session.working_directory,
        send_enter=True,
    )

    if success:
        logger.info("Claude revival command sent to tmux session %s", session.tmux_session_name)
    else:
        logger.error("Failed to send revival command to tmux session %s", session.tmux_session_name)

    return success


async def restart_teleclaude_session(teleclaude_session_id: str) -> None:
    """Restart Claude in a TeleClaude tmux session via database lookup and tmux commands.

    This is the standalone script entry point - creates its own Db instance.
    For daemon use, call revive_claude_in_session() directly with a Session object.
    """
    db = Db(config.database.path)
    await db.initialize()

    try:
        session = await db.get_session(teleclaude_session_id)

        if not session:
            logger.error("No TeleClaude session found for session ID %s", teleclaude_session_id)
            sys.exit(1)

        logger.info("Found TeleClaude session: %s (tmux: %s)", session.session_id[:8], session.tmux_session_name)

        # Use shared revival logic (but with longer wait time for standalone script)
        # Extract Claude Code session ID from ux_state (updated by SessionStart hook via MCP)
        claude_session_id = None
        if session.ux_state:
            try:
                ux_state = json.loads(session.ux_state)
                claude_session_id = ux_state.get("claude_session_id")
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning("Failed to parse ux_state: %s", e)

        # Kill Claude first (send CTRL+C twice like /cancel2x)
        logger.info("Sending CTRL+C twice to kill Claude Code...")
        success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

        if success:
            await asyncio.sleep(0.2)
            await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
            await asyncio.sleep(3.0)  # Wait for Claude to fully exit

        # Get base command from config with fallback to constant
        base_cmd = config.mcp.claude_command.strip() if config.mcp.claude_command else DEFAULT_CLAUDE_COMMAND

        # Prepend --model flag if session has claude_model set (AI-initiated sessions)
        if session.claude_model:
            base_cmd = f"{base_cmd} --model={session.claude_model}"

        # Build restart command using Claude session ID from database
        if claude_session_id:
            restart_cmd = f"{base_cmd} --resume {claude_session_id} 'you were just restarted - continue if you were in the middle of something or stay silent.'"
            logger.info("Resuming Claude session %s (from database)", claude_session_id[:8])
        else:
            restart_cmd = base_cmd
            logger.info("Starting fresh Claude session (no session ID in database)")

        # Send restart command via tmux
        success, _ = await terminal_bridge.send_keys(
            session_name=session.tmux_session_name,
            text=restart_cmd,
            working_dir=session.working_directory,
            send_enter=True,
        )

        if success:
            logger.info("Claude restart command sent to tmux session %s", session.tmux_session_name)
        else:
            logger.error("Failed to send restart command to tmux session %s", session.tmux_session_name)
            sys.exit(1)

    finally:
        await db.close()


async def main() -> None:
    """Restart Claude Code in its TeleClaude session."""
    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", "INFO")
    log_file = os.getenv("TELECLAUDE_LOG_FILE", "/var/log/teleclaude.log")
    setup_logging(level=log_level, log_file=log_file)

    # Get TeleClaude session ID from environment
    teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
    if not teleclaude_session_id:
        logger.debug("TELECLAUDE_SESSION_ID not set - not a TeleClaude session")
        sys.exit(1)

    logger.info("Restarting TeleClaude session %s", teleclaude_session_id[:8])
    await restart_teleclaude_session(teleclaude_session_id)


if __name__ == "__main__":
    asyncio.run(main())
