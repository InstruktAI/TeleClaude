"""Replay channel-closure for recently closed sessions via daemon API."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from instrukt_ai_logging import (  # noqa: E402 -- imports must use this checkout from any cwd
    configure_logging,
    get_logger,
)

from teleclaude.api_models import SessionDTO  # noqa: E402 -- imports must use this checkout from any cwd
from teleclaude.cli.api_client import (  # noqa: E402 -- imports must use this checkout from any cwd
    APIError,
    TelecAPIClient,
)
from teleclaude.config.machine import config  # noqa: E402 -- imports must use this checkout from any cwd

logger = get_logger(__name__)

_INVALID_HOURS_ERROR = "--hours must be > 0"
_NO_CLOSED_SESSIONS = "No closed sessions found in the last %.1f hours"
_CLOSED_SESSIONS_FOUND = "Found %d closed sessions in last %.1f hours"
_DRY_RUN_MESSAGE = "Dry-run; read-only API listing completed, no replay requests made"
_REMOTE_SESSION_SKIP = "Skipping session %s (owned by %s, this host is %s)"
_SESSION_REPLAY_REQUESTED = "Requested replay for session %s"
_SESSION_REPLAY_REFUSED = "Failed replay for session %s"
_SESSION_REPLAY_API_ERROR = "Failed to request replay for session %s: %s"
_REPLAY_SUMMARY = "Replay requests complete: success=%d fail=%d"
_CONFIG_NOT_READY = "Config not ready: %s"
_DONE_MESSAGE = "Done. Replayed %d session(s)"


async def _replay_closed_sessions(*, hours: float, dry_run: bool) -> int:
    if hours <= 0:
        raise ValueError(_INVALID_HOURS_ERROR)

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    local_computer = config.computer.name
    client = TelecAPIClient()
    await client.connect()
    try:
        sessions = await client.list_sessions(include_closed=True, all_sessions=True)
        candidates: list[SessionDTO] = [
            session for session in sessions if session.closed_at and datetime.fromisoformat(session.closed_at) >= cutoff
        ]

        if not candidates:
            logger.info(_NO_CLOSED_SESSIONS, hours)
            return 0

        logger.info(_CLOSED_SESSIONS_FOUND, len(candidates), hours)

        if dry_run:
            logger.info(_DRY_RUN_MESSAGE)
            return len(candidates)

        completed = 0
        failed = 0
        for session in candidates:
            if session.computer and session.computer != local_computer:
                logger.warning(
                    _REMOTE_SESSION_SKIP,
                    session.session_id,
                    session.computer,
                    local_computer,
                )
                continue

            target_computer = session.computer or local_computer
            try:
                if await client.end_session(session.session_id, target_computer):
                    completed += 1
                    logger.info(_SESSION_REPLAY_REQUESTED, session.session_id)
                else:
                    failed += 1
                    logger.warning(_SESSION_REPLAY_REFUSED, session.session_id)
            except APIError as exc:
                failed += 1
                logger.warning(_SESSION_REPLAY_API_ERROR, session.session_id, exc.detail)

        logger.info(_REPLAY_SUMMARY, completed, failed)
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
        help="List candidates with a read-only API query; do not request session replay",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    configure_logging("teleclaude")

    try:
        _ = config.computer.name
    except Exception as exc:
        logger.error(_CONFIG_NOT_READY, exc)
        return 1

    count = await _replay_closed_sessions(hours=args.hours, dry_run=args.dry_run)
    logger.info(_DONE_MESSAGE, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
