"""Moves a session's stored agent status on normalized events, run starts, and watchdog verdicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from teleclaude.config._models import AGENT_NO_SIGNAL_TIMEOUT_S, AGENT_NO_START_TIMEOUT_S
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import AgentHookEvents, SessionStatusContext, TeleClaudeEvents
from teleclaude.core.session_status import (
    AgentStatusReason,
    AgentStatusValue,
    is_session_terminal,
)
from teleclaude.core.status_contract import serialize_status_event
from teleclaude.events.envelope import EventVisibility

if TYPE_CHECKING:
    from teleclaude.core.models import Session


class AgentStatusStore(Protocol):
    """Persistence operations required by the agent-status owner."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def update_agent_status(
        self,
        session_id: str,
        *,
        status: AgentStatusValue,
        reason: AgentStatusReason | None,
        since: datetime | None,
        runtime_activity_at: datetime | None,
        open_tool_calls: set[str],
    ) -> Session | None: ...

    async def clear_inferred_stall_notification(self, session_id: str) -> None: ...

    async def apply_inferred_agent_stall_if_unchanged(
        self,
        expected: Session,
        *,
        reason: AgentStatusReason,
        at: datetime,
    ) -> bool: ...


@dataclass(frozen=True)
class AgentStatusTransition:
    """The status value before and after one persisted transition."""

    previous: AgentStatusValue
    entered: AgentStatusValue


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
BLOCKED_REASON_REQUIRED_ERROR = "agent_blocked requires a supported blocked reason"


async def apply_agent_event(
    store: AgentStatusStore,
    session_id: str,
    event: AgentHookEvents,
    *,
    received_at: datetime,
    tool_call_id: str | None = None,
    tool_batch_resolved: bool = False,
    blocked_reason: AgentStatusReason | None = None,
) -> AgentStatusTransition | None:
    """Persist one normalized agent event and publish a status transition if it changed."""
    rule = AGENT_STATUS_RULES.get(event)
    if rule is None:
        return None
    session = await store.get_session(session_id)
    if session is None or is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        return None

    status, reason = rule
    if event is AgentHookEvents.AGENT_BLOCKED:
        if blocked_reason not in BLOCKED_REASONS:
            raise ValueError(BLOCKED_REASON_REQUIRED_ERROR)
        reason = blocked_reason

    open_tool_calls = set(session.open_tool_calls)
    if event is AgentHookEvents.PRE_TOOL_USE and tool_call_id:
        open_tool_calls.add(tool_call_id)
    elif event is AgentHookEvents.POST_TOOL_USE:
        if tool_batch_resolved:
            open_tool_calls.clear()
        elif tool_call_id:
            open_tool_calls.discard(tool_call_id)
    elif event in TURN_BOUNDARY_EVENTS:
        open_tool_calls.clear()

    runtime_activity_at = session.runtime_activity_at
    if runtime_activity_at is None or received_at > runtime_activity_at:
        runtime_activity_at = received_at

    previous = session.agent_status
    changed = previous is not status or session.agent_status_reason is not reason
    next_since = received_at if changed else session.agent_status_since
    await store.update_agent_status(
        session_id,
        status=status,
        reason=reason,
        since=next_since,
        runtime_activity_at=runtime_activity_at,
        open_tool_calls=open_tool_calls,
    )
    if changed:
        _publish_status(session_id, status, reason, received_at, runtime_activity_at)
        return AgentStatusTransition(previous=previous, entered=status)
    return None


async def begin_agent_run(store: AgentStatusStore, session_id: str, *, at: datetime) -> AgentStatusTransition | None:
    """Reset agent status and per-run activity immediately before process dispatch."""
    session = await store.get_session(session_id)
    if session is None or is_session_terminal(
        lifecycle_status=session.lifecycle_status,
        closed_at=session.closed_at,
    ):
        return None
    previous = session.agent_status
    await store.clear_inferred_stall_notification(session_id)
    await store.update_agent_status(
        session_id,
        status=AgentStatusValue.UNKNOWN,
        reason=None,
        since=at,
        runtime_activity_at=None,
        open_tool_calls=set(),
    )
    if previous is not AgentStatusValue.UNKNOWN or session.agent_status_reason is not None:
        _publish_status(session_id, AgentStatusValue.UNKNOWN, None, at, None)
        return AgentStatusTransition(previous=previous, entered=AgentStatusValue.UNKNOWN)
    return None


def evaluate_watchdogs(session: Session, now: datetime) -> AgentStatusReason | None:
    """Return the sole silence-derived status reason when a watchdog window elapsed."""
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return None
    if session.agent_status is AgentStatusValue.UNKNOWN:
        if session.active_agent and session.agent_status_since is not None:
            elapsed = (now - session.agent_status_since).total_seconds()
            if elapsed >= AGENT_NO_START_TIMEOUT_S:
                return AgentStatusReason.NO_START
        return None
    if session.agent_status is AgentStatusValue.ACTIVE and not session.open_tool_calls:
        last_signal = max(
            (timestamp for timestamp in (session.runtime_activity_at, session.agent_status_since) if timestamp),
            default=None,
        )
        if last_signal is not None and (now - last_signal).total_seconds() >= AGENT_NO_SIGNAL_TIMEOUT_S:
            return AgentStatusReason.NO_SIGNAL
    return None


async def apply_inferred_stall(
    store: AgentStatusStore,
    session_id: str,
    reason: AgentStatusReason,
    *,
    at: datetime,
) -> AgentStatusTransition | None:
    """Re-check a watchdog verdict against the latest row before persisting it."""
    session = await store.get_session(session_id)
    if session is None or evaluate_watchdogs(session, at) is not reason:
        return None
    previous = session.agent_status
    applied = await store.apply_inferred_agent_stall_if_unchanged(
        session,
        reason=reason,
        at=at,
    )
    if not applied:
        return None
    _publish_status(session_id, AgentStatusValue.STALLED, reason, at, session.runtime_activity_at)
    return AgentStatusTransition(previous=previous, entered=AgentStatusValue.STALLED)


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
