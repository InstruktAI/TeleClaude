#!/usr/bin/env python3
"""Test tmux bridge responsiveness - core performance without Telegram."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import yaml

from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge
from teleclaude.utils import expand_env_vars

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_responsiveness():
    """Test core tmux bridge responsiveness."""

    # Load config
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)

    # Initialize components
    db_path = os.path.expanduser(config["database"]["path"])
    session_manager = SessionManager(db_path)
    terminal = TerminalBridge()

    await session_manager.initialize()

    logger.info("=" * 70)
    logger.info("TMUX BRIDGE RESPONSIVENESS TEST")
    logger.info("=" * 70)

    # Get active session
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        logger.error("No active sessions found")
        return

    session = sessions[0]
    session_id = session.session_id
    tmux_name = session.tmux_session_name

    logger.info(f"\nSession: {session_id[:8]} - {session.title}")
    logger.info(f"Tmux: {tmux_name}\n")

    # TEST 1: Simple command
    logger.info("=" * 70)
    logger.info("TEST 1: ls -als")
    logger.info("=" * 70)

    start = time.time()
    success = await terminal.send_keys(tmux_name, "ls -als")
    send_time = time.time() - start

    if not success:
        logger.error("Failed to send command")
        return

    logger.info(f"✅ Command sent in {send_time:.3f}s")

    # Wait and capture output
    await asyncio.sleep(2)
    capture_start = time.time()
    output = await terminal.capture_pane(tmux_name)
    capture_time = time.time() - capture_start

    logger.info(f"✅ Output captured in {capture_time:.3f}s ({len(output)} chars)")
    logger.info(f"Total time: {(time.time() - start):.3f}s")
    logger.info(f"\nOutput preview:\n{output[-400:]}\n")

    # TEST 2: Claude Code startup
    logger.info("=" * 70)
    logger.info("TEST 2: Starting Claude Code")
    logger.info("=" * 70)

    start = time.time()
    success = await terminal.send_keys(tmux_name, "claude --dangerously-skip-permissions")
    send_time = time.time() - start

    if not success:
        logger.error("Failed to send command")
        return

    logger.info(f"✅ Command sent in {send_time:.3f}s")

    # Wait for Claude to start
    logger.info("Waiting for Claude Code to start...")
    await asyncio.sleep(4)

    capture_start = time.time()
    output = await terminal.capture_pane(tmux_name)
    capture_time = time.time() - capture_start

    if "Claude Code" in output:
        logger.info(f"✅ Claude Code started! Capture took {capture_time:.3f}s")
    else:
        logger.warning(f"⚠️ Claude Code not detected. Capture took {capture_time:.3f}s")

    logger.info(f"Total time: {(time.time() - start):.3f}s")
    logger.info(f"\nOutput preview:\n{output[-500:]}\n")

    # TEST 3: Message to Claude
    logger.info("=" * 70)
    logger.info("TEST 3: Sending message to Claude")
    logger.info("=" * 70)

    start = time.time()
    success = await terminal.send_keys(tmux_name, "what files are in this directory?")
    send_time = time.time() - start

    if not success:
        logger.error("Failed to send message")
        return

    logger.info(f"✅ Message sent in {send_time:.3f}s")

    # Poll for output changes
    logger.info("Polling for Claude's response...")
    last_output = output
    polls = 0
    max_polls = 20

    while polls < max_polls:
        await asyncio.sleep(1)
        polls += 1

        current_output = await terminal.capture_pane(tmux_name)

        if current_output != last_output:
            logger.info(f"✅ Output changed after {polls}s")
            logger.info(f"Size: {len(current_output)} chars (+{len(current_output) - len(last_output)})")

            # Show what changed
            if len(current_output) > len(last_output):
                new_content = current_output[len(last_output):]
                logger.info(f"\nNew content:\n{new_content[:300]}")

            last_output = current_output

            # If output seems complete (has prompt), stop
            if any(current_output.strip().endswith(c) for c in ["$", ">", "❯"]):
                logger.info("✅ Shell prompt detected, response complete")
                break

    logger.info(f"\nTotal time: {(time.time() - start):.3f}s")
    logger.info(f"Final output preview:\n{last_output[-600:]}\n")

    # TEST 4: Cancel command
    logger.info("=" * 70)
    logger.info("TEST 4: Sending CTRL+C")
    logger.info("=" * 70)

    start = time.time()
    success = await terminal.send_signal(tmux_name, "SIGINT")
    signal_time = time.time() - start

    if success:
        logger.info(f"✅ SIGINT sent in {signal_time:.3f}s")

        await asyncio.sleep(1)
        output = await terminal.capture_pane(tmux_name)
        logger.info(f"\nOutput after cancel:\n{output[-300:]}")
    else:
        logger.error("Failed to send SIGINT")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("TESTS COMPLETE")
    logger.info("=" * 70)

    await session_manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(test_responsiveness())
    except KeyboardInterrupt:
        logger.info("\n\nTests interrupted")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
