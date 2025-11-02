#!/usr/bin/env python3
"""Test daemon message handling by calling handle_message directly."""

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
from teleclaude.utils import expand_env_vars

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_daemon_flow():
    """Test by finding the running daemon and sending it a message."""

    # Load configuration
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)

    # Connect to the running daemon's database
    db_path = os.path.expanduser(config["database"]["path"])
    session_manager = SessionManager(db_path)
    await session_manager.initialize()

    # Find an active session
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        logger.error("No active sessions found. Create one with /new_session test")
        return

    session = sessions[0]
    logger.info(f"Using session: {session.session_id[:8]} - {session.title}")

    # We can't directly call the daemon's handle_message because we'd need the daemon instance
    # Instead, let's use the REST API to send commands
    import aiohttp

    port = int(os.getenv("PORT", config.get("rest_api", {}).get("port", 6666)))
    base_url = f"http://127.0.0.1:{port}"

    async with aiohttp.ClientSession() as http_session:
        # Test 1: Check health
        logger.info("\n=== TEST 1: Health check ===")
        async with http_session.get(f"{base_url}/health") as resp:
            health = await resp.json()
            logger.info(f"Health: {health}")

        # Test 2: Send a simple command via the daemon
        # We'll send to the actual Telegram bot, which will trigger the full flow
        logger.info("\n=== TEST 2: Sending message via Telegram ===")
        logger.info("You need to manually send a message via Telegram to test the full flow")
        logger.info(f"Session topic ID: {session.adapter_metadata.get('channel_id')}")
        logger.info("Go to Telegram and send: ls -als")
        logger.info("Waiting 10 seconds for you to send the message...")
        await asyncio.sleep(10)

        # Check the output file that the daemon should create
        output_file = Path("logs/session_output") / f"{session.session_id[:8]}.txt"
        if output_file.exists():
            content = output_file.read_text()
            logger.info(f"\n=== Output file exists! ===")
            logger.info(f"Size: {len(content)} chars")
            logger.info(f"Last 500 chars:\n{content[-500:]}")
        else:
            logger.warning("No output file found - daemon may not have polled yet")

    await session_manager.close()
    logger.info("\n=== Tests complete ===")


if __name__ == "__main__":
    asyncio.run(test_daemon_flow())
