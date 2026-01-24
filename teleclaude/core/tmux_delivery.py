"""Tmux delivery sink for listener notifications (tmux only)."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge

logger = get_logger(__name__)


async def deliver_listener_message(session_id: str, tmux_session: str, message: str) -> bool:
    """Deliver a notification to a listener via tmux."""
    preview = message.replace("\n", "\\n")[:160]
    logger.debug(
        "Deliver listener message: session=%s tmux=%s preview=%r",
        session_id[:8],
        tmux_session,
        preview,
    )
    delivered = await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_session,
        text=message,
        send_enter=True,
    )
    if delivered:
        return True

    logger.debug("Tmux delivery failed (no tmux)", session=session_id[:8])
    return False
