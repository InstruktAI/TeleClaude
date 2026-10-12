"""Closing a conversation session once the work it holds has settled.

Two callers close a conversation session while its person may still return: the
idle cycle, after a confirmed compaction, and the retirement of a competing
session when its channel moves to one owner. Both close a session only when its
accepted work has settled, stamp the close before the session leaves ``ACTIVE``,
and call the close off when input arrives while it starts. Input still queued
for the session stays queued: the close keeps the conversation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.models import RelayStatus, Session
from teleclaude.core.session_cleanup import terminate_session
from teleclaude.core.session_lifecycle import LifecycleTransition, LifecycleTransitionReason, transition_session
from teleclaude.core.session_revival import session_is_resumable
from teleclaude.core.session_runtime_gate import RuntimeMutationInProgress, session_runtime_owner
from teleclaude.core.session_status import AgentStatusValue, SessionLifecycleStatus, is_agent_turn_running

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

RETIRE_CLOSE_REASON: Final[str] = "channel_retirement"


class NotDueReason(StrEnum):
    """Why a conversation session is not due to be closed."""

    NOT_ACTIVE = "not_active"
    NOT_RESUMABLE = "not_resumable"
    RECENT_INPUT = "recent_input"
    RELAY_ACTIVE = "relay_active"
    TURN_RUNNING = "turn_running"
    AGENT_NOT_IDLE = "agent_not_idle"
    INPUT_QUEUED = "input_queued"
    CONTROL_PENDING = "control_pending"
    PROCEDURE_EVENTS_PENDING = "procedure_events_pending"
    VOICE_INPUT_PENDING = "voice_input_pending"
    COMPACTION_NOT_COMPLETED = "compaction_not_completed"


class CloseOutcome(StrEnum):
    """What became of one request to close a settled conversation session."""

    CLOSED = "closed"
    DEFERRED = "deferred"
    CALLED_OFF = "called_off"
    NOT_PERFORMED = "not_performed"


@dataclass(frozen=True)
class CloseAdmission:
    """The outcome of a close request and, when the close did not happen, why not."""

    outcome: CloseOutcome
    reason: NotDueReason | None = None


async def _voice_input_pending(session_id: str) -> bool:
    """Whether a voice message of the session is still on its way to being accepted as input."""
    return any(row.session_id == session_id for row in await db.list_recoverable_voice_transcriptions())


async def unsettled_reason(
    session: Session, *, require_idle_status: bool, include_voice: bool = False
) -> NotDueReason | None:
    """Why the session's conversation is still going on, or ``None`` when its accepted work has settled.

    The agent's idle status is required to start new work on the session and not to close it
    after a compaction, because the compaction itself moves the status. Unfinished voice input
    counts only for a caller that closes a session its person may not have finished speaking to.
    """
    if session.closed_at is not None:
        return NotDueReason.NOT_ACTIVE
    if not session_is_resumable(session):
        return NotDueReason.NOT_RESUMABLE
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
    if await db.count_pending_procedure_events_for_session(session_id=session.session_id):
        return NotDueReason.PROCEDURE_EVENTS_PENDING
    if include_voice and await _voice_input_pending(session.session_id):
        return NotDueReason.VOICE_INPUT_PENDING
    return None


async def _admit_always(_session: Session) -> bool:
    return True


async def _after_nothing(_session: Session) -> None:
    return None


async def close_when_settled(
    session_id: str,
    client: AdapterClient,
    *,
    close_reason: str,
    blocker: Callable[[Session], Awaitable[NotDueReason | None]],
    mark_idle_closed: bool,
    admit: Callable[[Session], Awaitable[bool]] = _admit_always,
    after_closed: Callable[[Session], Awaitable[None]] = _after_nothing,
) -> CloseAdmission:
    """Close a conversation session unless it is going on, calling the close off when input reaches it.

    ``blocker`` states why the session may not close now, and is asked again once the close has
    started, so input that arrived meanwhile calls the close off. ``mark_idle_closed`` stamps the
    close before the session leaves ``ACTIVE``: input that still reaches the session afterwards
    finds an idle-closed conversation, whose delivery waits for the close to end and resumes the
    same session. A close without the stamp is never resumed by queued delivery. ``admit`` is the
    caller's own precondition on the session as the close finds it; ``after_closed`` runs on that
    session once its close is done.
    """
    async with session_runtime_owner(session_id):
        fresh = await db.get_session(session_id)
        if fresh is None or fresh.lifecycle_status != SessionLifecycleStatus.ACTIVE:
            return CloseAdmission(CloseOutcome.DEFERRED, NotDueReason.NOT_ACTIVE)
        if not await admit(fresh):
            return CloseAdmission(CloseOutcome.DEFERRED)
        blocked = await blocker(fresh)
        if blocked is not None:
            return CloseAdmission(CloseOutcome.DEFERRED, blocked)
        if mark_idle_closed:
            await db.update_session(session_id, idle_closed_at=datetime.now(UTC).isoformat())
        await transition_session(
            db,
            session_id,
            LifecycleTransition(SessionLifecycleStatus.CLOSING, LifecycleTransitionReason.CLOSE_STARTED),
        )
        started = await db.get_session(session_id)
        blocked = None if started is None else await blocker(started)
        if blocked is not None:
            await transition_session(
                db,
                session_id,
                LifecycleTransition(SessionLifecycleStatus.ACTIVE, LifecycleTransitionReason.CLOSE_FAILED),
            )
            if mark_idle_closed:
                await db.update_session(session_id, idle_closed_at=None)
            return CloseAdmission(CloseOutcome.CALLED_OFF, blocked)
        if not await terminate_session(session_id, client, reason=close_reason, expire_inbound=False):
            return CloseAdmission(CloseOutcome.NOT_PERFORMED)
        await after_closed(fresh)
        return CloseAdmission(CloseOutcome.CLOSED)


async def _retirement_blocker(session: Session) -> NotDueReason | None:
    return await unsettled_reason(session, require_idle_status=True, include_voice=True)


async def retire_session(session_id: str, client: AdapterClient) -> CloseAdmission:
    """Close a session that competes for a channel another session owns, once its accepted work has settled.

    The record keeps its identity, transcript lineage and memory provenance. A session that is
    being changed by another operation is left for the next attempt.
    """
    try:
        return await close_when_settled(
            session_id,
            client,
            close_reason=RETIRE_CLOSE_REASON,
            blocker=_retirement_blocker,
            mark_idle_closed=False,
        )
    except RuntimeMutationInProgress:
        return CloseAdmission(CloseOutcome.DEFERRED)


__all__ = [
    "RETIRE_CLOSE_REASON",
    "CloseAdmission",
    "CloseOutcome",
    "NotDueReason",
    "close_when_settled",
    "retire_session",
    "unsettled_reason",
]
