"""Typed persistence adapter for the Session agent-status record."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict, cast

from sqlalchemy import update
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core import db_models
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionUpdatedContext, TeleClaudeEvents
from teleclaude.core.models import Session, SessionField
from teleclaude.core.session_status import AgentStatusReason, AgentStatusValue
from teleclaude.events.envelope import EventVisibility

EMPTY_AGENT_STATUS_REASON = ""
INVALID_OPEN_TOOL_CALLS_UPDATE_ERROR = "open_tool_calls must be a set of strings"
TURN_NOTIFICATION_SEPARATOR = ","


class TurnNotificationRecord(StrEnum):
    """Notification outcomes recorded for the current session turn."""

    TERMINAL_TURN_END = "terminal_turn_end"
    TERMINAL_TURN_FAILED = "terminal_turn_failed"
    BLOCKED = "blocked"
    INFERRED_STALL = "inferred_stall"


TERMINAL_NOTIFICATION_RECORDS: frozenset[TurnNotificationRecord] = frozenset(
    {TurnNotificationRecord.TERMINAL_TURN_END, TurnNotificationRecord.TERMINAL_TURN_FAILED}
)


class _SessionUpdateStore(Protocol):
    """Narrow update surface implemented by the database session store."""

    async def get_session(self, session_id: str) -> Session | None: ...

    async def update_session(self, session_id: str, **fields: object) -> Session | None: ...

    def _session(self) -> SqlAsyncSession: ...


class _AgentStatusChangedFields(TypedDict):
    """Stored values emitted after a conditional agent-status transition."""

    agent_status: str
    agent_status_reason: str
    agent_status_since: datetime


class AgentStatusPersistenceMixin:
    """Persist typed agent-status changes through the session update owner."""

    async def update_agent_status(
        self,
        session_id: str,
        *,
        status: AgentStatusValue,
        reason: AgentStatusReason | None,
        since: datetime | None,
        runtime_activity_at: datetime | None,
        open_tool_calls: set[str],
    ) -> Session | None:
        """Persist the complete agent-status record as one session update."""
        store = cast(_SessionUpdateStore, self)
        return await store.update_session(
            session_id,
            agent_status=status,
            agent_status_reason=reason,
            agent_status_since=since,
            runtime_activity_at=runtime_activity_at,
            open_tool_calls=open_tool_calls,
        )

    async def clear_inferred_stall_notification(self, session_id: str) -> None:
        """Clear the inferred-stall slot while preserving other turn records."""
        store = cast(_SessionUpdateStore, self)
        session = await store.get_session(session_id)
        if session is None:
            return
        records = {
            TurnNotificationRecord(value)
            for value in session.turn_notifications_sent.split(TURN_NOTIFICATION_SEPARATOR)
            if value
        }
        records.discard(TurnNotificationRecord.INFERRED_STALL)
        await store.update_session(
            session_id, turn_notifications_sent=TURN_NOTIFICATION_SEPARATOR.join(sorted(records))
        )

    async def apply_inferred_agent_stall_if_unchanged(
        self,
        expected: Session,
        *,
        reason: AgentStatusReason,
        at: datetime,
    ) -> bool:
        """Apply a watchdog verdict only while every observed status input still matches."""
        store = cast(_SessionUpdateStore, self)
        expected_reason = (
            expected.agent_status_reason.value if expected.agent_status_reason else EMPTY_AGENT_STATUS_REASON
        )
        statement = (
            update(db_models.Session)
            .where(
                db_models.Session.session_id == expected.session_id,
                db_models.Session.agent_status == expected.agent_status.value,
                db_models.Session.agent_status_reason == expected_reason,
                db_models.Session.agent_status_since == expected.agent_status_since,
                db_models.Session.runtime_activity_at == expected.runtime_activity_at,
                db_models.Session.open_tool_calls == json.dumps(sorted(expected.open_tool_calls)),
                db_models.Session.lifecycle_status == expected.lifecycle_status,
                db_models.Session.active_agent == expected.active_agent,
            )
            .values(
                agent_status=AgentStatusValue.STALLED.value,
                agent_status_reason=reason.value,
                agent_status_since=at,
            )
        )
        if expected.closed_at is None:
            statement = statement.where(db_models.Session.closed_at.is_(None))
        else:
            statement = statement.where(db_models.Session.closed_at == expected.closed_at)
        async with store._session() as db_session:
            result = await db_session.exec(statement)
            await db_session.commit()
        if (result.rowcount or 0) != 1:
            return False
        changed_fields = _AgentStatusChangedFields(
            agent_status=AgentStatusValue.STALLED.value,
            agent_status_reason=reason.value,
            agent_status_since=at,
        )
        event_bus.emit(
            TeleClaudeEvents.SESSION_UPDATED,
            SessionUpdatedContext(session_id=expected.session_id, updated_fields=changed_fields),
            visibility=EventVisibility.CLUSTER,
        )
        return True


def serialize_agent_status_field(attr_name: str, value: object) -> tuple[bool, object]:
    """Validate and serialize values owned by the agent-status persistence surface."""
    if attr_name == SessionField.AGENT_STATUS.value:
        return True, AgentStatusValue(str(value)).value
    if attr_name == SessionField.AGENT_STATUS_REASON.value:
        return True, AgentStatusReason(str(value)).value if value else EMPTY_AGENT_STATUS_REASON
    if attr_name == SessionField.OPEN_TOOL_CALLS.value:
        if not isinstance(value, set) or not all(isinstance(call_id, str) for call_id in value):
            raise TypeError(INVALID_OPEN_TOOL_CALLS_UPDATE_ERROR)
        return True, json.dumps(sorted(value))
    return False, value
