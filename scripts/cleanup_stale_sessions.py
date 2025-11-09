#!/usr/bin/env python3
"""Periodic cleanup script for stale sessions.

This script is run by cron/systemd timer every 5-10 minutes to find and clean up
sessions that exist in the database but have no corresponding tmux session.

Exit codes:
    0: Success (cleaned up N sessions or found none)
    1: Error during execution
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from teleclaude.config import config
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db
from teleclaude.core.session_cleanup import cleanup_all_stale_sessions
from teleclaude.logging_config import setup_logging


async def main() -> int:
    """Run periodic stale session cleanup."""
    # Setup logging (logs to file)
    setup_logging(
        level="INFO",
        log_file="/var/log/teleclaude.log",
    )

    logger = logging.getLogger(__name__)
    logger.info("=== Periodic Stale Session Cleanup Started ===")

    try:
        # Initialize database
        await db.initialize()

        # Initialize AdapterClient (needed for delete_channel)
        client = AdapterClient()
        await client.initialize()

        # Run cleanup
        cleaned_count = await cleanup_all_stale_sessions(client)

        logger.info(
            "=== Periodic Cleanup Complete: %d stale session(s) cleaned ===",
            cleaned_count,
        )

        # Cleanup
        await client.cleanup()
        await db.close()

        return 0

    except Exception as e:
        logger.error("Periodic cleanup failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
