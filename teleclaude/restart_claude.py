#!/usr/bin/env python3
"""Restart Claude Code in its TeleClaude session.

This script can be called from anywhere. It checks for TELECLAUDE_SESSION_ID
environment variable and exits gracefully if not set (e.g., when run from
a regular terminal). When run from within a TeleClaude tmux session where
Claude is running, it queries the database and sends a command to restart claude.
(It is not possible for Claude Code to restart itself in a regular terminal session)

Uses the db module properly with async initialization.
"""

import asyncio
import logging
import os
import sys

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.db import Db
from teleclaude.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    """Find Claude's TeleClaude session and restart it."""

    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", "INFO")
    log_file = os.getenv("TELECLAUDE_LOG_FILE", "/var/log/teleclaude.log")
    setup_logging(level=log_level, log_file=log_file)

    # Get TeleClaude session ID from environment (set by TeleClaude)
    teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
    if not teleclaude_session_id:
        logger.debug("TELECLAUDE_SESSION_ID not set - not running in TeleClaude session")
        sys.exit(1)

    # Initialize database connection
    db = Db(config.database.path)
    await db.initialize()

    try:
        # Get session by TeleClaude session ID (primary key)
        session = await db.get_session(teleclaude_session_id)

        if not session:
            logger.error("No TeleClaude session found for session ID %s", teleclaude_session_id)
            sys.exit(1)

        logger.info("Found TeleClaude session: %s (tmux: %s)", session.session_id[:8], session.tmux_session_name)

        # Kill Claude first (send CTRL+C twice like /cancel2x)
        logger.info("Sending CTRL+C twice to kill Claude Code...")
        success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

        if success:
            await asyncio.sleep(0.2)
            await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
            await asyncio.sleep(1.0)  # Wait for Claude to fully exit

        # Send restart command using terminal_bridge (proper codebase pattern)
        restart_cmd = f"claude --dangerously-skip-permissions --session-id {session.session_id} 'you were just restarted - continue if you were in the middle of something or stay silent.'"

        # Use terminal_bridge.send_keys() which handles both text and Enter
        success = await terminal_bridge.send_keys(
            session_name=session.tmux_session_name,
            text=restart_cmd,
            shell=config.computer.default_shell,
            working_dir=session.working_directory,
            append_exit_marker=True,
            send_enter=True,
        )

        if success:
            logger.info("Claude restart command sent to tmux session %s", session.tmux_session_name)
        else:
            logger.error("Failed to send restart command to tmux session %s", session.tmux_session_name)
            sys.exit(1)

    except Exception as e:
        logger.error("%s: %s", type(e).__name__, e)
        sys.exit(1)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
