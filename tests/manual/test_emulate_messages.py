#!/usr/bin/env python3
"""Test script to emulate Telegram messages and test bridge responsiveness."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import yaml

from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.utils import expand_env_vars

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_message_flow():
    """Test the message flow by emulating Telegram messages."""

    # Load configuration
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)

    # Get daemon instance (don't start it, just use its components)
    # We'll access the running daemon's database
    from teleclaude.core.session_manager import SessionManager
    from teleclaude.core.terminal_bridge import TerminalBridge

    db_path = os.path.expanduser(config["database"]["path"])
    session_manager = SessionManager(db_path)
    terminal = TerminalBridge()

    await session_manager.initialize()

    # Find an active session
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        logger.error("No active sessions found. Create one first with /new_session test")
        return

    session = sessions[0]
    logger.info(f"Using session: {session.session_id[:8]} - {session.title}")
    logger.info(f"Tmux session: {session.tmux_session_name}")

    # Test 1: Send simple ls command
    logger.info("\n=== TEST 1: Sending 'ls -als' ===")
    start_time = time.time()

    success = await terminal.send_keys(session.tmux_session_name, "ls -als")

    if not success:
        logger.error("Failed to send command to tmux")
        return

    # Wait for output
    await asyncio.sleep(2)

    # Capture output
    output = await terminal.capture_pane(session.tmux_session_name)
    elapsed = time.time() - start_time

    logger.info(f"Command sent in {elapsed:.2f}s")
    logger.info(f"Output length: {len(output)} chars")
    logger.info(f"First 500 chars of output:\n{output[:500]}")

    # Test 2: Send /claude command (via daemon handle_command)
    logger.info("\n=== TEST 2: Sending '/claude' command ===")
    start_time = time.time()

    # We can't easily call handle_command without starting the full daemon
    # So let's just send the command directly via terminal
    success = await terminal.send_keys(
        session.tmux_session_name,
        "claude --dangerously-skip-permissions"
    )

    if not success:
        logger.error("Failed to send claude command")
        return

    # Wait longer for Claude Code to start
    await asyncio.sleep(3)

    output = await terminal.capture_pane(session.tmux_session_name)
    elapsed = time.time() - start_time

    logger.info(f"Claude command sent in {elapsed:.2f}s")
    logger.info(f"Output length: {len(output)} chars")
    logger.info(f"Last 500 chars of output:\n{output[-500:]}")

    # Check if Claude Code started
    if "Claude Code" in output:
        logger.info("✅ Claude Code started successfully")

        # Test 3: Send a message to Claude
        logger.info("\n=== TEST 3: Sending message to Claude ===")
        start_time = time.time()

        success = await terminal.send_keys(session.tmux_session_name, "how are you doing?")

        if not success:
            logger.error("Failed to send message to Claude")
            return

        # Wait for Claude to respond
        logger.info("Waiting for Claude to respond...")
        await asyncio.sleep(5)

        output = await terminal.capture_pane(session.tmux_session_name)
        elapsed = time.time() - start_time

        logger.info(f"Message sent and response received in {elapsed:.2f}s")
        logger.info(f"Output length: {len(output)} chars")
        logger.info(f"Last 1000 chars of output:\n{output[-1000:]}")
    else:
        logger.warning("⚠️ Claude Code may not have started properly")

    # Clean up
    await session_manager.close()
    logger.info("\n=== Tests complete ===")


if __name__ == "__main__":
    asyncio.run(test_message_flow())
