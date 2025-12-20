#!/usr/bin/env python3
"""Restart Agent in its TeleClaude tmux session.

For TeleClaude sessions:
- Reads native session ID from database (updated by SessionStart hook)
- Sends CTRL+C and restart command via tmux

NOTE: Auto-restart only works for TeleClaude tmux sessions.
For local terminals, user must manually restart Agent after daemon restart.

Uses the db module properly with async initialization.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from teleclaude.config import config
from teleclaude.core import terminal_bridge
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def restart_agent_in_session(session: Session, agent_name: Optional[str] = None) -> bool:
    """Restart Agent in a TeleClaude session.

    Args:
        session: Session object from database
        agent_name: Name of agent to restart (optional, derived from session if missing)

    Returns:
        True if restart command was sent successfully, False otherwise
    """
    logger.info(
        "Restarting agent in session %s (tmux: %s)",
        session.session_id[:8],
        session.tmux_session_name,
    )

    # Extract native session ID and active agent from ux_state
    ux_state = await db.get_ux_state(session.session_id)
    native_session_id: Optional[str] = ux_state.native_session_id if ux_state else None
    active_agent: Optional[str] = ux_state.active_agent if ux_state else None
    thinking_mode: str = ux_state.thinking_mode or "slow" if ux_state else "slow"

    # Determine agent name: argument > ux_state
    target_agent = agent_name or active_agent
    if not target_agent:
        logger.error(
            "Cannot determine active agent for session %s. Please specify agent_name or ensure it's saved in UX state.",
            session.session_id[:8],
        )
        return False
    logger.info("Target agent: %s", target_agent)

    # Kill any existing process (send CTRL+C twice)
    logger.debug("Sending CTRL+C twice to kill any existing process...")
    success = await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")

    if success:
        await asyncio.sleep(0.2)
        await terminal_bridge.send_signal(session.tmux_session_name, "SIGINT")
        await asyncio.sleep(1.0)  # Wait for process to exit

    # Get agent command from config
    agent_config = config.agents.get(target_agent)
    if not agent_config:
        logger.error("Unknown agent: %s", target_agent)
        return False

    if native_session_id:
        logger.info(
            "Resuming %s session %s (from database)",
            target_agent,
            native_session_id[:8],
        )
    else:
        raise RuntimeError("No native session ID found for resuming session")

    restart_cmd = get_agent_command(
        agent=target_agent,
        thinking_mode=thinking_mode,
        exec=False,
        native_session_id=native_session_id,
    )

    if native_session_id:
        logger.info(
            "Resuming %s session %s (from database)",
            target_agent,
            native_session_id[:8],
        )
    else:
        logger.info("Starting fresh %s session (no session ID in database)", target_agent)

    # Send restart command via tmux
    success, _ = await terminal_bridge.send_keys(
        session_name=session.tmux_session_name,
        text=restart_cmd,
        session_id=session.session_id,
        working_dir=session.working_directory,
        send_enter=True,
    )

    if success:
        logger.info("Restart command sent to tmux session %s", session.tmux_session_name)
    else:
        logger.error(
            "Failed to send restart command to tmux session %s",
            session.tmux_session_name,
        )

    return success


async def main() -> None:
    """Restart Agent in its TeleClaude session (standalone script)."""
    # Setup logging from environment variables
    log_level = os.getenv("TELECLAUDE_LOG_LEVEL", "INFO")
    setup_logging(level=log_level)

    # Get TeleClaude session ID from environment
    teleclaude_session_id = os.getenv("TELECLAUDE_SESSION_ID")
    if not teleclaude_session_id:
        logger.debug("TELECLAUDE_SESSION_ID not set - not a TeleClaude session")
        sys.exit(1)

    await db.initialize()

    try:
        session = await db.get_session(teleclaude_session_id)
        if not session:
            logger.error("No TeleClaude session found for session ID %s", teleclaude_session_id)
            sys.exit(1)

        logger.info(
            "Restarting active agent in TeleClaude session %s",
            teleclaude_session_id[:8],
        )

        # Don't pass agent_name - let it derive from session
        success = await restart_agent_in_session(session)
        if not success:
            logger.error(
                "Failed to restart agent for session %s. See logs for details.",
                teleclaude_session_id[:8],
            )
            sys.exit(1)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
