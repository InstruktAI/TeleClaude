"""The one-time deployment transition of the conversation-memory workers, and the barrier that gates release on it.

Workers that began under the session-addressed contract may hold accepted work and run beside no successor. The
transition runs once at the daemon's start, before any extraction is released: it re-captures the endings those
workers had not finished into the identity-addressed pipeline, settles their queued activations, and retires every
such worker. Until it is recorded complete on this computer no extraction is released, so an old and a new worker
never run for one scope at once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from instrukt_ai_logging import get_logger

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.events.envelope import ReceivedEvent
from teleclaude.events.renames import RETIRED_SESSION_ENDED_TYPE
from teleclaude.events.schemas.system import SESSION_ENDED_PREFIX, SessionEndedData
from teleclaude.events.type_pattern import TypePattern
from teleclaude.memory import closure, extractions
from teleclaude.memory.transition_barrier import record_transition_complete, transition_is_complete

logger = get_logger(__name__)

type SessionTerminator = Callable[[str], Awaitable[bool]]
"""Ends a session through agent runtime's end command; whether the session was ended by the call."""

LEGACY_PROCEDURE_IDS = (
    "general/procedure/conversation-memory/person",
    "general/procedure/conversation-memory/desk-company",
    "general/procedure/conversation-memory/desk-project",
)
TRANSITION_RETRY_INTERVAL_S = 60.0

_RECAPTURED_EVENT = "memory_transition_ending_recaptured"
_ENDING_UNREADABLE_EVENT = "memory_transition_ending_unreadable"
_SETTLED_EVENT = "memory_transition_activation_settled"
_AGENT_RETIRED_EVENT = "memory_transition_agent_retired"
_AGENT_RETIRE_FAILED_EVENT = "memory_transition_agent_retire_failed"
_TRANSITION_PASS_FAILED_EVENT = "memory_transition_pass_failed"
_TRANSITION_REASON = "superseded by the identity-addressed conversation-memory pipeline"
_SESSION_ENDED_PATTERNS = (TypePattern.below(SESSION_ENDED_PREFIX), TypePattern(RETIRED_SESSION_ENDED_TYPE))
_UNFINISHED_OUTCOMES = (
    db_models.ProcedureEventDeliveryOutcome.PENDING,
    db_models.ProcedureEventDeliveryOutcome.SUSPENDED,
    db_models.ProcedureEventDeliveryOutcome.DELIVERED,
)
_SETTLEABLE_OUTCOMES = frozenset(
    {db_models.ProcedureEventDeliveryOutcome.PENDING, db_models.ProcedureEventDeliveryOutcome.SUSPENDED}
)


def _is_session_ending(event: ReceivedEvent) -> bool:
    return any(pattern.matches(event.type) for pattern in _SESSION_ENDED_PATTERNS)


async def _progress_covers(source_session_id: str, ended_at: str) -> bool:
    """Whether the source's recorded progress already reaches an ending: the legacy read point, or completed work."""
    progress = await extractions.get_progress(source_session_id)
    if progress is None:
        return False
    ending = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    reached = [
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in (progress.through_at, progress.time_bound)
        if value
    ]
    return any(value >= ending for value in reached)


async def _recapture_legacy_endings() -> None:
    """Feed every ending a legacy worker had not finished into the pipeline, and settle the queued activations."""
    records = await db.list_procedure_activations(procedure_ids=LEGACY_PROCEDURE_IDS, outcomes=_UNFINISHED_OUTCOMES)
    for record in records:
        try:
            event = ReceivedEvent.model_validate_json(record.event_json)
            if _is_session_ending(event):
                ended = SessionEndedData.model_validate(event.data)
                if not await _progress_covers(ended.session_id, ended.ended_at):
                    await closure.intake_closure(event)
                    logger.info(_RECAPTURED_EVENT, activation_id=record.activation_id, session_id=ended.session_id)
        except ValueError as exc:
            logger.warning(_ENDING_UNREADABLE_EVENT, activation_id=record.activation_id, error=str(exc))
        if record.outcome in _SETTLEABLE_OUTCOMES:
            await db.fail_procedure_event(activation_id=record.activation_id, reason=_TRANSITION_REASON)
            logger.info(_SETTLED_EVENT, activation_id=record.activation_id)


async def _retire_legacy_agents(terminate: SessionTerminator) -> int:
    """End every open agent of the legacy procedures, busy or idle; how many remain after the attempt."""
    remaining = 0
    for session in await db.list_sessions(all_open=True):
        if session.job not in LEGACY_PROCEDURE_IDS:
            continue
        try:
            retired = await terminate(session.session_id)
        except Exception as exc:
            retired = False
            logger.error(_AGENT_RETIRE_FAILED_EVENT, session_id=session.session_id, error=str(exc), exc_info=True)
        if retired:
            logger.info(_AGENT_RETIRED_EVENT, session_id=session.session_id)
        else:
            remaining += 1
    return remaining


async def run_transition(terminate: SessionTerminator) -> bool:
    """Run the transition once; whether it is complete on this computer afterwards.

    Idempotent: re-capturing an ending, settling a settled activation and ending an ended agent each repeat
    harmlessly, so a pass that could not finish is simply run again. A recorded transition is never redone.
    """
    if await transition_is_complete():
        return True
    await _recapture_legacy_endings()
    if await _retire_legacy_agents(terminate):
        return False
    await record_transition_complete()
    await closure.allocate_all_pending()
    return True


async def run_transition_until_complete(terminate: SessionTerminator, stop: asyncio.Event) -> None:
    """Retry the transition until it is complete or the daemon stops; a failed pass is logged and retried."""
    while not stop.is_set():
        try:
            if await run_transition(terminate):
                return
        except Exception as exc:
            logger.error(_TRANSITION_PASS_FAILED_EVENT, error=str(exc), exc_info=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=TRANSITION_RETRY_INTERVAL_S)
        except TimeoutError:
            continue
