"""Tmux delivery sink for listener notifications (tmux only)."""

from __future__ import annotations

import asyncio

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge

logger = get_logger(__name__)

# Per-attempt timeout for the underlying `tmux send-keys` subprocess.
# Higher than the default SUBPROCESS_TIMEOUT_QUICK because the destination
# pane may be busy consuming prior input — listener delivery is not
# latency-critical and a few extra seconds is preferable to dropping a
# notification.
LISTENER_DELIVERY_TIMEOUT_S = 15.0

# Sleep durations (seconds) inserted between successive attempts.
# Length determines retry count: this tuple yields ``len(...) + 1`` total
# attempts. Tuned for the multi-second tmux-server stalls observed in
# practice (concurrent send-keys flooding the command socket).
LISTENER_RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0, 10.0)


async def deliver_listener_message(session_id: str, tmux_session: str, message: str) -> bool:
    """Deliver a notification to a listener via tmux, with bounded retry.

    Retries on transient ``send-keys`` failures (timeouts, nonzero exits)
    using the backoff schedule in :data:`LISTENER_RETRY_BACKOFF_S`. A single
    successful injection ends the loop; exhaustion is logged at ERROR.
    """
    preview = message.replace("\n", "\\n")[:160]
    total_attempts = len(LISTENER_RETRY_BACKOFF_S) + 1

    for attempt in range(1, total_attempts + 1):
        logger.debug(
            "Deliver listener message",
            session=session_id,
            tmux=tmux_session,
            attempt=attempt,
            of=total_attempts,
            preview=preview,
        )
        delivered = await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_session,
            text=message,
            timeout=LISTENER_DELIVERY_TIMEOUT_S,
        )
        if delivered:
            if attempt > 1:
                logger.info(
                    "Listener delivery succeeded after retries",
                    session=session_id,
                    tmux=tmux_session,
                    attempt=attempt,
                )
            return True

        if attempt < total_attempts:
            backoff = LISTENER_RETRY_BACKOFF_S[attempt - 1]
            logger.warning(
                "Listener delivery attempt failed; retrying",
                session=session_id,
                tmux=tmux_session,
                attempt=attempt,
                of=total_attempts,
                next_backoff_s=backoff,
            )
            await asyncio.sleep(backoff)

    logger.error(
        "Listener delivery exhausted retries",
        session=session_id,
        tmux=tmux_session,
        attempts=total_attempts,
    )
    return False
