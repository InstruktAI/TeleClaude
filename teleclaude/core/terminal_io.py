"""Session-aware terminal I/O routing.

Routes terminal input based on session origin:
- UI-origin sessions -> tmux
- terminal-origin sessions -> native TTY
"""

from __future__ import annotations

import os
import signal as signal_module
from typing import Optional

from instrukt_ai_logging import get_logger

from teleclaude.core import terminal_bridge
from teleclaude.core.db import db
from teleclaude.core.models import Session

logger = get_logger(__name__)


def _parse_terminal_size(value: str | None) -> tuple[int, int]:
    if value and "x" in value:
        try:
            cols_str, rows_str = value.split("x", 1)
            cols = int(cols_str)
            rows = int(rows_str)
            if cols > 0 and rows > 0:
                return cols, rows
        except ValueError:
            pass
    return 80, 24


async def _get_terminal_identity(session: Session) -> tuple[Optional[str], Optional[int]]:
    ux_state = await db.get_ux_state(session.session_id)
    tty_path = ux_state.native_tty_path if ux_state else None
    pid = ux_state.native_pid if ux_state else None
    if isinstance(tty_path, str) and tty_path:
        return tty_path, pid if isinstance(pid, int) else None
    return None, None


async def _send_to_tty(session: Session, payload: str, *, send_enter: bool = False) -> bool:
    tty_path, pid = await _get_terminal_identity(session)
    if not tty_path:
        logger.warning("No native TTY registered for session %s", session.session_id[:8])
        return False
    if pid is not None and not terminal_bridge.pid_is_alive(pid):
        logger.warning("Native PID not alive for session %s", session.session_id[:8])
        return False
    return await terminal_bridge.send_keys_to_tty(tty_path, payload, send_enter=send_enter)


def _ctrl_code(key: str) -> Optional[str]:
    if len(key) != 1:
        return None
    char = key.upper()
    if "A" <= char <= "Z":
        return chr(ord(char) - 64)

    mapping = {
        "@": "\x00",
        "[": "\x1b",
        "\\": "\x1c",
        "]": "\x1d",
        "^": "\x1e",
        "_": "\x1f",
    }
    return mapping.get(char)


async def send_text(
    session: Session,
    text: str,
    *,
    send_enter: bool = True,
    active_agent: Optional[str] = None,
    working_dir: Optional[str] = None,
    cols: Optional[int] = None,
    rows: Optional[int] = None,
) -> bool:
    if session.origin_adapter == "terminal":
        tmux_name = session.tmux_session_name
        if tmux_name and await terminal_bridge.session_exists(tmux_name):
            return await terminal_bridge.send_keys_existing_tmux(
                session_name=tmux_name,
                text=text,
                send_enter=send_enter,
                active_agent=active_agent,
            )
        return await _send_to_tty(session, text, send_enter=send_enter)

    working_dir = working_dir if working_dir is not None else session.working_directory
    if cols is None or rows is None:
        cols, rows = _parse_terminal_size(session.terminal_size)

    return await terminal_bridge.send_keys(
        session.tmux_session_name,
        text,
        session_id=session.session_id,
        working_dir=working_dir,
        cols=cols,
        rows=rows,
        send_enter=send_enter,
        active_agent=active_agent,
    )


async def send_escape(session: Session) -> bool:
    if session.origin_adapter == "terminal":
        return await _send_to_tty(session, "\x1b", send_enter=False)
    return await terminal_bridge.send_escape(session.tmux_session_name)


async def send_ctrl_key(session: Session, key: str) -> bool:
    if session.origin_adapter == "terminal":
        code = _ctrl_code(key)
        if not code:
            logger.warning("Invalid CTRL key '%s' for session %s", key, session.session_id[:8])
            return False
        return await _send_to_tty(session, code, send_enter=False)
    return await terminal_bridge.send_ctrl_key(session.tmux_session_name, key)


async def send_tab(session: Session) -> bool:
    if session.origin_adapter == "terminal":
        return await _send_to_tty(session, "\t", send_enter=False)
    return await terminal_bridge.send_tab(session.tmux_session_name)


async def send_shift_tab(session: Session, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid shift-tab count %d for session %s", count, session.session_id[:8])
        return False
    if session.origin_adapter == "terminal":
        return await _send_to_tty(session, "\x1b[Z" * count, send_enter=False)
    return await terminal_bridge.send_shift_tab(session.tmux_session_name, count)


async def send_backspace(session: Session, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid backspace count %d for session %s", count, session.session_id[:8])
        return False
    if session.origin_adapter == "terminal":
        return await _send_to_tty(session, "\x7f" * count, send_enter=False)
    return await terminal_bridge.send_backspace(session.tmux_session_name, count)


async def send_enter(session: Session) -> bool:
    if session.origin_adapter == "terminal":
        return await _send_to_tty(session, "", send_enter=True)
    return await terminal_bridge.send_enter(session.tmux_session_name)


async def send_arrow_key(session: Session, direction: str, count: int = 1) -> bool:
    if count < 1:
        logger.warning("Invalid arrow count %d for session %s", count, session.session_id[:8])
        return False

    if session.origin_adapter == "terminal":
        codes = {
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
        }
        seq = codes.get(direction.lower())
        if not seq:
            logger.warning("Invalid arrow direction '%s' for session %s", direction, session.session_id[:8])
            return False
        return await _send_to_tty(session, seq * count, send_enter=False)

    return await terminal_bridge.send_arrow_key(session.tmux_session_name, direction, count)


async def send_signal(session: Session, signal: str) -> bool:
    if session.origin_adapter != "terminal":
        return await terminal_bridge.send_signal(session.tmux_session_name, signal)

    if signal == "SIGINT":
        return await send_ctrl_key(session, "c")
    if signal == "SIGTERM":
        return await send_ctrl_key(session, "\\")
    if signal == "SIGKILL":
        _tty_path, pid = await _get_terminal_identity(session)
        if pid is None:
            logger.warning("No native PID for SIGKILL in session %s", session.session_id[:8])
            return False
        try:
            os.kill(pid, signal_module.SIGKILL)
            return True
        except Exception as exc:
            logger.warning("Failed to SIGKILL pid %s for session %s: %s", pid, session.session_id[:8], exc)
            return False

    logger.warning("Unsupported signal %s for terminal-origin session %s", signal, session.session_id[:8])
    return False


async def is_process_running(session: Session) -> bool:
    if session.origin_adapter == "terminal":
        _tty_path, pid = await _get_terminal_identity(session)
        if isinstance(pid, int):
            return terminal_bridge.pid_is_alive(pid)
        return False
    return await terminal_bridge.is_process_running(session.tmux_session_name)


async def wait_for_shell_ready(session: Session) -> bool:
    if session.origin_adapter == "terminal":
        return True
    return await terminal_bridge.wait_for_shell_ready(session.tmux_session_name)
