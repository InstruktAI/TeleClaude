#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "instruktai-python-logger",
#   "httpx>=0.28.0",
#   "websockets>=12.0",
#   "pydantic>=2.0",
#   "python-dotenv>=1.0.0",
#   "pyyaml>=6.0.3",
#   "sqlalchemy>=2.0.0",
#   "sqlmodel>=0.0.16",
#   "aiosqlite>=0.21.0",
#   "greenlet>=3.3.0",
# ]
# ///
"""Replay channel-closure for recently closed sessions via daemon API."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if os.environ.get("TELECLAUDE_DISABLE_UV_SCRIPT_ENV") is None:
    SCRIPT_DIR = Path(__file__).resolve().parent
    PROJECT_ROOT = SCRIPT_DIR.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config
from teleclaude.core.db import db

logger = get_logger(__name__)


async def _replay_closed_sessions(*, hours: float, dry_run: bool) -> int:
    if hours <= 0:
        raise ValueError("--hours must be > 0")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sessions = await db.list_sessions(
        include_closed=True,
        include_initializing=True,
        include_headless=True,
    )

    candidates = [
        (session.session_id, session.computer_name)
        for session in sessions
        if session.closed_at and session.closed_at >= cutoff
    ]

    if not candidates:
        logger.info("No closed sessions found in the last %.1f hours", hours)
        return 0

    logger.info("Found %d closed sessions in last %.1f hours", len(candidates), hours)

    if dry_run:
        logger.info("Dry-run; no API calls made")
        return len(candidates)

    local_computer = config.computer.name
    client = TelecAPIClient()
    await client.connect()
    try:
        completed = 0
        failed = 0
        for session_id, computer_name in candidates:
            if computer_name and computer_name != local_computer:
                logger.warning(
                    "Skipping session %s (owned by %s, this host is %s)",
                    session_id[:8],
                    computer_name,
                    local_computer,
                )
                continue

            target_computer = computer_name or local_computer
            try:
                if await client.end_session(session_id, target_computer):
                    completed += 1
                    logger.info("Requested replay for session %s", session_id[:8])
                else:
                    failed += 1
                    logger.warning("Failed replay for session %s", session_id[:8])
            except Exception:
                failed += 1
                logger.exception("Failed to request replay for session %s", session_id[:8])

        logger.info(
            "Replay requests complete: success=%d fail=%d",
            completed,
            failed,
        )
        return completed
    finally:
        await client.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay session_closed events for recently closed sessions",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=12.0,
        help="Lookback window in hours for closed sessions (default: 12)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List candidate sessions only; do not send requests",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    configure_logging("teleclaude")

    try:
        _ = config.computer.name
    except Exception as exc:
        logger.error("Config not ready: %s", exc)
        return 1

    await db.initialize()
    try:
        count = await _replay_closed_sessions(hours=args.hours, dry_run=args.dry_run)
        logger.info("Done. Replayed %d session(s)", count)
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
