"""The conversation idle cycle: compact an idle conversation session's agent, then close the session.

A conversation session (a session at a help desk, or a person's own session in their
home) is closed only to spare resources while its person is away. After it has had no
input for the idle threshold, the cycle types the agent's own compaction command, waits
for the agent to report the compaction complete, and then closes the session. The
person's next message or re-entry revives the same session.

The cycle never touches a session that is not a conversation, and never records the
compaction as input: the idle clock is the session's last input.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import AgentName
from teleclaude.core import tmux_io
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core.db import db
from teleclaude.core.injected_text import InjectedInputAuthority
from teleclaude.core.models import RelayStatus, Session
from teleclaude.core.session_cleanup import terminate_session
from teleclaude.core.session_ended import is_conversation_session
from teleclaude.core.session_idle_compaction import (
    CONVERSATION_IDLE_THRESHOLD,
    compaction_completed,
    last_input_at,
    live_compaction_request,
)
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_revival import session_is_resumable
from teleclaude.core.session_runtime_gate import RuntimeMutationInProgress, session_runtime_owner
from teleclaude.core.session_status import AgentStatusValue, SessionLifecycleStatus, is_agent_turn_running
from teleclaude.core.session_utils import resolve_working_dir

logger = get_logger(__name__)

# The cadence is well under the threshold, so a session closes within one cadence of falling due.
IDLE_CYCLE_INTERVAL_S: Final[float] = 300.0
IDLE_CLOSE_REASON: Final[str] = "idle_close"

_CYCLE_PASS_FAILED_EVENT = "idle_cycle_pass_failed"
_SESSION_FAILED_EVENT = "idle_cycle_session_failed"
_SESSION_BUSY_EVENT = "idle_cycle_session_busy"
_COMPACTION_REQUESTED_EVENT = "idle_cycle_compaction_requested"
_COMPACTION_NOT_TYPED_EVENT = "idle_cycle_compaction_not_typed"
_NOT_DUE_EVENT = "idle_cycle_not_due"
_CLOSED_EVENT = "idle_cycle_closed"
_CLOSE_CALLED_OFF_EVENT = "idle_cycle_close_called_off"
_CLOSE_NOT_PERFORMED_EVENT = "idle_cycle_close_not_performed"


class IdleStep(StrEnum):
    """The two steps of a session's idle cycle."""

    COMPACTION = "compaction"
    CLOSE = "close"


class NotDueReason(StrEnum):
    """Why a conversation session is not due for the next step of its idle cycle."""

    NOT_ACTIVE = "not_active"
    NOT_RESUMABLE = "not_resumable"
    RECENT_INPUT = "recent_input"
    RELAY_ACTIVE = "relay_active"
    TURN_RUNNING = "turn_running"
    AGENT_NOT_IDLE = "agent_not_idle"
    INPUT_QUEUED = "input_queued"
    CONTROL_PENDING = "control_pending"
    COMPACTION_NOT_COMPLETED = "compaction_not_completed"


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

    The agent's idle status is required to ask for a compaction and not to close
    afterwards, because the compaction itself moves the status.
    """
    if session.closed_at is not None:
        return NotDueReason.NOT_ACTIVE
    if not session_is_resumable(session):
        return NotDueReason.NOT_RESUMABLE
    last_input = last_input_at(session)
    if last_input is None or now - last_input < CONVERSATION_IDLE_THRESHOLD:
        return NotDueReason.RECENT_INPUT
    if session.relay_status == RelayStatus.ACTIVE:
        return NotDueReason.RELAY_ACTIVE
    if is_agent_turn_running(
        last_input_at=session.last_message_sent_at,
        last_agent_stop_at=session.last_agent_stop_at,
        last_agent_idle_at=session.last_agent_idle_at,
    ):
        return NotDueReason.TURN_RUNNING
    if require_idle_status and session.agent_status is not AgentStatusValue.IDLE:
        return NotDueReason.AGENT_NOT_IDLE
    if await db.has_queued_inbound(session.session_id):
        return NotDueReason.INPUT_QUEUED
    if await db.count_pending_control_payloads(session_id=session.session_id):
        return NotDueReason.CONTROL_PENDING
    return None


class ConversationIdleCycle:
    """Compacts and closes the conversation sessions that have been idle past the threshold."""

    def __init__(self, client: AdapterClient) -> None:
        self._client = client

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
        """Advance every active conversation session whose agent declares a compaction command."""
        for session in await db.get_active_sessions():
            command = compaction_command(session)
            if command is None or not is_conversation_session(session):
                continue
            try:
                await self._advance(session, command)
            except RuntimeMutationInProgress:
                logger.info(_SESSION_BUSY_EVENT, session_id=session.session_id)
            except Exception as exc:
                logger.error(_SESSION_FAILED_EVENT, session_id=session.session_id, error=str(exc), exc_info=True)

    async def _advance(self, session: Session, command: str) -> None:
        """Take the one step the session's compaction stamps call for."""
        if compaction_completed(session):
            await self._close(session)
            return
        requested = live_compaction_request(session)
        if requested is not None and datetime.now(UTC) - requested < CONVERSATION_IDLE_THRESHOLD:
            return
        await self._request_compaction(session, command)

    async def _request_compaction(self, session: Session, command: str) -> None:
        """Type the agent's compaction command, as input that is not recorded as the person's.

        The runtime owner is held from the last check to the stamp, so input being
        delivered stops the pass. The request is stamped before the command is typed,
        so a completion can never be observed ahead of its request.
        """
        session_id = session.session_id
        async with session_runtime_owner(session_id):
            fresh = await db.get_session(session_id)
            if fresh is None or fresh.lifecycle_status != SessionLifecycleStatus.ACTIVE:
                return
            reason = await _not_due_reason(fresh, datetime.now(UTC), require_idle_status=True)
            if reason is not None:
                logger.info(_NOT_DUE_EVENT, session_id=session_id, step=IdleStep.COMPACTION, reason=reason.value)
                return
            await db.update_session(session_id, idle_compaction_requested_at=datetime.now(UTC).isoformat())
            typed = await tmux_io.process_text(
                fresh,
                command,
                active_agent=fresh.active_agent,
                authority=InjectedInputAuthority.INTERFACE,
                working_dir=resolve_working_dir(fresh.project_path, fresh.subdir),
            )
            if not typed:
                await db.update_session(session_id, idle_compaction_requested_at=None)
                logger.warning(_COMPACTION_NOT_TYPED_EVENT, session_id=session_id)
                return
            logger.info(_COMPACTION_REQUESTED_EVENT, session_id=session_id, agent=fresh.active_agent)

    async def _close(self, session: Session) -> None:
        """Close a session whose compaction completed, unless the conversation is going on.

        Input queued for the session, or arriving while the close starts, calls the close
        off. The close is stamped before the session leaves ``ACTIVE``, so input that still
        reaches the session afterwards finds an idle-closed conversation: its delivery waits
        for the close to end and resumes the same session (``deliver_inbound``), and the
        conversation seam does the same for a turn it routes to the closing session.
        """
        session_id = session.session_id
        async with session_runtime_owner(session_id):
            fresh = await db.get_session(session_id)
            if fresh is None or fresh.lifecycle_status != SessionLifecycleStatus.ACTIVE:
                return
            if await self._due_to_close(fresh) is not None:
                return
            await db.update_session(session_id, idle_closed_at=datetime.now(UTC).isoformat())
            await transition_session(
                db,
                session_id,
                LifecycleTransition(SessionLifecycleStatus.CLOSING, LifecycleTransitionReason.CLOSE_STARTED),
            )
            started = await db.get_session(session_id)
            reason = None if started is None else await self._due_to_close(started)
            if reason is not None:
                await transition_session(
                    db,
                    session_id,
                    LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.CLOSE_FAILED),
                )
                await db.update_session(session_id, idle_closed_at=None)
                logger.info(_CLOSE_CALLED_OFF_EVENT, session_id=session_id, reason=reason.value)
                return
            terminated = await terminate_session(
                session_id, self._client, reason=IDLE_CLOSE_REASON, expire_inbound=False
            )
            if not terminated:
                logger.warning(_CLOSE_NOT_PERFORMED_EVENT, session_id=session_id)
                return
            logger.info(_CLOSED_EVENT, session_id=session_id, agent=session.active_agent)

    async def _due_to_close(self, session: Session) -> NotDueReason | None:
        """Why the session may not be closed now, or ``None`` when its completed compaction makes it due."""
        reason = await _not_due_reason(session, datetime.now(UTC), require_idle_status=False)
        if reason is not None:
            logger.info(_NOT_DUE_EVENT, session_id=session.session_id, step=IdleStep.CLOSE, reason=reason.value)
            return reason
        if not compaction_completed(session):
            return NotDueReason.COMPACTION_NOT_COMPLETED
        return None
