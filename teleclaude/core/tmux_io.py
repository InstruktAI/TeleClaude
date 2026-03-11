"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import asyncio
import string
from signal import Signals

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agents import get_agent_command
from teleclaude.core.codex_prompt_normalization import normalize_codex_next_command
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.core.voice_assignment import get_voice_env_vars

logger = get_logger(__name__)

_SPECIAL_CHARS = frozenset(set(string.punctuation) - {"/"})
_BRACKETED_PASTE_START = "\x1b[200~"
_BRACKETED_PASTE_END = "\x1b[201~"


def wrap_bracketed_paste(text: str, active_agent: str | None = None) -> str:
    if not text:
        return text
    text = normalize_codex_next_command(active_agent, text)
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


async def _revive_headless_and_send(
    session: Session,
    text: str,
    *,
    send_enter: bool,
    active_agent: str | None,
    working_dir: str,
) -> bool:
    """Create a tmux session for a headless session on the fly and send text to it.

    Mutates session.tmux_session_name in-place so callers (e.g. deliver_inbound)
    can use the updated name for downstream operations like start_polling.
    """
    tmux_name = session.tmux_session_name
    if not tmux_name:
        tmux_name = f"{TMUX_SESSION_PREFIX}{session.session_id[:8]}"

    voice = await db.get_voice(session.session_id)
    env_vars = get_voice_env_vars(voice) if voice else {}

    created = await tmux_bridge.ensure_tmux_session(
        name=tmux_name,
        working_dir=working_dir,
        session_id=session.session_id,
        env_vars=env_vars,
    )
    if not created:
        logger.warning("Failed to create tmux session for headless session %s", session.session_id[:8])
        return False

    if session.active_agent and session.native_session_id:
        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
        )
        wrapped_resume = wrap_bracketed_paste(resume_cmd, active_agent=session.active_agent)
        await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=wrapped_resume,
            send_enter=True,
            active_agent=session.active_agent,
        )
        logger.info(
            "Revived headless session %s with agent %s (native=%s)",
            session.session_id[:8],
            session.active_agent,
            session.native_session_id[:8],
        )

    # Update in-place so callers see the new tmux_session_name immediately
    session.tmux_session_name = tmux_name
    asyncio.create_task(db.update_session(session.session_id, lifecycle_status="active", tmux_session_name=tmux_name))

    return await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=text,
        send_enter=send_enter,
        active_agent=active_agent,
    )


async def _send_to_tmux(
    session: Session,
    text: str,
    *,
    send_enter: bool,
    active_agent: str | None = None,
    working_dir: str,
) -> bool:
    tmux_name = session.tmux_session_name
    if tmux_name and await tmux_bridge.session_exists(tmux_name, log_missing=False):
        return await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=text,
            send_enter=send_enter,
            active_agent=active_agent,
        )

    if session.lifecycle_status == "headless":
        return await _revive_headless_and_send(
            session, text, send_enter=send_enter, active_agent=active_agent, working_dir=working_dir
        )

    logger.warning(
        "tmux session unavailable for session %s; maintenance healing required",
        session.session_id[:8],
    )
    return False


async def process_text(
    session: Session,
    text: str,
    *,
    send_enter: bool = True,
    active_agent: str | None = None,
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
