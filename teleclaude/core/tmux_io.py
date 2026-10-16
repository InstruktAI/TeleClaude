"""Session-aware tmux I/O routing (tmux only)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from signal import Signals
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AgentName
from teleclaude.core import tmux_bridge
from teleclaude.core.agent_availability import launch_ownership
from teleclaude.core.agent_dispatch import resolve_launch_model
from teleclaude.core.agent_readiness import (
    NoComposerReadinessTimeout,
    PromptDeliveryObservation,
    PromptDeliveryState,
    await_agent_readiness,
    classify_prompt_delivery,
    publish_delivery_no_composer,
)
from teleclaude.core.agents import get_agent_command
from teleclaude.core.db import db
from teleclaude.core.injected_text import (
    InjectedInputAuthority,
    construct_delivered_text,
    prepare_composer_submission,
)
from teleclaude.core.models import Session
from teleclaude.core.runtime_readiness import RuntimeReadiness, RuntimeReadinessKey
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_cleanup import TMUX_SESSION_NAME_UNBOUND, host_pane_name
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_launch_profile import resolve_session_launch_profile
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.voice_assignment import get_voice_env_vars
from teleclaude.runtime.environment import runtime_run_command

logger = get_logger(__name__)

# Interface input keeps the historical append behavior when the composer is
# occupied. Conversation input waits for an empty composer before submission.
INJECT_OCCUPIED_COMPOSER_SEPARATOR = "\n\n"

# Headless-adoption resume gate. The resumed agent must reach its input prompt
# before the triggering payload is sent into the pane — sending on a fixed
# schedule instead races the agent's tty attach and silently drops the payload.
ADOPTION_READINESS_TIMEOUT_S = 60.0
ADOPTION_STABILIZE_QUIET_S = 1.0

# Structured log event names for the adoption readiness gate.
ADOPTION_READINESS_TIMEOUT_EVENT = "adoption_readiness_timeout"
ADOPTION_TEARDOWN_PANE_SURVIVED_EVENT = "adoption_teardown_pane_survived"
ADOPTION_HELD_ON_SCREEN_EVENT = "adoption_held_on_screen_without_composer"

CONVERSATION_REQUIRES_ACTIVE_AGENT_ERROR = "Conversation input requires an active agent"


class UserTurnDeliveryOutcome(StrEnum):
    """Terminal outcomes for structured text delivered to an active composer."""

    SUBMITTED = "submitted"
    APPENDED_UNSUBMITTED = "appended_unsubmitted"
    HELD = "held"
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
    NO_COMPOSER = "no_composer"
    HOST_OPERATION_FAILED = "host_operation_failed"
    EXECUTION_ERROR = "execution_error"


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
        return self.outcome in (
            UserTurnDeliveryOutcome.SUBMITTED,
            UserTurnDeliveryOutcome.APPENDED_UNSUBMITTED,
        )


async def _revive_headless_and_send(
    session: Session,
    text: str,
    *,
    active_agent: str | None,
    authority: InjectedInputAuthority,
    working_dir: str,
    readiness: RuntimeReadiness,
) -> bool | UserTurnDeliveryResult:
    """Create a tmux session for a headless session on the fly and send text to it.

    Mutates session.tmux_session_name in-place so callers (e.g. deliver_inbound)
    can use the updated name for downstream operations like start_polling.
    """
    tmux_name = session.tmux_session_name
    if not tmux_name:
        tmux_name = host_pane_name(session.session_id)

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
    await db.update_session(session.session_id, tmux_session_name=tmux_name)
    await transition_session(
        db,
        session.session_id,
        LifecycleTransition(SessionLifecycleStatus.INITIALIZING, LifecycleTransitionReason.ADOPTION_INITIALIZED),
    )

    if session.active_agent and session.native_session_id:
        launch = (
            await resolve_launch_model(
                session.active_agent,
                session.thinking_mode,
                ownership=launch_ownership(session.role),
                session_id=session.session_id,
            )
            if session.thinking_mode
            else None
        )
        launch_profile = resolve_session_launch_profile(session, session.active_agent)
        resume_cmd = get_agent_command(
            agent=session.active_agent,
            thinking_mode=session.thinking_mode,
            exec=False,
            native_session_id=session.native_session_id,
            profile=launch_profile.profile,
            launch_flags=launch_profile.flags,
            resolved_flags=launch.flags if launch else None,
        )
        runtime_run_id = str(uuid4())
        if not await db.install_runtime_run(session.session_id, runtime_run_id):
            await _teardown_failed_adoption(
                session,
                tmux_name,
                agent_name=session.active_agent,
                timeout_s=ADOPTION_READINESS_TIMEOUT_S,
            )
            return False
        resume_cmd = runtime_run_command(resume_cmd, runtime_run_id)

        readiness_key = RuntimeReadinessKey.ordinary(session.session_id, runtime_run_id)
        ready_future = readiness.register(readiness_key)
        try:
            await tmux_bridge.send_keys_existing_tmux(
                session_name=tmux_name,
                text=resume_cmd,
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
                    readiness=readiness,
                )
            except NoComposerReadinessTimeout:
                # The resumed agent shows a screen other than its composer. Keep
                # its pane bound and the session initializing so the woken parent
                # can see and clear it; the waiting input reaches the agent
                # through this session once a composer appears.
                logger.info(
                    ADOPTION_HELD_ON_SCREEN_EVENT,
                    agent_name=session.active_agent,
                    session_id=session.session_id,
                    tmux_session_name=tmux_name,
                )
                return _no_composer_hold()
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
            readiness.release(readiness_key, ready_future)

    if active_agent:
        delivery_result = await inject_user_turn(
            session,
            text,
            active_agent=active_agent,
            authority=authority,
            readiness=readiness,
        )
        return delivery_result
    return await tmux_bridge.send_keys_existing_tmux(session_name=tmux_name, text=text)


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
    await db.update_session(session.session_id, tmux_session_name=TMUX_SESSION_NAME_UNBOUND)
    await transition_session(
        db,
        session.session_id,
        LifecycleTransition(SessionLifecycleStatus.HEADLESS, LifecycleTransitionReason.HEADLESS_RESTORED),
    )


async def _send_to_tmux(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    authority: InjectedInputAuthority,
    working_dir: str,
    readiness: RuntimeReadiness,
) -> bool | UserTurnDeliveryResult:
    tmux_name = session.tmux_session_name
    if tmux_name and await tmux_bridge.session_exists(tmux_name, log_missing=False):
        if authority is InjectedInputAuthority.CONVERSATION and active_agent is not None:
            return await inject_user_turn(
                session,
                text,
                active_agent=active_agent,
                authority=authority,
                readiness=readiness,
            )
        return await tmux_bridge.send_keys_existing_tmux(
            session_name=tmux_name,
            text=text,
        )

    if session.lifecycle_status == "headless":
        return await _revive_headless_and_send(
            session,
            text,
            active_agent=active_agent,
            authority=authority,
            working_dir=working_dir,
            readiness=readiness,
        )

    logger.warning(
        "tmux session unavailable for session %s; maintenance healing required",
        session.session_id,
    )
    return False


async def route_text(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    authority: InjectedInputAuthority,
    working_dir: str,
    readiness: RuntimeReadiness,
) -> bool | UserTurnDeliveryResult:
    """Route text input to the appropriate tmux session and return the delivery decision as made.

    A raw pane write answers with a bool; delivery into an agent composer answers
    with its typed result, including a hold, which is a wait and not a failure.
    """
    text_sha = hashlib.sha256(text.encode()).hexdigest()[:12]
    logger.info(
        "process_text_write",
        session_id=session.session_id,
        active_agent=active_agent,
        text_len=len(text),
        text_sha=text_sha,
    )
    result = await _send_to_tmux(
        session,
        text,
        active_agent=active_agent,
        authority=authority,
        working_dir=working_dir,
        readiness=readiness,
    )
    write_failed = (
        result.outcome is UserTurnDeliveryOutcome.FAILED if isinstance(result, UserTurnDeliveryResult) else not result
    )
    if write_failed:
        logger.warning(
            "process_text_write_failed",
            session_id=session.session_id,
            text_len=len(text),
            text_sha=text_sha,
        )
    return result


async def process_text(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    authority: InjectedInputAuthority,
    working_dir: str,
    readiness: RuntimeReadiness,
) -> bool | UserTurnDeliveryResult:
    """Route text input; interface authority collapses a typed delivery result to whether it succeeded."""
    result = await route_text(
        session,
        text,
        active_agent=active_agent,
        authority=authority,
        working_dir=working_dir,
        readiness=readiness,
    )
    if authority is InjectedInputAuthority.INTERFACE and isinstance(result, UserTurnDeliveryResult):
        return result.succeeded
    return result


async def inject_user_turn(
    session: Session,
    text: str,
    *,
    active_agent: str | None = None,
    authority: InjectedInputAuthority,
    readiness: RuntimeReadiness,
) -> UserTurnDeliveryResult:
    """Deliver text without allowing platform Enter to submit occupied input."""
    delivered_text = text
    conversation_agent: AgentName | None = None
    if authority is InjectedInputAuthority.CONVERSATION:
        if active_agent is None:
            raise ValueError(CONVERSATION_REQUIRES_ACTIVE_AGENT_ERROR)
        conversation_agent = AgentName.from_str(active_agent)
        delivered_text = construct_delivered_text(text, authority, conversation_agent)
    tmux_name = session.tmux_session_name or ""
    observation = await tmux_bridge.observe_visible_pane(tmux_name)
    if observation is None:
        return _failed_delivery(
            UserTurnDeliveryReason.HOST_OPERATION_FAILED,
            stage=UserTurnDeliveryStage.OBSERVATION,
        )
    before_delivery = classify_prompt_delivery(observation, active_agent)
    _log_prompt_observation(
        "inject_user_turn: pre-delivery observation",
        session=session,
        observation=before_delivery,
    )
    if before_delivery.state is PromptDeliveryState.AMBIGUOUS:
        # The pane shows a screen other than the composer: nothing is pasted or
        # pressed into it, for any authority, and the input waits as a hold.
        await publish_delivery_no_composer(session.session_id, observation.text, readiness)
        return _no_composer_hold()

    if before_delivery.state is PromptDeliveryState.OCCUPIED:
        if authority is InjectedInputAuthority.CONVERSATION:
            return UserTurnDeliveryResult(
                UserTurnDeliveryOutcome.HELD,
                UserTurnDeliveryStage.OBSERVATION,
                UserTurnDeliveryReason.COMPOSER_OCCUPIED,
                paste_performed=False,
                platform_enter_sent=False,
                existing_input_preserved=True,
            )
        pasted = await tmux_bridge.paste_text_existing_tmux(
            session_name=tmux_name,
            text=f"{INJECT_OCCUPIED_COMPOSER_SEPARATOR}{text}",
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

    submission_text = delivered_text
    if conversation_agent is not None:
        submission_text = prepare_composer_submission(delivered_text, conversation_agent)
    submitted = await tmux_bridge.send_keys_existing_tmux(
        session_name=tmux_name,
        text=submission_text,
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


def _no_composer_hold() -> UserTurnDeliveryResult:
    """Build the hold for input that met a screen with no composer; nothing was sent."""
    return UserTurnDeliveryResult(
        UserTurnDeliveryOutcome.HELD,
        UserTurnDeliveryStage.OBSERVATION,
        UserTurnDeliveryReason.NO_COMPOSER,
        paste_performed=False,
        platform_enter_sent=False,
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
