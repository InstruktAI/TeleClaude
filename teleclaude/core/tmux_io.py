"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import asyncio
from signal import Signals

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agent_prompt_state import (
    PromptDeliveryObservation,
    PromptDeliveryState,
    classify_prompt_delivery,
    is_codex_collapsed_paste_marker,
)
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

# Confirmed user-turn delivery. A single blind paste+submit can lose ordering
# under tmux congestion: the discrete Enter may be swallowed while the target
# text stays in the live input. Paste is single-shot because repeating it
# corrupts the editor buffer; recovery retries only Enter and only while the
# target still appears in that live input.
INJECT_TURN_START_TIMEOUT_S = 8.0
INJECT_PASTE_VISIBLE_TIMEOUT_S = 8.0
INJECT_PROMPT_OBSERVE_INTERVAL_S = 0.1
INJECT_SUBMIT_RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0)


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

    Paste is attempted once. Submit is retried with Enter only while the pane
    shows ``text`` in the live prompt input. The routine never clears the prompt
    and never re-pastes after a successful paste operation.

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
        before_paste = await _observe_prompt_delivery(
            session,
            text,
            active_agent=active_agent,
            accept_codex_collapsed_paste=False,
        )
        stale_collapsed_live_input = (
            before_paste.live_input if is_codex_collapsed_paste_marker(before_paste.live_input) else None
        )
        pasted = await tmux_bridge.paste_text_existing_tmux(
            session_name=tmux_name,
            text=text,
            active_agent=active_agent,
        )
        if not pasted:
            logger.warning("inject_user_turn: paste failed session=%s", session.session_id)
            return False

        observation = await _wait_for_prompt_delivery_observation(
            session,
            text,
            active_agent=active_agent,
            turn_started=turn_started,
            timeout_s=INJECT_PASTE_VISIBLE_TIMEOUT_S,
            stale_collapsed_live_input=stale_collapsed_live_input,
        )
        if turn_started.done():
            logger.info("inject_user_turn: turn started during paste observation session=%s", session.session_id)
            return True
        if observation.state == PromptDeliveryState.SUBMITTED:
            return await _confirm_observed_submission(
                session,
                turn_started=turn_started,
                source="paste_observation",
                attempt=1,
                attempt_total=1,
            )
        if observation.state == PromptDeliveryState.IN_INPUT:
            return await _submit_observed_user_turn(
                session,
                text,
                active_agent=active_agent,
                turn_started=turn_started,
                initial_observation=observation,
            )

        logger.warning(
            "inject_user_turn: target not confirmed after single paste session=%s state=%s live_input=%r",
            session.session_id,
            observation.state.value,
            observation.live_input[:80],
        )
        return False
    finally:
        event_bus.unsubscribe(TeleClaudeEvents.AGENT_ACTIVITY, handler)


async def _confirm_observed_submission(
    session: Session,
    *,
    turn_started: asyncio.Future[None],
    source: str,
    attempt: int,
    attempt_total: int,
) -> bool:
    if await _wait_for_turn_started(turn_started, INJECT_TURN_START_TIMEOUT_S):
        logger.info(
            "inject_user_turn: turn confirmed after pane submission observation session=%s source=%s attempt=%d/%d",
            session.session_id,
            source,
            attempt,
            attempt_total,
        )
        return True
    logger.warning(
        "inject_user_turn: pane showed submitted state without turn-start confirmation session=%s source=%s attempt=%d/%d",
        session.session_id,
        source,
        attempt,
        attempt_total,
    )
    return False


async def _wait_for_prompt_delivery_observation(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    turn_started: asyncio.Future[None],
    timeout_s: float,
    stale_collapsed_live_input: str | None,
) -> PromptDeliveryObservation:
    deadline = asyncio.get_running_loop().time() + timeout_s
    observation = await _observe_prompt_delivery(
        session,
        text,
        active_agent=active_agent,
        accept_codex_collapsed_paste=True,
    )
    ignored_collapsed = _is_stale_collapsed_observation(observation, stale_collapsed_live_input)
    while (observation.state == PromptDeliveryState.ABSENT or ignored_collapsed) and not turn_started.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            if ignored_collapsed:
                return PromptDeliveryObservation(PromptDeliveryState.ABSENT, observation.live_input)
            return observation
        await asyncio.sleep(min(INJECT_PROMPT_OBSERVE_INTERVAL_S, remaining))
        observation = await _observe_prompt_delivery(
            session,
            text,
            active_agent=active_agent,
            accept_codex_collapsed_paste=True,
        )
        ignored_collapsed = _is_stale_collapsed_observation(observation, stale_collapsed_live_input)
    return observation


async def _observe_prompt_delivery(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    accept_codex_collapsed_paste: bool,
) -> PromptDeliveryObservation:
    output = await tmux_bridge.capture_pane(session.tmux_session_name)
    return classify_prompt_delivery(
        output,
        text,
        active_agent,
        accept_codex_collapsed_paste=accept_codex_collapsed_paste,
    )


def _is_stale_collapsed_observation(
    observation: PromptDeliveryObservation,
    stale_collapsed_live_input: str | None,
) -> bool:
    return (
        stale_collapsed_live_input is not None
        and observation.live_input == stale_collapsed_live_input
        and is_codex_collapsed_paste_marker(observation.live_input)
    )


async def _submit_observed_user_turn(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    turn_started: asyncio.Future[None],
    initial_observation: PromptDeliveryObservation,
) -> bool:
    observation = initial_observation
    for submit_attempt, delay_s in enumerate(INJECT_SUBMIT_RETRY_DELAYS_S, start=1):
        if observation.state == PromptDeliveryState.SUBMITTED:
            return await _confirm_observed_submission(
                session,
                turn_started=turn_started,
                source="submit_observation",
                attempt=submit_attempt,
                attempt_total=len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
        if observation.state != PromptDeliveryState.IN_INPUT:
            return turn_started.done()

        submitted = await tmux_bridge.send_enter(session.tmux_session_name)
        if not submitted:
            logger.warning(
                "inject_user_turn: enter failed session=%s attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )

        if await _wait_for_turn_started(turn_started, delay_s):
            logger.info(
                "inject_user_turn: turn started session=%s submit_attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
            return True

        observation = await _observe_prompt_delivery(
            session,
            text,
            active_agent=active_agent,
            accept_codex_collapsed_paste=True,
        )
        if observation.state == PromptDeliveryState.SUBMITTED:
            return await _confirm_observed_submission(
                session,
                turn_started=turn_started,
                source="submit_observation",
                attempt=submit_attempt,
                attempt_total=len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
        if observation.state == PromptDeliveryState.ABSENT:
            if await _wait_for_turn_started(turn_started, INJECT_TURN_START_TIMEOUT_S):
                return True
            logger.warning(
                "inject_user_turn: target left input without confirmation session=%s submit_attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
            return False

        logger.warning(
            "inject_user_turn: target still in input after enter session=%s submit_attempt=%d/%d",
            session.session_id,
            submit_attempt,
            len(INJECT_SUBMIT_RETRY_DELAYS_S),
        )

    return False


async def _wait_for_turn_started(turn_started: asyncio.Future[None], timeout_s: float) -> bool:
    if turn_started.done():
        return True
    try:
        await asyncio.wait_for(asyncio.shield(turn_started), timeout=timeout_s)
    except TimeoutError:
        return turn_started.done()
    return True


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
