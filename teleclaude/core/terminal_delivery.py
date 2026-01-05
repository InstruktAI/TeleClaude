"""Terminal delivery sink for listener notifications (tmux only)."""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge

logger = get_logger(__name__)


async def deliver_listener_message(session_id: str, tmux_session: str, message: str) -> bool:
    """Deliver a notification to a listener via tmux."""
    delivered = await terminal_bridge.send_keys_existing_tmux(
        session_name=tmux_session,
        text=message,
        send_enter=True,
    )
    if delivered:
        return True

    logger.debug("Terminal delivery failed (no tmux)", session=session_id[:8])
    return False
