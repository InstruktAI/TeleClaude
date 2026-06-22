"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import asyncio
from signal import Signals

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import AgentActivityEvent, AgentHookEvents, TeleClaudeEvents
from teleclaude.core.models import Session
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.voice_assignment import get_voice_env_vars

logger = get_logger(__name__)

# Confirmed user-turn delivery. A single blind paste+submit is lost when the
# readiness race resolves before the agent is listening (swallowed paste) or the
# submit Enter lands inside the bracketed-paste span (text sits unsubmitted). The
# wrapper below observes a positive turn-start signal — the `user_prompt_submit`
# agent-activity event the runtime already tracks — and idempotently re-injects
# until the turn starts or the cap is reached.
INJECT_TURN_START_TIMEOUT_S = 8.0
INJECT_MAX_ATTEMPTS = 3


async def _revive_headless_and_send(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    working_dir: str,
) -> bool:
    """Create a tmux session for a headless session on the fly and send text to it.

    Mutates session.tmux_session_name in-place so callers (e.g. deliver_inbound)
    can use the updated name for downstream operations like start_polling.
    """
    tmux_name = session.tmux_session_name
    if not tmux_name:
        tmux_name = f"{TMUX_SESSION_PREFIX}{session.session_id}"

    voice = await db.get_voice(session.session_id)
    env_vars = build_agent_session_environment(
        project_path=session.project_path,
        platform_env=get_voice_env_vars(voice) if voice else {},
    )

    if not await ensure_tmux_with_identity(session, tmux_name, working_dir, env_vars):
        logger.warning("Failed to create tmux session for headless session %s", session.session_id)
        return False

    if session.active_agent and session.native_session_id:
        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
        )
        await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=resume_cmd,
            active_agent=session.active_agent,
        )
        logger.info(
            "Revived headless session %s with agent %s (native=%s)",
            session.session_id,
            session.active_agent,
            session.native_session_id,
        )

    # Update in-place so callers see the new tmux_session_name immediately
    session.tmux_session_name = tmux_name
    asyncio.create_task(
        db.update_session(session.session_id, lifecycle_status="active", tmux_session_name=tmux_name),
        name="tmux-db-update",
    )

    return await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=text,
        active_agent=active_agent,
    )


async def _send_to_tmux(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    working_dir: str,
) -> bool:
    tmux_name = session.tmux_session_name
    if tmux_name and await tmux_bridge.session_exists(tmux_name, log_missing=False):
        return await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=text,
            active_agent=active_agent,
        )

    if session.lifecycle_status == "headless":
        return await _revive_headless_and_send(
            session,
            text,
            active_agent=active_agent,
            working_dir=working_dir,
        )

    logger.warning(
        "tmux session unavailable for session %s; maintenance healing required",
        session.session_id,
    )
    return False


async def process_text(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    working_dir: str,
) -> bool:
    """Process and route text input to the appropriate tmux session."""
    return await _send_to_tmux(
        session,
        text,
        active_agent=active_agent,
        working_dir=working_dir,
    )


async def inject_user_turn(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
) -> bool:
    """Inject a user-turn message and confirm the agent actually started a turn.

    Pastes ``text`` via the shared submit path, then waits for a positive
    turn-start signal — the ``user_prompt_submit`` agent-activity event the
    runtime already emits when the agent accepts a turn. "Input left the box" is
    NOT treated as success: a swallowed paste also empties the input line. When no
    turn start is observed within the per-attempt window, the input line is
    cleared (so a landed-but-unsubmitted paste is not duplicated) and the text is
    re-pasted and resubmitted, bounded by ``INJECT_MAX_ATTEMPTS``.

    Returns True when a turn start is confirmed, False when the retry cap is
    exhausted with no started turn (the caller fails loudly — no silent drop).
    """
    tmux_name = session.tmux_session_name or ""
    loop = asyncio.get_running_loop()
    turn_started: asyncio.Future[None] = loop.create_future()

    async def _on_activity(_event_type: str, ctx: AgentActivityEvent) -> None:
        if (
            ctx.session_id == session.session_id
            and ctx.event_type == AgentHookEvents.USER_PROMPT_SUBMIT
            and not turn_started.done()
        ):
            turn_started.set_result(None)

    handler = event_bus.subscribe(TeleClaudeEvents.AGENT_ACTIVITY, _on_activity)
    try:
        for attempt in range(1, INJECT_MAX_ATTEMPTS + 1):
            if attempt > 1:
                # Clear any landed-but-unsubmitted paste before re-injecting so a
                # swallowed-Enter does not accumulate duplicated content.
                await tmux_bridge.send_ctrl_key(tmux_name, "u")
            sent = await tmux_bridge.send_keys_existing_tmux(
                session_name=tmux_name,
                text=text,
                active_agent=active_agent,
            )
            if not sent:
                logger.warning(
                    "inject_user_turn: paste failed session=%s attempt=%d/%d",
                    session.session_id,
                    attempt,
                    INJECT_MAX_ATTEMPTS,
                )
            try:
                await asyncio.wait_for(asyncio.shield(turn_started), timeout=INJECT_TURN_START_TIMEOUT_S)
            except TimeoutError:
                logger.warning(
                    "inject_user_turn: no turn start session=%s attempt=%d/%d",
                    session.session_id,
                    attempt,
                    INJECT_MAX_ATTEMPTS,
                )
                continue
            logger.info(
                "inject_user_turn: turn started session=%s attempt=%d/%d",
                session.session_id,
                attempt,
                INJECT_MAX_ATTEMPTS,
            )
            return True
        return False
    finally:
        event_bus.unsubscribe(TeleClaudeEvents.AGENT_ACTIVITY, handler)


async def send_escape(session: Session) -> bool:
    """Send an escape key to the session's tmux pane."""
    return await tmux_bridge.send_escape(session.tmux_session_name)


async def send_ctrl_key(session: Session, key: str) -> bool:
    """Send a Ctrl+key combination to the session's tmux pane."""
    return await tmux_bridge.send_ctrl_key(session.tmux_session_name, key)


async def send_tab(session: Session) -> bool:
    """Send a tab key to the session's tmux pane."""
    return await tmux_bridge.send_tab(session.tmux_session_name)


async def send_shift_tab(session: Session, count: int = 1) -> bool:
    """Send shift-tab key(s) to the session's tmux pane."""
    if count < 1:
        logger.warning("Invalid shift-tab count %d for session %s", count, session.session_id)
        return False
    return await tmux_bridge.send_shift_tab(session.tmux_session_name, count)


async def send_backspace(session: Session, count: int = 1) -> bool:
    """Send backspace key(s) to the session's tmux pane."""
    if count < 1:
        logger.warning("Invalid backspace count %d for session %s", count, session.session_id)
        return False
    return await tmux_bridge.send_backspace(session.tmux_session_name, count)


async def send_enter(session: Session) -> bool:
    """Send an enter key to the session's tmux pane."""
    return await tmux_bridge.send_enter(session.tmux_session_name)


async def send_arrow_key(session: Session, direction: str, count: int = 1) -> bool:
    """Send arrow key(s) to the session's tmux pane."""
    if count < 1:
        logger.warning("Invalid arrow count %d for session %s", count, session.session_id)
        return False

    return await tmux_bridge.send_arrow_key(session.tmux_session_name, direction, count)


async def send_signal(session: Session, signal: Signals | str) -> bool:
    """Send a POSIX signal to the session's tmux pane process."""
    if isinstance(signal, str):
        try:
            signal = Signals[signal]
        except KeyError:
            logger.warning("Unknown signal %s for session %s", signal, session.session_id)
            return False
    return await tmux_bridge.send_signal(session.tmux_session_name, signal)


async def is_process_running(session: Session) -> bool:
    """Check if the session's tmux pane has a running process."""
    return await tmux_bridge.is_process_running(session.tmux_session_name)


async def wait_for_shell_ready(session: Session) -> bool:
    """Wait until the session's tmux pane has a ready shell."""
    return await tmux_bridge.wait_for_shell_ready(session.tmux_session_name)
