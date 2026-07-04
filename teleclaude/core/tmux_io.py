"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import asyncio
import hashlib
from signal import Signals

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agent_prompt_state import (
    PromptDeliveryObservation,
    PromptDeliveryState,
    classify_prompt_delivery,
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
from teleclaude.utils import strip_ansi_codes

logger = get_logger(__name__)

# Prompt-state user-turn delivery. A single blind paste+submit can lose ordering
# under tmux congestion: the discrete Enter may be swallowed while the pasted
# input stays live. Paste is single-shot because repeating it corrupts the
# editor buffer; recovery retries only Enter and only while effective input
# remains in that live prompt.
INJECT_TURN_START_TIMEOUT_S = 8.0
INJECT_PASTE_VISIBLE_TIMEOUT_S = 8.0
INJECT_PASTE_LANDED_TIMEOUT_S = 60.0
INJECT_PROMPT_OBSERVE_INTERVAL_S = 0.1
INJECT_SUBMIT_RETRY_DELAYS_S: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0)


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
    """Inject a user-turn message and confirm the prompt accepted submission.

    Paste is attempted once. Submit is retried with Enter only after the pane
    shows a live prompt input change. The routine never clears the prompt and
    never re-pastes after a successful paste operation.

    Returns True when the live prompt no longer holds the pasted input or an
    agent activity hook arrives first, False when the retry cap is exhausted
    with the input still stuck (the caller fails loudly — no silent drop).
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
            pre_paste_live_input=before_paste.live_input,
        )
        if observation.state == PromptDeliveryState.ABSENT and not turn_started.done():
            logger.info(
                "inject_user_turn: prompt input not observed after initial paste window; "
                "continuing observation session=%s timeout_s=%.1f",
                session.session_id,
                INJECT_PASTE_LANDED_TIMEOUT_S,
            )
            observation = await _wait_for_prompt_delivery_observation(
                session,
                text,
                active_agent=active_agent,
                turn_started=turn_started,
                timeout_s=INJECT_PASTE_LANDED_TIMEOUT_S,
                pre_paste_live_input=before_paste.live_input,
            )
        if turn_started.done():
            logger.info("inject_user_turn: turn started during paste observation session=%s", session.session_id)
            return True
        if observation.state == PromptDeliveryState.SUBMITTED:
            _log_prompt_delivery_evidence(
                "inject_user_turn: pane showed submitted state before enter",
                session=session,
                observation=observation,
            )
            return False
        if observation.state == PromptDeliveryState.IN_INPUT:
            return await _submit_observed_user_turn(
                session,
                text,
                active_agent=active_agent,
                turn_started=turn_started,
                initial_observation=observation,
            )

        _log_prompt_delivery_evidence(
            "inject_user_turn: target not confirmed after single paste",
            session=session,
            observation=observation,
        )
        return False
    finally:
        event_bus.unsubscribe(TeleClaudeEvents.AGENT_ACTIVITY, handler)


async def _wait_for_prompt_delivery_observation(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    turn_started: asyncio.Future[None],
    timeout_s: float,
    pre_paste_live_input: str,
) -> PromptDeliveryObservation:
    deadline = asyncio.get_running_loop().time() + timeout_s
    observation = await _observe_prompt_delivery(
        session,
        text,
        active_agent=active_agent,
    )
    observation = _accept_new_live_input_after_paste(
        observation,
        pre_paste_live_input=pre_paste_live_input,
    )
    while observation.state == PromptDeliveryState.ABSENT and not turn_started.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return observation
        await asyncio.sleep(min(INJECT_PROMPT_OBSERVE_INTERVAL_S, remaining))
        observation = await _observe_prompt_delivery(
            session,
            text,
            active_agent=active_agent,
        )
        observation = _accept_new_live_input_after_paste(
            observation,
            pre_paste_live_input=pre_paste_live_input,
        )
    return observation


async def _observe_prompt_delivery(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    output = await tmux_bridge.capture_pane(session.tmux_session_name)
    return classify_prompt_delivery(output, text, active_agent)


def _accept_new_live_input_after_paste(
    observation: PromptDeliveryObservation,
    *,
    pre_paste_live_input: str,
) -> PromptDeliveryObservation:
    live_input = observation.live_input.strip()
    if not live_input or live_input == pre_paste_live_input.strip():
        if observation.state == PromptDeliveryState.ABSENT:
            return observation
        return PromptDeliveryObservation(
            PromptDeliveryState.ABSENT, observation.live_input, observation.raw_live_region
        )
    logger.debug(
        "inject_user_turn: accepting changed live input after paste without exact target reconstruction "
        "live_input_len=%d live_input_sha256=%s",
        len(live_input),
        _prompt_delivery_evidence_digest(live_input),
    )
    return PromptDeliveryObservation(PromptDeliveryState.IN_INPUT, live_input, observation.raw_live_region)


def _accept_current_live_input(observation: PromptDeliveryObservation) -> PromptDeliveryObservation:
    if observation.state != PromptDeliveryState.ABSENT:
        return observation
    live_input = observation.live_input.strip()
    if not live_input:
        return observation
    return PromptDeliveryObservation(PromptDeliveryState.IN_INPUT, live_input, observation.raw_live_region)


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
            logger.info(
                "inject_user_turn: prompt submitted session=%s submit_attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
            return True
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

        observation = await _wait_for_post_enter_prompt_state(
            session,
            text,
            active_agent=active_agent,
            turn_started=turn_started,
            timeout_s=delay_s,
        )
        if observation.state == PromptDeliveryState.SUBMITTED:
            logger.info(
                "inject_user_turn: prompt submitted session=%s submit_attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
            return True
        if observation.state == PromptDeliveryState.ABSENT:
            logger.info(
                "inject_user_turn: prompt input cleared after enter session=%s submit_attempt=%d/%d",
                session.session_id,
                submit_attempt,
                len(INJECT_SUBMIT_RETRY_DELAYS_S),
            )
            return True

        _log_prompt_delivery_evidence(
            "inject_user_turn: target still in input after enter",
            session=session,
            observation=observation,
            submit_attempt=submit_attempt,
            submit_attempts=len(INJECT_SUBMIT_RETRY_DELAYS_S),
        )

    _log_prompt_delivery_evidence(
        "inject_user_turn: input remained stuck after submit retry budget",
        session=session,
        observation=observation,
        submit_attempts=len(INJECT_SUBMIT_RETRY_DELAYS_S),
    )
    return False


async def _wait_for_post_enter_prompt_state(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    turn_started: asyncio.Future[None],
    timeout_s: float,
) -> PromptDeliveryObservation:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        if turn_started.done():
            return PromptDeliveryObservation(PromptDeliveryState.SUBMITTED, "")
        observation = await _observe_prompt_delivery(
            session,
            text,
            active_agent=active_agent,
        )
        observation = _accept_current_live_input(observation)
        if observation.state != PromptDeliveryState.IN_INPUT:
            return observation
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return observation
        await asyncio.sleep(min(INJECT_PROMPT_OBSERVE_INTERVAL_S, remaining))


def _log_prompt_delivery_evidence(
    message: str,
    *,
    session: Session,
    observation: PromptDeliveryObservation,
    submit_attempt: int | None = None,
    submit_attempts: int | None = None,
) -> None:
    normalized_raw_region = _normalize_prompt_delivery_evidence(observation.raw_live_region)
    attempt_text = ""
    if submit_attempt is not None and submit_attempts is not None:
        attempt_text = f" submit_attempt={submit_attempt}/{submit_attempts}"
    elif submit_attempts is not None:
        attempt_text = f" attempts={submit_attempts}"
    raw_has_text = bool(_normalize_prompt_delivery_evidence(observation.raw_live_region).strip())
    raw_has_ansi_or_control = _has_ansi_or_control_bytes(observation.raw_live_region)
    derived_has_text = bool(observation.live_input.strip())
    # Intentionally raw: this path only runs when TeleClaude's own agent-start,
    # restart, or restore stimulus could not be confirmed after paste/enter.
    # The marker-bounded prompt region is the evidence needed to debug why the
    # input detector classified a visible prompt as empty or unsubmitted.
    logger.warning(
        "%s session=%s state=%s%s raw_has_text=%s raw_has_ansi_or_control=%s derived_has_text=%s "
        "live_input_len=%d live_input_sha256=%s live_input=%r "
        "raw_live_region_len=%d raw_live_region_sha256=%s raw_live_region=%r "
        "normalized_raw_live_region_len=%d normalized_raw_live_region_sha256=%s normalized_raw_live_region=%r",
        message,
        session.session_id,
        observation.state.value,
        attempt_text,
        raw_has_text,
        raw_has_ansi_or_control,
        derived_has_text,
        len(observation.live_input),
        _prompt_delivery_evidence_digest(observation.live_input),
        observation.live_input,
        len(observation.raw_live_region),
        _prompt_delivery_evidence_digest(observation.raw_live_region),
        observation.raw_live_region,
        len(normalized_raw_region),
        _prompt_delivery_evidence_digest(normalized_raw_region),
        normalized_raw_region,
    )


def _normalize_prompt_delivery_evidence(text: str) -> str:
    stripped = strip_ansi_codes(text or "")
    return stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")


def _has_ansi_or_control_bytes(text: str) -> bool:
    return any((ord(char) < 32 and char not in "\n\r\t") or char == "\x1b" for char in text or "")


def _prompt_delivery_evidence_digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


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
