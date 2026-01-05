"""Terminal delivery sink for listener notifications.

Centralizes terminal injection (tmux + TTY fallback) so callers don't
duplicate routing logic.
"""

from __future__ import annotations

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db

logger = get_logger(__name__)


async def deliver_listener_message(session_id: str, tmux_session: str, message: str) -> bool:
    """Deliver a notification to a listener via tmux or fallback TTY."""
    delivered = await terminal_bridge.send_keys_existing_tmux(
        session_name=tmux_session,
        text=message,
        send_enter=True,
    )
    if delivered:
        return True

    session = await db.get_session(session_id)
    if not session or session.origin_adapter != "terminal":
        logger.debug("Terminal delivery skipped (non-terminal origin)", session=session_id[:8])
        return False

    ux_state = await db.get_ux_state(session_id)
    tty_path = ux_state.native_tty_path
    pid = ux_state.native_pid
    if isinstance(tty_path, str) and tty_path and isinstance(pid, int) and terminal_bridge.pid_is_alive(pid):
        return await terminal_bridge.send_keys_to_tty(tty_path, message, send_enter=True)

    logger.debug("Terminal delivery failed (no tmux/tty)", session=session_id[:8])
    return False
