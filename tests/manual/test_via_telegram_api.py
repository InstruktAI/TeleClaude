#!/usr/bin/env python3
"""Test responsiveness by sending messages via Telegram Bot API."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import aiohttp
import yaml
from dotenv import load_dotenv

from teleclaude.core.session_manager import SessionManager
from teleclaude.utils import expand_env_vars

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def send_telegram_message(bot_token: str, chat_id: int, thread_id: int, text: str) -> dict:
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "message_thread_id": thread_id,
        "text": text,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()


async def test_telegram_flow():
    """Test the full message flow via Telegram Bot API."""

    # Load configuration
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)

    # Get Telegram credentials
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    supergroup_id = int(os.getenv("TELEGRAM_SUPERGROUP_ID"))

    if not bot_token or not supergroup_id:
        logger.error("Missing Telegram credentials in .env")
        return

    # Connect to database
    db_path = os.path.expanduser(config["database"]["path"])
    session_manager = SessionManager(db_path)
    await session_manager.initialize()

    # Find an active session
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        logger.error("No active sessions found. Create one with /new_session test")
        return

    session = sessions[0]
    topic_id = session.adapter_metadata.get("channel_id") or session.adapter_metadata.get("topic_id")

    if not topic_id:
        logger.error(f"Session {session.session_id[:8]} has no topic_id")
        return

    logger.info(f"Using session: {session.session_id[:8]} - {session.title}")
    logger.info(f"Topic ID: {topic_id}")

    # Test 1: Send simple ls command
    logger.info("\n=== TEST 1: Sending 'ls -als' via Telegram ===")
    start_time = time.time()

    result = await send_telegram_message(bot_token, supergroup_id, int(topic_id), "ls -als")
    send_elapsed = time.time() - start_time

    if result.get("ok"):
        logger.info(f"✅ Message sent in {send_elapsed:.2f}s")
        logger.info(f"Message ID: {result['result']['message_id']}")
    else:
        logger.error(f"❌ Failed to send message: {result}")
        return

    # Wait for daemon to process and poll
    logger.info("Waiting 5 seconds for daemon to poll output...")
    await asyncio.sleep(5)

    total_elapsed = time.time() - start_time
    logger.info(f"Total time: {total_elapsed:.2f}s")

    # Check daemon logs
    logger.info("\n=== Checking daemon activity ===")
    log_file = Path("/var/log/teleclaude.log")
    if log_file.exists():
        # Get last 30 lines
        with open(log_file) as f:
            lines = f.readlines()
            recent_logs = lines[-30:]

        # Filter for relevant logs (ignore DEBUG)
        relevant = [
            l for l in recent_logs if any(x in l for x in ["INFO", "ERROR", "Message", "poll", session.session_id[:8]])
        ]

        if relevant:
            logger.info(f"Recent daemon logs ({len(relevant)} lines):")
            for line in relevant[-10:]:
                print(line.rstrip())
        else:
            logger.warning("No relevant daemon logs found")
    else:
        logger.warning("Log file not found")

    # Test 2: Send message to Claude
    logger.info("\n=== TEST 2: Starting Claude and sending message ===")

    # Send /claude command
    result = await send_telegram_message(bot_token, supergroup_id, int(topic_id), "/claude")
    if result.get("ok"):
        logger.info("✅ /claude command sent")
    else:
        logger.error(f"❌ Failed: {result}")
        return

    # Wait for Claude to start
    await asyncio.sleep(5)

    # Send message to Claude
    start_time = time.time()
    result = await send_telegram_message(bot_token, supergroup_id, int(topic_id), "hey claude, how are you?")

    if result.get("ok"):
        logger.info("✅ Message to Claude sent")
    else:
        logger.error(f"❌ Failed: {result}")
        return

    # Wait for response
    logger.info("Waiting 10 seconds for Claude to respond...")
    await asyncio.sleep(10)

    total_elapsed = time.time() - start_time
    logger.info(f"Total time: {total_elapsed:.2f}s")

    # Check output file
    output_file = Path("logs/session_output") / f"{session.session_id[:8]}.txt"
    if output_file.exists():
        content = output_file.read_text()
        logger.info("\n=== Output file ===")
        logger.info(f"Size: {len(content)} chars")
        logger.info(f"Last 800 chars:\n{content[-800:]}")
    else:
        logger.warning("No output file found")

    await session_manager.close()
    logger.info("\n=== Tests complete ===")


if __name__ == "__main__":
    asyncio.run(test_telegram_flow())
