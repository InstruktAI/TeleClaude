#!/usr/bin/env python3
"""Monitor daemon responsiveness while you send Telegram messages."""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
import yaml

from teleclaude.core.session_manager import SessionManager
from teleclaude.core.terminal_bridge import TerminalBridge
from teleclaude.utils import expand_env_vars

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def monitor_session(session_id: str, tmux_session_name: str, terminal: TerminalBridge):
    """Monitor a session for changes."""
    logger.info(f"\nMonitoring session: {session_id[:8]}")
    logger.info(f"Tmux: {tmux_session_name}")
    logger.info("=" * 60)
    logger.info("Send messages from Telegram now. Press Ctrl+C to stop.")
    logger.info("=" * 60)

    last_output = ""
    last_output_time = time.time()

    while True:
        try:
            # Capture current output
            output = await terminal.capture_pane(tmux_session_name)

            # Check if output changed
            if output != last_output:
                change_time = time.time()
                elapsed = change_time - last_output_time

                # Calculate diff
                if last_output:
                    # Find what changed
                    old_lines = last_output.split('\n')
                    new_lines = output.split('\n')

                    if len(new_lines) > len(old_lines):
                        new_content = '\n'.join(new_lines[len(old_lines):])
                        logger.info(f"\n{'='*60}")
                        logger.info(f"📝 OUTPUT CHANGED (after {elapsed:.2f}s)")
                        logger.info(f"{'='*60}")
                        logger.info(f"New content ({len(new_content)} chars):")
                        logger.info(f"{new_content[:500]}")
                        if len(new_content) > 500:
                            logger.info(f"... (truncated, total {len(new_content)} chars)")
                    else:
                        logger.info(f"\n📝 OUTPUT CHANGED (after {elapsed:.2f}s)")
                        logger.info(f"Size: {len(output)} chars")
                        logger.info(f"Last 300 chars:\n{output[-300:]}")
                else:
                    logger.info(f"\n📝 INITIAL OUTPUT CAPTURED")
                    logger.info(f"Size: {len(output)} chars")

                last_output = output
                last_output_time = change_time

            # Check daemon log for recent activity
            log_file = Path("/var/log/teleclaude.log")
            if log_file.exists():
                # Get last modified time
                mtime = log_file.stat().st_mtime
                current_time = time.time()

                if current_time - mtime < 2:  # Log updated in last 2 seconds
                    # Read last few lines
                    with open(log_file) as f:
                        lines = f.readlines()
                        recent = lines[-5:]

                    # Filter out DEBUG noise
                    relevant = [l for l in recent if not any(x in l for x in ["DEBUG", "httpcore", "httpx", "ExtBot"])]

                    if relevant:
                        logger.info(f"\n🔍 Recent daemon activity:")
                        for line in relevant:
                            print(f"    {line.rstrip()}")

            await asyncio.sleep(0.5)  # Poll every 0.5 seconds

        except KeyboardInterrupt:
            logger.info("\n\n👋 Monitoring stopped")
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            await asyncio.sleep(1)


async def main():
    """Main entry point."""

    # Load configuration
    base_dir = Path(__file__).parent
    config_path = base_dir / "config.yml"
    env_path = base_dir / ".env"

    load_dotenv(env_path)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = expand_env_vars(config)

    # Connect to database
    db_path = os.path.expanduser(config["database"]["path"])
    session_manager = SessionManager(db_path)
    terminal = TerminalBridge()

    await session_manager.initialize()

    # Find active sessions
    sessions = await session_manager.list_sessions(status="active")

    if not sessions:
        logger.error("No active sessions found")
        logger.info("Create one first with: /new_session test")
        return

    # List sessions
    logger.info("\nActive sessions:")
    for i, s in enumerate(sessions, 1):
        topic_id = s.adapter_metadata.get("channel_id") or s.adapter_metadata.get("topic_id")
        logger.info(f"{i}. {s.session_id[:8]} - {s.title} (topic: {topic_id})")

    # Use first session
    session = sessions[0]

    # Monitor it
    await monitor_session(session.session_id, session.tmux_session_name, terminal)

    await session_manager.close()


if __name__ == "__main__":
    asyncio.run(main())
