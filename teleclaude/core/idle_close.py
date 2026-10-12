"""The conversation idle cycle: compact an idle continuing conversation, then close it.

A continuing conversation (a session at a help desk, or a session created at a person's
assistant endpoint through conversation entry) is closed only to spare resources while its
person is away. After it has had no input for the idle threshold, the cycle resumes its native
transcript in a temporary runtime, submits the agent's declared compaction command, and closes
only after the provider confirms compaction. Returning input abandons maintenance and resumes
the same session under its ordinary launch profile.

The cycle never touches a session that is not a continuing conversation, and never records the
compaction command as conversation input: the idle clock is the session's last input.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.agent_registry import AgentName
from teleclaude.config.machine import config
from teleclaude.core import tmux_bridge
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.agent_readiness import AGENT_START_STABILIZE_QUIET_S
from teleclaude.core.agent_startup_delivery import (
    AgentStartupDeliveryMode,
    deliver_startup_message,
)
from teleclaude.core.agents import get_compaction_agent_command
from teleclaude.core.conversation_close import CloseOutcome, NotDueReason, close_when_settled, unsettled_reason
from teleclaude.core.db import db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import AgentReadyContext, TeleClaudeEvents
from teleclaude.core.injected_text import InjectedInputAuthority
from teleclaude.core.models import Session
from teleclaude.core.session_bootstrap import ensure_tmux_with_identity
from teleclaude.core.session_compaction import (
    CompactionAttempt,
    CompactionStage,
    SessionCompactionOwner,
    last_input_at,
    launch_context_for_attempt,
    session_compaction_owner,
)
from teleclaude.core.session_ended import is_continuing_conversation
from teleclaude.core.session_environment import build_agent_session_environment
from teleclaude.core.session_idle_compaction import (
    CONVERSATION_IDLE_THRESHOLD,
    compaction_completed,
)
from teleclaude.core.session_revival import session_is_resumable
from teleclaude.core.session_runtime_gate import (
    RuntimeMutationInProgress,
    clear_relaunch_awaiting_readiness,
    mark_relaunch_awaiting_readiness,
    session_runtime_owner,
)
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.core.session_utils import resolve_working_dir
from teleclaude.core.tmux_io import UserTurnDeliveryOutcome
from teleclaude.core.voice_assignment import get_voice_env_vars

logger = get_logger(__name__)

# The cadence is well under the threshold, so a session closes within one cadence of falling due.
IDLE_CYCLE_INTERVAL_S: Final[float] = 300.0
IDLE_CLOSE_REASON: Final[str] = "idle_close"

_CYCLE_PASS_FAILED_EVENT = "idle_cycle_pass_failed"
_SESSION_FAILED_EVENT = "idle_cycle_session_failed"
_SESSION_BUSY_EVENT = "idle_cycle_session_busy"
_COMPACTION_REQUESTED_EVENT = "idle_cycle_compaction_requested"
_NOT_DUE_EVENT = "idle_cycle_not_due"
_CLOSED_EVENT = "idle_cycle_closed"
_CLOSE_CALLED_OFF_EVENT = "idle_cycle_close_called_off"
_CLOSE_NOT_PERFORMED_EVENT = "idle_cycle_close_not_performed"
_COMPACTION_LAUNCH_FAILED_EVENT = "idle_cycle_compaction_launch_failed"
_COMPACTION_LAUNCH_NOT_STARTED = "temporary compaction runtime could not be started"
_COMPACTION_IDENTITY_MISSING = "conversation session has no recorded agent or native session"
_COMPACTION_PANE_MISSING = "conversation session has no recorded tmux runtime"
_COMPACTION_PANE_SHUTDOWN_FAILED = "conversation runtime could not be shut down for compaction"
_COMPACTION_READY_TIMEOUT_S: Final[float] = config.daemon.agent_prompt_ready_timeout_s


class IdleStep(StrEnum):
    """The two steps of a session's idle cycle."""

    COMPACTION = "compaction"
    CLOSE = "close"


def compaction_command(session: Session) -> str | None:
    """The command that compacts the session's agent, or ``None`` when its agent declares none."""
    if not session.active_agent:
        return None
    try:
        return AgentName.from_str(session.active_agent).compaction_command
    except ValueError:
        return None


async def _not_due_reason(session: Session, now: datetime, *, require_idle_status: bool) -> NotDueReason | None:
    """Why the session is not due, or ``None`` when it is.

    A session is due once its person has been away for the idle threshold and its accepted work
    has settled (``unsettled_reason``).
    """
    if session.closed_at is not None:
        return NotDueReason.NOT_ACTIVE
    if not session_is_resumable(session):
        return NotDueReason.NOT_RESUMABLE
    last_input = last_input_at(session)
    if last_input is None or now - last_input < CONVERSATION_IDLE_THRESHOLD:
        return NotDueReason.RECENT_INPUT
    return await unsettled_reason(session, require_idle_status=require_idle_status)


async def _launch_temporary_compaction_runtime(
    session: Session,
    agent: str,
    tmux_session_name: str,
    attempt: CompactionAttempt,
    command: str,
) -> None:
    """Resume the recorded native transcript and submit its declared command."""
    launch_context = launch_context_for_attempt(attempt)
    loop = asyncio.get_running_loop()
    ready_future: asyncio.Future[None] = loop.create_future()

    async def _on_ready(_event_type: str, context: AgentReadyContext) -> None:
        if (
            context.session_id == session.session_id
            and context.compaction_launch_context == launch_context
            and not ready_future.done()
        ):
            ready_future.set_result(None)

    ready_handler = event_bus.subscribe(TeleClaudeEvents.AGENT_READY, _on_ready)
    mark_relaunch_awaiting_readiness(session.session_id)
    try:
        voice = await db.get_voice(session.session_id)
        env_vars = build_agent_session_environment(
            project_path=session.project_path,
            platform_env=get_voice_env_vars(voice) if voice else {},
        )
        working_dir = resolve_working_dir(session.project_path, session.subdir)
        if await tmux_bridge.session_exists(tmux_session_name, log_missing=False):
            if not await tmux_bridge.kill_session(tmux_session_name):
                raise RuntimeError(_COMPACTION_PANE_SHUTDOWN_FAILED)
        if not await ensure_tmux_with_identity(session, tmux_session_name, working_dir, env_vars):
            raise RuntimeError(_COMPACTION_LAUNCH_NOT_STARTED)
        launch_command = get_compaction_agent_command(session, agent, launch_context)
        if not await tmux_bridge.send_keys_existing_tmux(session_name=tmux_session_name, text=launch_command):
            raise RuntimeError(_COMPACTION_LAUNCH_NOT_STARTED)
        delivery = await deliver_startup_message(
            session=session,
            agent_name=agent,
            message=command,
            authority=InjectedInputAuthority.INTERFACE,
            ready_future=ready_future,
            quiet_s=AGENT_START_STABILIZE_QUIET_S,
            timeout_s=_COMPACTION_READY_TIMEOUT_S,
            delivery_mode=AgentStartupDeliveryMode.FRESH_START,
        )
        if delivery.outcome is not UserTurnDeliveryOutcome.SUBMITTED:
            raise RuntimeError(_COMPACTION_LAUNCH_NOT_STARTED)
    finally:
        event_bus.unsubscribe(TeleClaudeEvents.AGENT_READY, ready_handler)
        clear_relaunch_awaiting_readiness(session.session_id)


async def _due_to_close(session: Session) -> NotDueReason | None:
    """Why the session may not be closed now, or ``None`` when its completed compaction makes it due."""
    reason = await _not_due_reason(session, datetime.now(UTC), require_idle_status=False)
    if reason is not None:
        logger.info(_NOT_DUE_EVENT, session_id=session.session_id, step=IdleStep.CLOSE, reason=reason.value)
        return reason
    if not compaction_completed(session):
        return NotDueReason.COMPACTION_NOT_COMPLETED
    return None


async def close_completed_conversation(
    session: Session,
    client: AdapterClient,
    compaction_owner: SessionCompactionOwner,
) -> None:
    """Close a session whose compaction completed, unless the conversation is going on.

    Input queued for the session, or arriving while the close starts, calls the close
    off. The close is stamped before the session leaves ``ACTIVE``, so input that still
    reaches the session afterwards finds an idle-closed conversation: its delivery waits
    for the close to end and resumes the same session (``deliver_inbound``), and the
    conversation seam does the same for a turn it routes to the closing session.
    """
    session_id = session.session_id

    async def _compaction_completed(fresh: Session) -> bool:
        return compaction_owner.active_attempt(fresh) is not None and compaction_completed(fresh)

    async def _settle_compaction(fresh: Session) -> None:
        attempt = compaction_owner.active_attempt(fresh)
        if attempt is not None:
            await compaction_owner.settle(fresh, attempt.attempt_id)
        await db.update_session(session_id, idle_compaction_completed_at=None)

    admission = await close_when_settled(
        session_id,
        client,
        close_reason=IDLE_CLOSE_REASON,
        blocker=_due_to_close,
        mark_idle_closed=True,
        admit=_compaction_completed,
        after_closed=_settle_compaction,
    )
    if admission.outcome is CloseOutcome.CALLED_OFF and admission.reason is not None:
        logger.info(_CLOSE_CALLED_OFF_EVENT, session_id=session_id, reason=admission.reason.value)
    elif admission.outcome is CloseOutcome.NOT_PERFORMED:
        logger.warning(_CLOSE_NOT_PERFORMED_EVENT, session_id=session_id)
    elif admission.outcome is CloseOutcome.CLOSED:
        logger.info(_CLOSED_EVENT, session_id=session_id, agent=session.active_agent)


class ConversationIdleCycle:
    """Compacts and closes the continuing conversations that have been idle past the threshold."""

    def __init__(self, client: AdapterClient, compaction_owner: SessionCompactionOwner | None = None) -> None:
        self._client = client
        self._compaction_owner = compaction_owner or session_compaction_owner

    async def run(self) -> None:
        """Run the cycle forever."""
        while True:
            try:
                await self.run_pass()
                await asyncio.sleep(IDLE_CYCLE_INTERVAL_S)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(_CYCLE_PASS_FAILED_EVENT, error=str(exc), exc_info=True)
                await asyncio.sleep(IDLE_CYCLE_INTERVAL_S)

    async def run_pass(self) -> None:
        """Advance every active continuing conversation whose agent declares a compaction command."""
        for session in await db.get_active_sessions():
            command = compaction_command(session)
            if command is None or not is_continuing_conversation(session):
                continue
            try:
                await self._advance(session, command)
            except RuntimeMutationInProgress:
                logger.info(_SESSION_BUSY_EVENT, session_id=session.session_id)
            except Exception as exc:
                logger.error(_SESSION_FAILED_EVENT, session_id=session.session_id, error=str(exc), exc_info=True)

    async def _advance(self, session: Session, command: str) -> None:
        """Take the one step the session's compaction stamps call for."""
        if self._compaction_owner.active_attempt(session) is not None:
            if compaction_completed(session):
                await close_completed_conversation(session, self._client, self._compaction_owner)
            return
        await self._request_compaction(session, command)

    async def _request_compaction(self, session: Session, command: str) -> None:
        """Replace the ordinary pane temporarily, then submit the declared command."""
        session_id = session.session_id
        attempt: CompactionAttempt | None = None
        launch_error: Exception | None = None
        try:
            async with session_runtime_owner(session_id):
                fresh = await db.get_session(session_id)
                if fresh is None or fresh.lifecycle_status != SessionLifecycleStatus.ACTIVE:
                    return
                reason = await _not_due_reason(fresh, datetime.now(UTC), require_idle_status=True)
                if reason is not None:
                    logger.info(_NOT_DUE_EVENT, session_id=session_id, step=IdleStep.COMPACTION, reason=reason.value)
                    return
                active_agent = fresh.active_agent
                native_session_id = fresh.native_session_id
                tmux_session_name = fresh.tmux_session_name
                if not active_agent or not native_session_id:
                    raise ValueError(_COMPACTION_IDENTITY_MISSING)
                if not tmux_session_name:
                    raise ValueError(_COMPACTION_PANE_MISSING)

                attempt = await self._compaction_owner.begin_attempt(fresh, native_session_id)
                await db.update_session(session_id, idle_compaction_completed_at=None)
                fresh = await db.get_session(session_id)
                if fresh is None:
                    raise RuntimeError(_COMPACTION_LAUNCH_NOT_STARTED)
                await _launch_temporary_compaction_runtime(
                    fresh,
                    active_agent,
                    tmux_session_name,
                    attempt,
                    command,
                )
                current = await db.get_session(session_id)
                if current is not None:
                    await self._compaction_owner.transition(current, attempt.attempt_id, CompactionStage.RUNNING)
                logger.info(_COMPACTION_REQUESTED_EVENT, session_id=session_id, agent=active_agent)
        except RuntimeMutationInProgress:
            raise
        except (OSError, RuntimeError, SQLAlchemyError, TimeoutError, ValueError) as exc:
            launch_error = exc

        if launch_error is None:
            return
        if attempt is None:
            raise launch_error

        restored = await self._compaction_owner.restore_ordinary(session_id, attempt.attempt_id)
        logger.error(
            _COMPACTION_LAUNCH_FAILED_EVENT,
            session_id=session_id,
            attempt_id=attempt.attempt_id,
            error=str(launch_error),
            restored=restored,
        )
