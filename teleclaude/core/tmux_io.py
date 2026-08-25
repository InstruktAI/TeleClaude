"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from signal import Signals

from instrukt_ai_logging import get_logger

from teleclaude.core import tmux_bridge
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_prompt_state import (
    PromptDeliveryObservation,
    PromptDeliveryState,
    classify_prompt_delivery,
)
from teleclaude.core.agent_readiness import await_agent_readiness
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import (
    SessionLifecycleContext,
    TeleClaudeEvents,
)
from teleclaude.core.models import Session
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.voice_assignment import get_voice_env_vars

logger = get_logger(__name__)

# Prompt-state user-turn delivery makes exactly one pre-delivery decision.
# Empty composers use the normal paste-and-submit primitive; occupied composers
# receive an unsubmitted append so platform delivery cannot submit human input.
INJECT_OCCUPIED_COMPOSER_SEPARATOR = "\n\n"

# Headless-adoption resume gate. The resumed agent must reach its input prompt
# before the triggering payload is sent into the pane — sending on a fixed
# schedule instead races the agent's tty attach and silently drops the payload.
ADOPTION_READINESS_TIMEOUT_S = 60.0
ADOPTION_STABILIZE_QUIET_S = 1.0

# Structured log event names for the adoption readiness gate.
ADOPTION_READINESS_TIMEOUT_EVENT = "adoption_readiness_timeout"
ADOPTION_TEARDOWN_PANE_SURVIVED_EVENT = "adoption_teardown_pane_survived"

# Sentinel for an unbound tmux pane, named so callers never inline the literal.
TMUX_SESSION_NAME_UNBOUND = ""


class _AdoptionLifecycleStatus(StrEnum):
    """The Session.lifecycle_status values this module's headless-adoption gate
    transitions through — not the full session lifecycle vocabulary, which has
    additional values (e.g. "closing", "closed") this module never assigns.
    """

    HEADLESS = "headless"
    INITIALIZING = "initializing"
    ACTIVE = "active"


class UserTurnDeliveryOutcome(StrEnum):
    """Terminal outcomes for structured text delivered to an active composer."""

    SUBMITTED = "submitted"
    APPENDED_UNSUBMITTED = "appended_unsubmitted"
    FAILED = "failed"


class UserTurnDeliveryStage(StrEnum):
    """The prompt-delivery stage that reached its terminal decision."""

    OBSERVATION = "observation"
    PASTE = "paste"
    APPEND = "append"
    CONFIRMATION = "confirmation"
    SUBMIT = "submit"


class UserTurnDeliveryReason(StrEnum):
    """Closed reasons for a structured text delivery outcome."""

    COMPOSER_EMPTY = "composer_empty"
    COMPOSER_OCCUPIED = "composer_occupied"
    OBSERVATION_AMBIGUOUS = "observation_ambiguous"
    HOST_OPERATION_FAILED = "host_operation_failed"
    EXECUTION_ERROR = "execution_error"
    FRESH_START = "fresh_start"


@dataclass(frozen=True)
class UserTurnDeliveryResult:
    """The committed delivery decision and its host-pane effects."""

    outcome: UserTurnDeliveryOutcome
    stage: UserTurnDeliveryStage
    reason: UserTurnDeliveryReason
    paste_performed: bool
    platform_enter_sent: bool
    existing_input_preserved: bool

    @property
    def succeeded(self) -> bool:
        """Whether the inbound row can be marked delivered."""
        return self.outcome is not UserTurnDeliveryOutcome.FAILED


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

    # Bind the pane in a held state before gating on readiness. Update in-place
    # so callers (e.g. deliver_inbound) see the new tmux_session_name
    # immediately, and persist "initializing" so deliver_inbound's startup gate
    # holds any other inbound message for this session until the resumed agent
    # is confirmed ready or the adoption is torn down below.
    session.tmux_session_name = tmux_name
    await db.update_session(
        session.session_id,
        lifecycle_status=_AdoptionLifecycleStatus.INITIALIZING,
        tmux_session_name=tmux_name,
    )

    if session.active_agent and session.native_session_id:
        launch = (
            await resolve_launch_model(session.active_agent, session.thinking_mode, session_id=session.session_id)
            if session.thinking_mode
            else None
        )
        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
            resolved_flags=launch.flags if launch else None,
        )

        # Subscribe BEFORE issuing the resume command — the agent's SessionStart
        # hook can race the send and emit AGENT_READY before this coroutine
        # resumes; subscribing after the send loses the event (event_bus does
        # not replay).
        loop = asyncio.get_running_loop()
        ready_future: asyncio.Future[None] = loop.create_future()

        async def _on_ready(_event_type: str, ctx: SessionLifecycleContext) -> None:
            if ctx.session_id == session.session_id and not ready_future.done():
                ready_future.set_result(None)

        ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)
        try:
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
            try:
                await await_agent_readiness(
                    agent_name=session.active_agent,
                    session=session,
                    session_id=session.session_id,
                    ready_future=ready_future,
                    quiet_s=ADOPTION_STABILIZE_QUIET_S,
                    timeout_s=ADOPTION_READINESS_TIMEOUT_S,
                )
            except TimeoutError:
                logger.warning(
                    ADOPTION_READINESS_TIMEOUT_EVENT,
                    agent_name=session.active_agent,
                    session_id=session.session_id,
                    tmux_session_name=tmux_name,
                    timeout_s=ADOPTION_READINESS_TIMEOUT_S,
                )
                await _teardown_failed_adoption(
                    session,
                    tmux_name,
                    agent_name=session.active_agent,
                    timeout_s=ADOPTION_READINESS_TIMEOUT_S,
                )
                return False
        finally:
            event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)

    await db.update_session(session.session_id, lifecycle_status=_AdoptionLifecycleStatus.ACTIVE)

    return await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=text,
        active_agent=active_agent,
    )


async def _teardown_failed_adoption(
    session: Session,
    tmux_name: str,
    *,
    agent_name: str | None,
    timeout_s: float,
) -> None:
    """Undo a headless adoption whose resumed agent never reached readiness.

    ensure_tmux_session is idempotent on an existing pane name, so reverting
    the durable state to "headless" while the pane is still alive would let a
    retry accept that pane and paste a second resume command into it. The
    reset is therefore conditional on session_exists confirming the pane is
    actually gone, never on the kill attempt alone.
    """
    await tmux_bridge.kill_session(tmux_name)
    if await tmux_bridge.session_exists(tmux_name, log_missing=False):
        logger.error(
            ADOPTION_TEARDOWN_PANE_SURVIVED_EVENT,
            agent_name=agent_name,
            session_id=session.session_id,
            tmux_session_name=tmux_name,
            timeout_s=timeout_s,
        )
        return

    session.tmux_session_name = TMUX_SESSION_NAME_UNBOUND
    await db.update_session(
        session.session_id,
        lifecycle_status=_AdoptionLifecycleStatus.HEADLESS,
        tmux_session_name=TMUX_SESSION_NAME_UNBOUND,
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
    text_sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    logger.info(
        "process_text_write",
        session_id=session.session_id,
        active_agent=active_agent,
        text_len=len(text),
        text_sha=text_sha,
    )
    success = await _send_to_tmux(
        session,
        text,
        active_agent=active_agent,
        working_dir=working_dir,
    )
    if not success:
        logger.warning(
            "process_text_write_failed",
            session_id=session.session_id,
            text_len=len(text),
            text_sha=text_sha,
        )
    return success


async def inject_user_turn(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
) -> UserTurnDeliveryResult:
    """Deliver text without allowing platform Enter to submit occupied input."""
    tmux_name = session.tmux_session_name or ""
    before_delivery = await _observe_prompt_delivery(session, active_agent=active_agent)
    _log_prompt_observation(
        "inject_user_turn: pre-delivery observation",
        session=session,
        observation=before_delivery,
    )
    if before_delivery.state is PromptDeliveryState.AMBIGUOUS:
        return _failed_delivery(
            UserTurnDeliveryReason.OBSERVATION_AMBIGUOUS,
            stage=UserTurnDeliveryStage.OBSERVATION,
        )

    if before_delivery.state is PromptDeliveryState.OCCUPIED:
        pasted = await tmux_bridge.paste_text_existing_tmux(
            session_name=tmux_name,
            text=f"{INJECT_OCCUPIED_COMPOSER_SEPARATOR}{text}",
            active_agent=active_agent,
        )
        if not pasted:
            return _failed_delivery(UserTurnDeliveryReason.HOST_OPERATION_FAILED, stage=UserTurnDeliveryStage.PASTE)
        return UserTurnDeliveryResult(
            UserTurnDeliveryOutcome.APPENDED_UNSUBMITTED,
            UserTurnDeliveryStage.APPEND,
            UserTurnDeliveryReason.COMPOSER_OCCUPIED,
            paste_performed=True,
            platform_enter_sent=False,
            existing_input_preserved=True,
        )

    submitted = await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=text,
        active_agent=active_agent,
    )
    if not submitted:
        return _failed_delivery(UserTurnDeliveryReason.HOST_OPERATION_FAILED, stage=UserTurnDeliveryStage.SUBMIT)
    return UserTurnDeliveryResult(
        UserTurnDeliveryOutcome.SUBMITTED,
        UserTurnDeliveryStage.SUBMIT,
        UserTurnDeliveryReason.COMPOSER_EMPTY,
        paste_performed=True,
        platform_enter_sent=True,
        existing_input_preserved=False,
    )


async def submit_fresh_start_turn(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
) -> UserTurnDeliveryResult:
    """Submit a newly created session's initial platform turn without observation."""
    submitted = await tmux_bridge.send_keys_existing_tmux(
        session_name=session.tmux_session_name or TMUX_SESSION_NAME_UNBOUND,
        text=text,
        active_agent=active_agent,
    )
    if not submitted:
        return _failed_delivery(UserTurnDeliveryReason.HOST_OPERATION_FAILED, stage=UserTurnDeliveryStage.SUBMIT)
    return UserTurnDeliveryResult(
        UserTurnDeliveryOutcome.SUBMITTED,
        UserTurnDeliveryStage.SUBMIT,
        UserTurnDeliveryReason.FRESH_START,
        paste_performed=True,
        platform_enter_sent=True,
        existing_input_preserved=False,
    )


def _failed_delivery(
    reason: UserTurnDeliveryReason,
    *,
    stage: UserTurnDeliveryStage = UserTurnDeliveryStage.CONFIRMATION,
    paste_performed: bool = False,
    platform_enter_sent: bool = False,
) -> UserTurnDeliveryResult:
    """Build an explicit retryable delivery failure."""
    return UserTurnDeliveryResult(
        UserTurnDeliveryOutcome.FAILED,
        stage,
        reason,
        paste_performed=paste_performed,
        platform_enter_sent=platform_enter_sent,
        existing_input_preserved=False,
    )


async def _observe_prompt_delivery(
    session: Session,
    *,
    active_agent: str | None,
) -> PromptDeliveryObservation:
    output = await tmux_bridge.capture_pane(session.tmux_session_name)
    return classify_prompt_delivery(output, active_agent)


def _log_prompt_observation(
    message: str,
    *,
    session: Session,
    observation: PromptDeliveryObservation,
) -> None:
    """Log the content-independent pre-delivery occupancy decision."""
    logger.trace(
        "%s session=%s state=%s",
        message,
        session.session_id,
        observation.state.value,
    )


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


async def wait_for_shell_ready(
    session: Session,
    *,
    timeout_s: float = 8.0,
    poll_interval_s: float = 0.2,
) -> bool:
    """Wait until the session's tmux pane has a ready shell."""
    return await tmux_bridge.wait_for_shell_ready(
        session.tmux_session_name,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )
