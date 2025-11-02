#!/usr/bin/env python3
"""Direct emulation of Telegram messages - call daemon methods directly."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

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


async def test_full_flow():
    """Test full message flow by directly calling daemon methods."""

    # Load config
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    # Create daemon instance (don't start it, we'll use its methods directly)
    daemon = TeleClaudeDaemon(str(config_path), str(env_path))

    # Initialize database
    await daemon.session_manager.initialize()

    logger.info("=" * 70)
    logger.info("TESTING TELECLAUDE RESPONSIVENESS - DIRECT METHOD CALLS")
    logger.info("=" * 70)

    # Get existing active session or create new one
    sessions = await daemon.session_manager.list_sessions(status="active")

    if not sessions:
        logger.info("\n=== TEST 0: Creating new session ===")
        start = time.time()

        context = {
            "adapter_type": "telegram",
            "user_id": 12345,
            "chat_id": -1001234567890,
            "message_thread_id": None,
        }

        await daemon.handle_command("new-session", ["TEST"], context)

        elapsed = time.time() - start
        logger.info(f"✅ Session created in {elapsed:.2f}s")

        # Get the session we just created
        sessions = await daemon.session_manager.list_sessions(status="active")

    session = sessions[0]
    session_id = session.session_id
    tmux_name = session.tmux_session_name

    logger.info(f"\nUsing session: {session_id[:8]} - {session.title}")
    logger.info(f"Tmux: {tmux_name}")

    # TEST 1: Simple command (ls -als)
    logger.info("\n" + "=" * 70)
    logger.info("TEST 1: Sending 'ls -als'")
    logger.info("=" * 70)

    start = time.time()

    context = {
        "adapter_type": "telegram",
        "user_id": 12345,
        "message_id": 1001,
    }

    # This will:
    # 1. Send command to tmux
    # 2. Poll for output
    # 3. Send messages to Telegram (which will fail since no real Telegram, but we can check timing)
    await daemon.handle_message(session_id, "ls -als", context)

    elapsed = time.time() - start
    logger.info(f"\n✅ Command processed in {elapsed:.2f}s")

    # Check what output is in tmux
    output = await daemon.terminal.capture_pane(tmux_name)
    logger.info(f"Output size: {len(output)} chars")
    logger.info(f"Last 400 chars:\n{output[-400:]}")

    # Wait a bit before next test
    await asyncio.sleep(1)

    # TEST 2: /claude command
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Starting Claude Code")
    logger.info("=" * 70)

    start = time.time()

    context = {
        "adapter_type": "telegram",
        "session_id": session_id,
        "user_id": 12345,
    }

    await daemon.handle_command("claude", [], context)

    elapsed = time.time() - start
    logger.info(f"\n✅ Claude command processed in {elapsed:.2f}s")

    # Check output
    output = await daemon.terminal.capture_pane(tmux_name)
    logger.info(f"Output size: {len(output)} chars")

    if "Claude Code" in output:
        logger.info("✅ Claude Code started successfully")
    else:
        logger.warning("⚠️ Claude Code may not have started")

    logger.info(f"Last 400 chars:\n{output[-400:]}")

    # Wait for Claude to fully load
    await asyncio.sleep(3)

    # TEST 3: Send message to Claude
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Sending message to Claude: 'how are you doing?'")
    logger.info("=" * 70)

    start = time.time()

    context = {
        "adapter_type": "telegram",
        "user_id": 12345,
        "message_id": 1003,
    }

    await daemon.handle_message(session_id, "how are you doing?", context)

    elapsed = time.time() - start
    logger.info(f"\n✅ Message processed in {elapsed:.2f}s")

    # Check response
    output = await daemon.terminal.capture_pane(tmux_name)
    logger.info(f"Output size: {len(output)} chars")
    logger.info(f"Last 600 chars:\n{output[-600:]}")

    # TEST 4: Check output file
    logger.info("\n" + "=" * 70)
    logger.info("TEST 4: Checking session output file")
    logger.info("=" * 70)

    output_file = Path("logs/session_output") / f"{session_id[:8]}.txt"
    if output_file.exists():
        content = output_file.read_text()
        logger.info(f"✅ Output file exists: {len(content)} chars")
        logger.info(f"Last 500 chars:\n{content[-500:]}")
    else:
        logger.warning("⚠️ No output file found")

    # TEST 5: /cancel command
    logger.info("\n" + "=" * 70)
    logger.info("TEST 5: Testing /cancel command")
    logger.info("=" * 70)

    start = time.time()

    context = {
        "adapter_type": "telegram",
        "session_id": session_id,
        "user_id": 12345,
    }

    await daemon.handle_command("cancel", [], context)

    elapsed = time.time() - start
    logger.info(f"✅ Cancel processed in {elapsed:.2f}s")

    # Final output
    output = await daemon.terminal.capture_pane(tmux_name)
    logger.info(f"Output size: {len(output)} chars")
    logger.info(f"Last 300 chars:\n{output[-300:]}")

    # Cleanup
    await daemon.session_manager.close()

    logger.info("\n" + "=" * 70)
    logger.info("ALL TESTS COMPLETE")
    logger.info("=" * 70)
    logger.info("\nNote: Telegram send/edit calls will show errors since we're not")
    logger.info("running with a real Telegram connection, but timing is accurate.")


if __name__ == "__main__":
    try:
        asyncio.run(test_full_flow())
    except KeyboardInterrupt:
        logger.info("\n\nTests interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
