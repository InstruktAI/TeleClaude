"""Own agent-status transition rules and publish committed status changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, assert_never

from teleclaude.config._models import AGENT_NO_SIGNAL_TIMEOUT_S, AGENT_NO_START_TIMEOUT_S
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import AgentHookEvents, SessionStatusContext, TeleClaudeEvents
from teleclaude.core.session_status import (
    TERMINAL_LIFECYCLE_STATUSES,
    AgentStatusReason,
    AgentStatusValue,
    TurnNotificationRecord,
)
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from teleclaude.core.models import Session

_INTEGRITY_ERROR_MESSAGE = "Agent status integrity failure for session %s during %s (affected rows: %s)"
_CONTENTION_ERROR_MESSAGE = "Agent status contention retries exhausted for session %s during %s"
_BLOCKED_REASON_REQUIRED_ERROR = "agent_blocked requires a supported blocked reason"
_STATUS_TARGET_LABEL = "%s->%s"
_RUN_START_LABEL = "agent_run_start"
_DELIVERY_BLOCK_LABEL = "delivery_observed_block"
_INFERRED_STALL_LABEL = "inferred_stall:%s"
_MAX_VERSION_ATTEMPTS = 3


class AgentStatusIntegrityError(RuntimeError):
    """A status transition violated a row or affected-count invariant."""

    def __init__(self, session_id: str, attempted_transition: str, affected_rows: int) -> None:
        super().__init__(_INTEGRITY_ERROR_MESSAGE % (session_id, attempted_transition, affected_rows))


class AgentStatusContentionError(RuntimeError):
    """Repeated concurrent writes prevented a status transition from committing."""

    def __init__(self, session_id: str, attempted_transition: str) -> None:
        super().__init__(_CONTENTION_ERROR_MESSAGE % (session_id, attempted_transition))


class SilenceClock(StrEnum):
    """Timestamp source used by one inferred-stall rule."""

    LAST_SIGNAL = "last_signal"
    STATUS_ENTERED = "status_entered"


@dataclass(frozen=True)
class InferredStallRule:
    """One persisted status and its complete silence-verdict conditions."""

    reason: AgentStatusReason
    status: AgentStatusValue
    window_s: float
    silence_clock: SilenceClock
    tool_calls_must_be_closed: bool
    agent_must_be_assigned: bool


INFERRED_STALL_RULES = (
    InferredStallRule(
        reason=AgentStatusReason.NO_SIGNAL,
        status=AgentStatusValue.ACTIVE,
        window_s=AGENT_NO_SIGNAL_TIMEOUT_S,
        silence_clock=SilenceClock.LAST_SIGNAL,
        tool_calls_must_be_closed=True,
        agent_must_be_assigned=False,
    ),
    InferredStallRule(
        reason=AgentStatusReason.NO_START,
        status=AgentStatusValue.UNKNOWN,
        window_s=AGENT_NO_START_TIMEOUT_S,
        silence_clock=SilenceClock.STATUS_ENTERED,
        tool_calls_must_be_closed=False,
        agent_must_be_assigned=True,
    ),
)


@dataclass(frozen=True)
class AgentEventCause:
    """Normalized event and event-specific evidence for a status transition."""

    event: AgentHookEvents
    tool_call_id: str | None = None
    tool_batch_resolved: bool = False
    blocked_reason: AgentStatusReason | None = None


@dataclass(frozen=True)
class AgentRunStart:
    """Cause representing a process run starting for the session."""


@dataclass(frozen=True)
class InferredStallVerdict:
    """Cause representing one rule's inferred-stall verdict."""

    rule: InferredStallRule


@dataclass(frozen=True)
class DeliveryObservedBlock:
    """Cause representing input delivery finding no composer to deliver into.

    The agent CLI shows some other screen and the runtime sent no signal about
    it, so the daemon's own observation is the evidence.
    """


type AgentStatusCause = AgentEventCause | AgentRunStart | InferredStallVerdict | DeliveryObservedBlock


class AgentStatusCommit(StrEnum):
    """Distinct outcomes from version-guarded event and run-start writes."""

    COMMITTED = "committed"
    VERSION_MOVED = "version_moved"
    SESSION_TERMINAL = "session_terminal"


@dataclass(frozen=True)
class CommittedStall:
    """Fields returned from a committed inferred-stall transition."""

    runtime_activity_at: datetime | None


@dataclass(frozen=True)
class AgentStatusTransition:
    """The status value before and after one persisted transition."""

    previous: AgentStatusValue
    entered: AgentStatusValue


class AgentStatusStore(Protocol):
    """Persistence operations required by the agent-status owner."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def commit_agent_status(
        self,
        session_id: str,
        *,
        expected_version: int,
        cause: AgentStatusCause,
        status: AgentStatusValue,
        reason: AgentStatusReason | None,
        since: datetime | None,
        runtime_activity_at: datetime | None,
        open_tool_calls: frozenset[str],
    ) -> AgentStatusCommit: ...

    async def commit_inferred_stall(
        self,
        session_id: str,
        rule: InferredStallRule,
        *,
        at: datetime,
    ) -> CommittedStall | None: ...

    async def release_turn_notification(self, session_id: str, record: TurnNotificationRecord) -> None: ...


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
        case InferredStallVerdict():
            cause_name = _INFERRED_STALL_LABEL % cause.rule.reason.value
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
) -> tuple[AgentStatusValue, AgentStatusReason | None, datetime | None, datetime | None, frozenset[str]]:
    match cause:
        case AgentRunStart():
            return AgentStatusValue.UNKNOWN, None, at, None, frozenset()
        case DeliveryObservedBlock():
            return _delivery_block_record(session, at)
        case AgentEventCause():
            return _event_status_record(session, cause, at)
        case _:
            assert_never(cause)


def _delivery_block_record(
    session: Session,
    at: datetime,
) -> tuple[AgentStatusValue, AgentStatusReason | None, datetime | None, datetime | None, frozenset[str]]:
    """Enter ``blocked`` / ``needs_input``; the runtime did nothing, so its activity and tool calls stay as they were."""
    status = AgentStatusValue.BLOCKED
    reason = AgentStatusReason.NEEDS_INPUT
    status_changed = session.agent_status is not status or session.agent_status_reason is not reason
    since = at if status_changed else session.agent_status_since
    return status, reason, since, session.runtime_activity_at, frozenset(session.open_tool_calls)


def _event_status_record(
    session: Session,
    cause: AgentEventCause,
    at: datetime,
) -> tuple[AgentStatusValue, AgentStatusReason | None, datetime | None, datetime | None, frozenset[str]]:
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
    return status, reason, since, runtime_activity_at, frozenset(open_tool_calls)


async def transition_agent_status(
    store: AgentStatusStore,
    session_id: str,
    cause: AgentStatusCause,
    *,
    at: datetime,
) -> AgentStatusTransition | None:
    """Apply one event, run-start, delivery-observed block, or inferred-stall transition through its owner."""
    match cause:
        case InferredStallVerdict():
            committed = await store.commit_inferred_stall(session_id, cause.rule, at=at)
            if committed is None:
                return None
            _publish_status(session_id, AgentStatusValue.STALLED, cause.rule.reason, at, committed.runtime_activity_at)
            return AgentStatusTransition(previous=cause.rule.status, entered=AgentStatusValue.STALLED)
        case AgentRunStart():
            await store.release_turn_notification(session_id, TurnNotificationRecord.INFERRED_STALL)
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
    for _ in range(_MAX_VERSION_ATTEMPTS):
        session = await store.get_session(session_id)
        if session is None:
            raise AgentStatusIntegrityError(session_id, attempted_transition, 0)
        if session.closed_at is not None or session.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES:
            return None

        status, reason, since, runtime_activity_at, open_tool_calls = _next_status_record(session, cause, at)

        changed = (
            session.agent_status is not status
            or session.agent_status_reason is not reason
            or session.agent_status_since != since
            or session.runtime_activity_at != runtime_activity_at
            or session.open_tool_calls != open_tool_calls
        )
        if not changed:
            return None
        result = await store.commit_agent_status(
            session_id,
            expected_version=session.agent_status_version,
            cause=cause,
            status=status,
            reason=reason,
            since=since,
            runtime_activity_at=runtime_activity_at,
            open_tool_calls=open_tool_calls,
        )
        if result is AgentStatusCommit.VERSION_MOVED:
            continue
        if result is AgentStatusCommit.SESSION_TERMINAL:
            return None
        if session.agent_status is not status or session.agent_status_reason is not reason:
            _publish_status(session_id, status, reason, at, runtime_activity_at)
            return AgentStatusTransition(previous=session.agent_status, entered=status)
        return None

    raise AgentStatusContentionError(session_id, attempted_transition)


def _publish_status(
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
    event_bus.emit(
        TeleClaudeEvents.SESSION_STATUS,
        SessionStatusContext(
            session_id=session_id,
            status=status.value,
            reason=status_reason,
            timestamp=timestamp,
            last_activity_at=last_activity,
            message_intent=canonical.message_intent,
            delivery_scope=canonical.delivery_scope,
        ),
        visibility=EventVisibility.CLUSTER,
    )
