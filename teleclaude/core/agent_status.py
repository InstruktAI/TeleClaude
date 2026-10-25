"""Own agent-status transition rules and publish committed status changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, assert_never
from uuid import uuid4

from teleclaude.core.events import AgentHookEvents
from teleclaude.core.runtime_events import publish_session_status
from teleclaude.core.session_status import (
    TERMINAL_LIFECYCLE_STATUSES,
    AgentStatusReason,
    AgentStatusValue,
    is_agent_turn_running,
    is_session_terminal,
)
from teleclaude.core.status_contract import serialize_status_event

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_INTEGRITY_ERROR_MESSAGE = "Agent status integrity failure for session %s during %s (affected rows: %s)"
_CONTENTION_ERROR_MESSAGE = "Agent status contention retries exhausted for session %s during %s"
_BLOCKED_REASON_REQUIRED_ERROR = "agent_blocked requires a supported blocked reason"
_STATUS_TARGET_LABEL = "%s->%s"
_RUN_START_LABEL = "agent_run_start"
_DELIVERY_BLOCK_LABEL = "delivery_observed_block"
_MAX_VERSION_ATTEMPTS = 3


class AgentStatusIntegrityError(RuntimeError):
    """A status transition violated a row or affected-count invariant."""

    def __init__(self, session_id: str, attempted_transition: str, affected_rows: int) -> None:
        super().__init__(_INTEGRITY_ERROR_MESSAGE % (session_id, attempted_transition, affected_rows))


class AgentStatusContentionError(RuntimeError):
    """Repeated concurrent writes prevented a status transition from committing."""

    def __init__(self, session_id: str, attempted_transition: str) -> None:
        super().__init__(_CONTENTION_ERROR_MESSAGE % (session_id, attempted_transition))


@dataclass(frozen=True)
class AgentEventCause:
    """Normalized event and event-specific evidence for a status transition."""

    event: AgentHookEvents
    tool_call_id: str | None = None
    tool_batch_resolved: bool = False
    blocked_reason: AgentStatusReason | None = None
    new_turn: bool = False
    turn_id: str | None = None


@dataclass(frozen=True)
class AgentRunStart:
    """Cause representing a process run starting for the session."""

    startup_work_expected: bool = False
    run_id: str | None = None


@dataclass(frozen=True)
class DeliveryObservedBlock:
    """Cause representing input delivery finding no composer to deliver into.

    The agent CLI shows some other screen and the runtime sent no signal about
    it, so the daemon's own observation is the evidence.
    """


type AgentStatusCause = AgentEventCause | AgentRunStart | DeliveryObservedBlock


class AgentStatusCommit(StrEnum):
    """Distinct outcomes from version-guarded event and run-start writes."""

    COMMITTED = "committed"
    VERSION_MOVED = "version_moved"
    SESSION_TERMINAL = "session_terminal"


@dataclass(frozen=True)
class AgentStatusTransition:
    """The status value before and after one persisted transition."""

    previous: AgentStatusValue
    entered: AgentStatusValue


@dataclass(frozen=True)
class TurnEndEvidence:
    """A provider-reported turn completion and the session snapshot it was judged against."""

    completed_at: datetime
    snapshot: Session


class AgentStatusStore(Protocol):
    """Persistence operations required by the agent-status owner."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def commit_agent_status(
        self,
        session_id: str,
        *,
        expected_version: int,
        expected_runtime_run_id: str | None,
        cause: AgentStatusCause,
        status: AgentStatusValue,
        reason: AgentStatusReason | None,
        since: datetime | None,
        runtime_activity_at: datetime | None,
        open_tool_calls: frozenset[str],
        runtime_run_id: str | None,
        runtime_turn_id: str | None,
    ) -> AgentStatusCommit: ...

    async def commit_reconciled_turn_end(
        self,
        session_id: str,
        *,
        evidence: TurnEndEvidence,
        status: AgentStatusValue,
        reason: AgentStatusReason | None,
        since: datetime | None,
        runtime_activity_at: datetime | None,
        open_tool_calls: frozenset[str],
        runtime_run_id: str | None,
        runtime_turn_id: str | None,
    ) -> bool: ...


AgentStatusRule = tuple[AgentStatusValue, AgentStatusReason | None]

AGENT_STATUS_RULES: dict[AgentHookEvents, AgentStatusRule] = {
    AgentHookEvents.AGENT_SESSION_START: (AgentStatusValue.IDLE, None),
    AgentHookEvents.USER_PROMPT_SUBMIT: (AgentStatusValue.ACTIVE, None),
    AgentHookEvents.PRE_TOOL_USE: (AgentStatusValue.ACTIVE, None),
    AgentHookEvents.POST_TOOL_USE: (AgentStatusValue.ACTIVE, None),
    AgentHookEvents.AGENT_BLOCKED: (AgentStatusValue.BLOCKED, None),
    AgentHookEvents.AGENT_STOP: (AgentStatusValue.IDLE, None),
    AgentHookEvents.AGENT_IDLE: (AgentStatusValue.IDLE, None),
    AgentHookEvents.AGENT_TURN_FAILED: (AgentStatusValue.STALLED, AgentStatusReason.TURN_FAILED),
}

TURN_BOUNDARY_EVENTS = frozenset(
    {
        AgentHookEvents.USER_PROMPT_SUBMIT,
        AgentHookEvents.AGENT_STOP,
        AgentHookEvents.AGENT_IDLE,
        AgentHookEvents.AGENT_TURN_FAILED,
    }
)
BLOCKED_REASONS = frozenset({AgentStatusReason.NEEDS_INPUT, AgentStatusReason.QUOTA_WAIT})


def _attempted_transition(cause: AgentStatusCause, status: AgentStatusValue) -> str:
    match cause:
        case AgentRunStart():
            cause_name = _RUN_START_LABEL
        case DeliveryObservedBlock():
            cause_name = _DELIVERY_BLOCK_LABEL
        case AgentEventCause():
            cause_name = cause.event.value
        case _:
            assert_never(cause)
    return _STATUS_TARGET_LABEL % (cause_name, status.value)


def _next_status_record(
    session: Session,
    cause: AgentEventCause | AgentRunStart | DeliveryObservedBlock,
    at: datetime,
) -> tuple[
    AgentStatusValue,
    AgentStatusReason | None,
    datetime | None,
    datetime | None,
    frozenset[str],
    str | None,
    str | None,
]:
    match cause:
        case AgentRunStart():
            return AgentStatusValue.UNKNOWN, None, at, None, frozenset(), cause.run_id, None
        case DeliveryObservedBlock():
            return _delivery_block_record(session, at)
        case AgentEventCause():
            return _event_status_record(session, cause, at)
        case _:
            assert_never(cause)


def _delivery_block_record(
    session: Session,
    at: datetime,
) -> tuple[
    AgentStatusValue,
    AgentStatusReason | None,
    datetime | None,
    datetime | None,
    frozenset[str],
    str | None,
    str | None,
]:
    """Enter ``blocked`` / ``needs_input``; the runtime did nothing, so its activity and tool calls stay as they were."""
    status = AgentStatusValue.BLOCKED
    reason = AgentStatusReason.NEEDS_INPUT
    status_changed = session.agent_status is not status or session.agent_status_reason is not reason
    since = at if status_changed else session.agent_status_since
    return (
        status,
        reason,
        since,
        session.runtime_activity_at,
        frozenset(session.open_tool_calls),
        session.runtime_run_id,
        session.runtime_turn_id,
    )


def _event_status_record(
    session: Session,
    cause: AgentEventCause,
    at: datetime,
) -> tuple[
    AgentStatusValue,
    AgentStatusReason | None,
    datetime | None,
    datetime | None,
    frozenset[str],
    str | None,
    str | None,
]:
    status, reason = AGENT_STATUS_RULES[cause.event]
    if cause.event is AgentHookEvents.AGENT_BLOCKED:
        reason = cause.blocked_reason
    open_tool_calls = set(session.open_tool_calls)
    if cause.event is AgentHookEvents.PRE_TOOL_USE and cause.tool_call_id:
        open_tool_calls.add(cause.tool_call_id)
    elif cause.event is AgentHookEvents.POST_TOOL_USE:
        if cause.tool_batch_resolved:
            open_tool_calls.clear()
        elif cause.tool_call_id:
            open_tool_calls.discard(cause.tool_call_id)
    elif cause.event in TURN_BOUNDARY_EVENTS:
        open_tool_calls.clear()
    current_activity = session.runtime_activity_at
    runtime_activity_at = at if current_activity is None or at > current_activity else current_activity
    status_changed = session.agent_status is not status or session.agent_status_reason is not reason
    since = at if status_changed else session.agent_status_since
    return (
        status,
        reason,
        since,
        runtime_activity_at,
        frozenset(open_tool_calls),
        session.runtime_run_id,
        cause.turn_id if cause.new_turn else session.runtime_turn_id,
    )


async def transition_agent_status(
    store: AgentStatusStore,
    session_id: str,
    cause: AgentStatusCause,
    *,
    at: datetime,
    expected_runtime_run_id: str | None = None,
) -> AgentStatusTransition | None:
    """Apply one normalized activity, run-start, or delivery-observed block through its owner."""
    if isinstance(cause, AgentRunStart) and cause.run_id is None:
        cause = AgentRunStart(startup_work_expected=cause.startup_work_expected, run_id=str(uuid4()))
    if isinstance(cause, AgentEventCause) and cause.new_turn and cause.turn_id is None:
        cause = AgentEventCause(
            event=cause.event,
            tool_call_id=cause.tool_call_id,
            tool_batch_resolved=cause.tool_batch_resolved,
            blocked_reason=cause.blocked_reason,
            new_turn=True,
            turn_id=str(uuid4()),
        )
    match cause:
        case AgentRunStart():
            target_status = AgentStatusValue.UNKNOWN
        case DeliveryObservedBlock():
            target_status = AgentStatusValue.BLOCKED
        case AgentEventCause():
            event_rule = AGENT_STATUS_RULES.get(cause.event)
            if event_rule is None:
                return None
            if cause.event is AgentHookEvents.AGENT_BLOCKED and cause.blocked_reason not in BLOCKED_REASONS:
                raise ValueError(_BLOCKED_REASON_REQUIRED_ERROR)
            target_status = event_rule[0]
        case _:
            assert_never(cause)
    attempted_transition = _attempted_transition(cause, target_status)
    initial_generation_loaded = False
    initial_run_id: str | None = None
    initial_turn_id: str | None = None
    for _ in range(_MAX_VERSION_ATTEMPTS):
        session = await store.get_session(session_id)
        if session is None:
            raise AgentStatusIntegrityError(session_id, attempted_transition, 0)
        if expected_runtime_run_id is not None and session.runtime_run_id != expected_runtime_run_id:
            return None
        if session.closed_at is not None or session.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES:
            return None
        if not initial_generation_loaded:
            initial_generation_loaded = True
            initial_run_id = session.runtime_run_id
            initial_turn_id = session.runtime_turn_id
        elif isinstance(cause, AgentRunStart) and session.runtime_run_id != initial_run_id:
            return None
        elif (
            isinstance(cause, AgentEventCause)
            and cause.new_turn
            and (session.runtime_run_id != initial_run_id or session.runtime_turn_id != initial_turn_id)
        ):
            return None

        (
            status,
            reason,
            since,
            runtime_activity_at,
            open_tool_calls,
            runtime_run_id,
            runtime_turn_id,
        ) = _next_status_record(session, cause, at)

        changed = (
            session.agent_status is not status
            or session.agent_status_reason is not reason
            or session.agent_status_since != since
            or session.runtime_activity_at != runtime_activity_at
            or session.open_tool_calls != open_tool_calls
            or session.runtime_run_id != runtime_run_id
            or session.runtime_turn_id != runtime_turn_id
        )
        if not changed:
            return None
        result = await store.commit_agent_status(
            session_id,
            expected_version=session.agent_status_version,
            expected_runtime_run_id=expected_runtime_run_id,
            cause=cause,
            status=status,
            reason=reason,
            since=since,
            runtime_activity_at=runtime_activity_at,
            open_tool_calls=open_tool_calls,
            runtime_run_id=runtime_run_id,
            runtime_turn_id=runtime_turn_id,
        )
        if result is AgentStatusCommit.VERSION_MOVED:
            continue
        if result is AgentStatusCommit.SESSION_TERMINAL:
            return None
        if session.agent_status is not status or session.agent_status_reason is not reason:
            await _publish_status(session_id, status, reason, at, runtime_activity_at)
            return AgentStatusTransition(previous=session.agent_status, entered=status)
        return None

    raise AgentStatusContentionError(session_id, attempted_transition)


RECONCILED_TURN_END_CAUSE = AgentEventCause(event=AgentHookEvents.AGENT_IDLE)


async def reconcile_turn_end(
    store: AgentStatusStore,
    session_id: str,
    evidence: TurnEndEvidence,
) -> AgentStatusTransition | None:
    """Record a turn end whose Stop never reached the coordinator, once and only against its snapshot.

    The idle boundary is written at the provider's completion time, so input
    accepted afterwards stays newer than it. Unlike ``transition_agent_status``
    there is no retry: a snapshot that moved means newer state exists, and
    re-applying the end to it could mark a newer turn idle.
    """
    snapshot = evidence.snapshot
    if is_session_terminal(lifecycle_status=snapshot.lifecycle_status, closed_at=snapshot.closed_at):
        return None
    last_input_at = snapshot.last_message_sent_at
    if not is_agent_turn_running(
        last_input_at=last_input_at,
        last_agent_stop_at=snapshot.last_agent_stop_at,
        last_agent_idle_at=snapshot.last_agent_idle_at,
    ):
        return None
    if last_input_at is None or evidence.completed_at <= last_input_at:
        return None
    if snapshot.runtime_activity_at is not None and snapshot.runtime_activity_at > evidence.completed_at:
        return None
    (
        status,
        reason,
        since,
        runtime_activity_at,
        open_tool_calls,
        runtime_run_id,
        runtime_turn_id,
    ) = _event_status_record(snapshot, RECONCILED_TURN_END_CAUSE, evidence.completed_at)
    committed = await store.commit_reconciled_turn_end(
        session_id,
        evidence=evidence,
        status=status,
        reason=reason,
        since=since,
        runtime_activity_at=runtime_activity_at,
        open_tool_calls=open_tool_calls,
        runtime_run_id=runtime_run_id,
        runtime_turn_id=runtime_turn_id,
    )
    if not committed:
        return None
    await _publish_status(session_id, status, reason, evidence.completed_at, runtime_activity_at)
    return AgentStatusTransition(previous=snapshot.agent_status, entered=status)


async def _publish_status(
    session_id: str,
    status: AgentStatusValue,
    reason: AgentStatusReason | None,
    at: datetime,
    last_activity_at: datetime | None,
) -> None:
    """Validate and publish the stored status through the canonical event stream."""
    status_reason = reason.value if reason else status.value
    timestamp = at.isoformat()
    last_activity = last_activity_at.isoformat() if last_activity_at else None
    canonical = serialize_status_event(
        session_id=session_id,
        status=status.value,
        reason=status_reason,
        timestamp=timestamp,
        last_activity_at=last_activity,
    )
    if canonical is None:
        return
    await publish_session_status(
        session_id,
        status.value,
        status_reason,
        timestamp,
        last_activity_at=last_activity,
        message_intent=canonical.message_intent,
        delivery_scope=canonical.delivery_scope,
    )
