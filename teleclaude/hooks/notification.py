#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv",
#     "pyyaml",
#     "aiosqlite",
#     "python-telegram-bot",
#     "redis",
# ]
# ///
"""Claude Code notification hook for TeleClaude.

Sends attention-getting messages to TeleClaude sessions when Claude needs user input.
Triggered by Claude Code Notification event (mid-session).

Usage:
    echo '{"session_id": "abc123", "message": "..."}' | ./notification.py --notify

Expected stdin JSON format:
    {
        "session_id": "abc123",
        "message": "notification type"
    }

Exit codes:
    0: Success
    1: Error (logged to stderr)
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

# Setup minimal logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def log_debug(message: str) -> None:
    """Log debug messages to file (disabled by default)."""
    return  # Disabled for performance

    debug_log = Path.home() / ".claude" / "hooks" / "logs" / "notification_debug.log"
    debug_log.parent.mkdir(parents=True, exist_ok=True)

    from datetime import datetime

    timestamp = datetime.now().isoformat()

    with open(debug_log, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


async def bootstrap_teleclaude():  # type: ignore
    """Bootstrap TeleClaude components (config, db, adapter_client).

    Returns:
        Tuple of (config, db, adapter_client)

    Raises:
        RuntimeError: If bootstrap fails
    """
    try:
        # Import TeleClaude modules (after sys.path setup)
        from teleclaude.config import config
        from teleclaude.core.adapter_client import AdapterClient
        from teleclaude.core.db import db

        # Initialize database
        await db.initialize()
        logger.debug("Database initialized")

        # Create AdapterClient and load adapters
        adapter_client = AdapterClient()
        adapter_client._load_adapters()  # pylint: disable=protected-access
        logger.debug("Loaded %d adapter(s)", len(adapter_client.adapters))

        # Wire DB to AdapterClient for UI updates
        db.set_client(adapter_client)

        # Start adapters (required for sending messages)
        await adapter_client.start()
        logger.debug("Adapters started")

        return config, db, adapter_client

    except Exception as e:
        raise RuntimeError(f"Failed to bootstrap TeleClaude: {e}") from e


async def send_notification(session_id: str) -> None:
    """Send notification message to TeleClaude session.

    Args:
        session_id: TeleClaude session ID

    Raises:
        RuntimeError: If notification fails
    """
    # Bootstrap TeleClaude components
    config, db, adapter_client = await bootstrap_teleclaude()

    try:
        # Verify session exists
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return

        # Get engineer name for personalization
        engineer_name = os.getenv("ENGINEER_NAME", "").strip()

        # Create notification message (30% chance to include name)
        if engineer_name and random.random() < 0.3:
            message = f"{engineer_name}, your agent needs your input"
        else:
            message = "Your agent needs your input"

        log_debug(f"Sending notification: {message}")

        # Send message via AdapterClient (broadcasts to all UI adapters)
        message_id = await adapter_client.send_message(session_id, message)
        log_debug(f"Sent notification (message_id={message_id})")

        # Set notification flag in UX state (clears inactivity timer)
        await db.set_notification_flag(session_id, True)
        log_debug(f"Set notification_sent flag for session {session_id[:8]}")

    except Exception as e:
        raise RuntimeError(f"Failed to send notification: {e}") from e

    finally:
        # Stop adapters gracefully
        for adapter_name, adapter in adapter_client.adapters.items():
            try:
                await adapter.stop()
            except Exception as e:
                logger.warning("Failed to stop %s adapter: %s", adapter_name, e)


async def main_async(args: argparse.Namespace, input_data: dict[str, object]) -> None:
    """Async main logic.

    Args:
        args: Parsed command line arguments
        input_data: JSON input from stdin
    """
    log_debug("=== Notification hook started ===")
    log_debug(f"Args: notify={args.notify}")
    log_debug(f"Input data: {json.dumps(input_data)}")

    # Extract session_id
    session_id = str(input_data.get("session_id", ""))
    if not session_id:
        logger.error("Missing session_id in input JSON")
        return

    # Only send if --notify flag is set AND not the generic message
    # Skip generic "Claude is waiting for your input" (too noisy)
    if args.notify and input_data.get("message") != "Claude is waiting for your input":
        log_debug("Sending notification")
        await send_notification(session_id)
    else:
        log_debug("Skipping notification (--notify flag not set or generic message)")

    log_debug("Hook completed successfully")


def main() -> None:
    """Main entry point for notification hook."""
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description="TeleClaude notification hook")
        parser.add_argument("--notify", action="store_true", help="Enable notifications")
        args = parser.parse_args()

        # Read JSON input from stdin
        input_data = json.loads(sys.stdin.read())

        # Run async logic
        asyncio.run(main_async(args, input_data))

        sys.exit(0)

    except json.JSONDecodeError as e:
        logger.error("Invalid JSON input: %s", e)
        sys.exit(1)

    except Exception as e:
        logger.error("Unexpected error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    # Load environment variables
    load_dotenv()

    # Add TeleClaude to sys.path (hook runs from project root)
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Run main
    main()
