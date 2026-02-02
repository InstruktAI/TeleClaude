"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import string
from signal import Signals
from typing import Optional

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.models import Session

logger = get_logger(__name__)

_SPECIAL_CHARS = frozenset(set(string.punctuation) - {"/"})
_BRACKETED_PASTE_START = "\x1b[200~"
_BRACKETED_PASTE_END = "\x1b[201~"


def wrap_bracketed_paste(text: str) -> str:
    if not text:
        return text
    # Only bypass bracketed paste for single-word slash commands (e.g., /help, /exit)
    # Absolute paths like /Users/... should still be wrapped to prevent shell echo
    stripped = text.lstrip()
    if stripped.startswith("/"):
        first_word = stripped.split()[0] if stripped else ""
        slash_count = first_word.count("/")
        # Single slash = command (/help), multiple slashes = path (/Users/...)
        if slash_count == 1:
            logger.debug("Bypassing bracketed paste for slash command: %s", text[:50])
            return text
        logger.debug("Will wrap path (slash_count=%d): %s", slash_count, text[:80])
    if any(char in _SPECIAL_CHARS for char in text):
        wrapped = f"{_BRACKETED_PASTE_START}{text}{_BRACKETED_PASTE_END}"
        logger.debug("Wrapped with bracketed paste (has special chars): %s", text[:80])
        return wrapped
    logger.debug("No wrapping needed (no special chars): %s", text[:50])
    return text


async def _send_to_tmux(
    session: Session,
    text: str,
    *,
    send_enter: bool,
    active_agent: Optional[str] = None,
    working_dir: str,
) -> bool:
    tmux_name = session.tmux_session_name
    if tmux_name and await tmux_bridge.session_exists(tmux_name):
        return await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=text,
            send_enter=send_enter,
            active_agent=active_agent,
        )

    return await tmux_bridge.send_keys(
        session.tmux_session_name,
        text,
        session_id=session.session_id,
        working_dir=working_dir,
        send_enter=send_enter,
        active_agent=active_agent,
    )


async def send_text(
    session: Session,
    text: str,
    *,
    send_enter: bool = True,
    active_agent: Optional[str] = None,
    working_dir: str,
) -> bool:
    return await _send_to_tmux(
        session,
        text,
        send_enter=send_enter,
        active_agent=active_agent,
        working_dir=working_dir,
    )


async def send_escape(session: Session) -> bool:
    return await tmux_bridge.send_escape(session.tmux_session_name)


async def send_ctrl_key(session: Session, key: str) -> bool:
    return await tmux_bridge.send_ctrl_key(session.tmux_session_name, key)


async def send_tab(session: Session) -> bool:
    return await tmux_bridge.send_tab(session.tmux_session_name)


async def send_shift_tab(session: Session, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid shift-tab count %d for session %s", count, session.session_id[:8])
        return False
    return await tmux_bridge.send_shift_tab(session.tmux_session_name, count)


async def send_backspace(session: Session, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid backspace count %d for session %s", count, session.session_id[:8])
        return False
    return await tmux_bridge.send_backspace(session.tmux_session_name, count)


async def send_enter(session: Session) -> bool:
    return await tmux_bridge.send_enter(session.tmux_session_name)


async def send_arrow_key(session: Session, direction: str, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid arrow count %d for session %s", count, session.session_id[:8])
        return False

    return await tmux_bridge.send_arrow_key(session.tmux_session_name, direction, count)


async def send_signal(session: Session, signal: Signals | str) -> bool:
    if isinstance(signal, str):
        try:
            signal = Signals[signal]
        except KeyError:
            logger.warning("Unknown signal %s for session %s", signal, session.session_id[:8])
            return False
    return await tmux_bridge.send_signal(session.tmux_session_name, signal)


async def is_process_running(session: Session) -> bool:
    return await tmux_bridge.is_process_running(session.tmux_session_name)


async def wait_for_shell_ready(session: Session) -> bool:
    return await tmux_bridge.wait_for_shell_ready(session.tmux_session_name)
