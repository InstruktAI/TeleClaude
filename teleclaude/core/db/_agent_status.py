"""Typed persistence adapter for agent-status transitions and notification gates."""

from __future__ import annotations

import json
from collections.abc import Set
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict, cast

from instrukt_ai_logging import get_logger
from sqlalchemy import func, or_, select, text, update
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.core import db_models
from teleclaude.core.agent_status import (
    INFERRED_STALL_RULES,
    AgentStatusCause,
    AgentStatusCommit,
    AgentStatusIntegrityError,
    CommittedStall,
    InferredStallRule,
    InferredStallVerdict,
    SilenceClock,
    _attempted_transition,
)
from teleclaude.core.event_bus import event_bus
from teleclaude.core.events import SessionUpdatedContext, TeleClaudeEvents
from teleclaude.core.models import SessionField
from teleclaude.core.session_status import (
    TERMINAL_LIFECYCLE_STATUSES,
    AgentStatusReason,
    AgentStatusValue,
    TurnNotificationRecord,
)
from teleclaude.events.envelope import EventVisibility

_INVALID_OPEN_TOOL_CALLS_ERROR = "Invalid open_tool_calls for session %s"
_INVALID_TURN_NOTIFICATIONS_ERROR = "Invalid turn_notifications_sent for session %s"
EMPTY_AGENT_STATUS_REASON = ""
_CLAIM_NOTIFICATION_SQL = """
UPDATE sessions
SET turn_notifications_sent = json_insert(turn_notifications_sent, '$[#]', :record)
WHERE session_id = :session_id
    AND NOT EXISTS (
        SELECT 1 FROM json_each(sessions.turn_notifications_sent)
        WHERE value = :record
            OR (:terminal AND value IN (:terminal_end, :terminal_failed))
    )
RETURNING turn_notifications_sent
"""
_SELECT_TURN_NOTIFICATIONS_SQL = "SELECT turn_notifications_sent FROM sessions WHERE session_id = :session_id"
_SELECT_SESSION_EXISTENCE_SQL = "SELECT session_id FROM sessions WHERE session_id = :session_id"
_RELEASE_NOTIFICATION_SQL = """
UPDATE sessions
SET turn_notifications_sent = COALESCE(
    (SELECT json_group_array(value) FROM json_each(sessions.turn_notifications_sent)
     WHERE value != :record), '[]'
)
WHERE session_id = :session_id
    AND EXISTS (
        SELECT 1 FROM json_each(sessions.turn_notifications_sent)
        WHERE value = :record
    )
RETURNING turn_notifications_sent
"""
_CLEAR_NOTIFICATIONS_SQL = (
    "UPDATE sessions SET turn_notifications_sent = '[]' "
    "WHERE session_id = :session_id AND turn_notifications_sent != '[]' "
    "RETURNING turn_notifications_sent"
)
_SESSION_ID_PARAMETER = "session_id"
_RECORD_PARAMETER = "record"
_TERMINAL_PARAMETER = "terminal"
_TERMINAL_END_PARAMETER = "terminal_end"
_TERMINAL_FAILED_PARAMETER = "terminal_failed"
_MULTIPLE_CLAIM_ROWS_ERROR = "claim_turn_notification updated multiple rows for session %s"
_MISSING_CLAIM_SESSION_ERROR = "claim_turn_notification found no session %s"
_AGENT_STATUS_ROW_COUNT_ERROR = "Agent status transition %s for session %s affected %s rows"
_INFERRED_STALL_COMMITTED_EVENT = "agent_status_inferred_stall_committed"
_INFERRED_STALL_RULE_MOVED_EVENT = "agent_status_inferred_stall_rule_no_longer_holds"
_EMPTY_TEXT = ""

logger = get_logger(__name__)


def decode_open_tool_calls(raw: str, *, session_id: str) -> frozenset[str]:
    """Decode the persisted open-tool-call set for one session."""
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(_INVALID_OPEN_TOOL_CALLS_ERROR % session_id) from exc
    if not isinstance(value, list) or not all(isinstance(call_id, str) for call_id in value):
        raise ValueError(_INVALID_OPEN_TOOL_CALLS_ERROR % session_id)
    return frozenset(value)


def encode_open_tool_calls(calls: Set[str]) -> str:
    """Encode open tool calls as stable JSON."""
    return json.dumps(sorted(calls))


def decode_turn_notifications(raw: str, *, session_id: str) -> frozenset[TurnNotificationRecord]:
    """Decode the persisted turn-notification set for one session."""
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(_INVALID_TURN_NOTIFICATIONS_ERROR % session_id) from exc
    if not isinstance(value, list) or not all(isinstance(record, str) for record in value):
        raise ValueError(_INVALID_TURN_NOTIFICATIONS_ERROR % session_id)
    try:
        return frozenset(TurnNotificationRecord(record) for record in value)
    except ValueError as exc:
        raise ValueError(_INVALID_TURN_NOTIFICATIONS_ERROR % session_id) from exc


class _AgentStatusDatabase(Protocol):
    def _session(self) -> SqlAsyncSession: ...


class _AgentStatusUpdatedFields(TypedDict):
    agent_status: str
    agent_status_reason: str
    agent_status_since: datetime | None
    runtime_activity_at: datetime | None
    open_tool_calls: list[str]


class _InferredStallUpdatedFields(TypedDict):
    agent_status: str
    agent_status_reason: str
    agent_status_since: datetime


def _emit_turn_notifications_updated(session_id: str, records: frozenset[TurnNotificationRecord]) -> None:
    event_bus.emit(
        TeleClaudeEvents.SESSION_UPDATED,
        SessionUpdatedContext(
            session_id=session_id,
            updated_fields={SessionField.TURN_NOTIFICATIONS_SENT.value: sorted(record.value for record in records)},
        ),
        visibility=EventVisibility.CLUSTER,
    )


def _emit_agent_status_updated(
    session_id: str,
    *,
    status: AgentStatusValue,
    reason: AgentStatusReason | None,
    since: datetime | None,
    runtime_activity_at: datetime | None,
    open_tool_calls: frozenset[str],
) -> None:
    updated_fields = _AgentStatusUpdatedFields(
        agent_status=status.value,
        agent_status_reason=reason.value if reason else _EMPTY_TEXT,
        agent_status_since=since,
        runtime_activity_at=runtime_activity_at,
        open_tool_calls=sorted(open_tool_calls),
    )
    event_bus.emit(
        TeleClaudeEvents.SESSION_UPDATED,
        SessionUpdatedContext(session_id=session_id, updated_fields=updated_fields),
        visibility=EventVisibility.CLUSTER,
    )


def _emit_inferred_stall_updated(
    session_id: str,
    *,
    reason: AgentStatusReason,
    since: datetime,
) -> None:
    updated_fields = _InferredStallUpdatedFields(
        agent_status=AgentStatusValue.STALLED.value,
        agent_status_reason=reason.value,
        agent_status_since=since,
    )
    event_bus.emit(
        TeleClaudeEvents.SESSION_UPDATED,
        SessionUpdatedContext(session_id=session_id, updated_fields=updated_fields),
        visibility=EventVisibility.CLUSTER,
    )


def _session_open() -> object:
    terminal_statuses = tuple(status.value for status in TERMINAL_LIFECYCLE_STATUSES)
    return db_models.Session.closed_at.is_(None) & or_(
        db_models.Session.lifecycle_status.is_(None),
        db_models.Session.lifecycle_status.not_in(terminal_statuses),
    )


def _inferred_stall_predicate(
    rule: InferredStallRule,
    cutoff: datetime,
    *,
    include_tool_call_guard: bool = True,
) -> object:
    predicate = [
        _session_open(),
        db_models.Session.agent_status == rule.status.value,
    ]
    if rule.tool_calls_must_be_closed and include_tool_call_guard:
        predicate.append(func.json_array_length(db_models.Session.open_tool_calls) == 0)
    if rule.agent_must_be_assigned:
        predicate.extend(
            [
                db_models.Session.active_agent.is_not(None),
                db_models.Session.active_agent != _EMPTY_TEXT,
            ]
        )
    cutoff_julian = func.julianday(cutoff.astimezone(UTC).isoformat())
    if rule.silence_clock is SilenceClock.LAST_SIGNAL:
        runtime_julian = func.julianday(db_models.Session.runtime_activity_at)
        status_since_julian = func.julianday(db_models.Session.agent_status_since)
        last_signal = func.max(
            func.coalesce(runtime_julian, status_since_julian),
            func.coalesce(status_since_julian, runtime_julian),
        )
        predicate.append(last_signal <= cutoff_julian)
    else:
        predicate.append(func.julianday(db_models.Session.agent_status_since) <= cutoff_julian)
    return predicate


class AgentStatusPersistenceMixin:
    """Persist typed status records and per-turn gates with conditional statements."""

    async def claim_turn_notification(
        self, session_id: str, record: TurnNotificationRecord
    ) -> tuple[bool, frozenset[TurnNotificationRecord]]:
        """Atomically claim one notification unless its per-turn gate is already closed."""
        terminal = record in {TurnNotificationRecord.TERMINAL_TURN_END, TurnNotificationRecord.TERMINAL_TURN_FAILED}
        statement = text(_CLAIM_NOTIFICATION_SQL)  # guard: raw-sql - one conditional statement owns gate membership
        parameters = {
            _SESSION_ID_PARAMETER: session_id,
            _RECORD_PARAMETER: record.value,
            _TERMINAL_PARAMETER: terminal,
            _TERMINAL_END_PARAMETER: TurnNotificationRecord.TERMINAL_TURN_END.value,
            _TERMINAL_FAILED_PARAMETER: TurnNotificationRecord.TERMINAL_TURN_FAILED.value,
        }
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.execute(statement, parameters)
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, record.value, len(rows))
            if rows:
                records = decode_turn_notifications(rows[0][0], session_id=session_id)
                _emit_turn_notifications_updated(session_id, records)
                return True, records
            result = await db_session.execute(
                text(_SELECT_TURN_NOTIFICATIONS_SQL),
                {_SESSION_ID_PARAMETER: session_id},
            )
            stored = result.first()
            if stored is None:
                raise AgentStatusIntegrityError(session_id, record.value, 0)
            return False, decode_turn_notifications(stored[0], session_id=session_id)

    async def release_turn_notification(self, session_id: str, record: TurnNotificationRecord) -> None:
        """Atomically remove one notification record from the current turn."""
        statement = text(_RELEASE_NOTIFICATION_SQL)  # guard: raw-sql - one statement preserves concurrent claims
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.execute(
                statement,
                {_SESSION_ID_PARAMETER: session_id, _RECORD_PARAMETER: record.value},
            )
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, record.value, len(rows))
            if not rows:
                existing = await db_session.execute(
                    text(_SELECT_TURN_NOTIFICATIONS_SQL),
                    {_SESSION_ID_PARAMETER: session_id},
                )
                stored = existing.first()
                if stored is None:
                    raise AgentStatusIntegrityError(session_id, record.value, 0)
                decode_turn_notifications(stored[0], session_id=session_id)
                return
        _emit_turn_notifications_updated(session_id, decode_turn_notifications(rows[0][0], session_id=session_id))

    async def clear_turn_notifications(self, session_id: str) -> None:
        """Atomically clear all notification records when a new user turn begins."""
        statement = text(_CLEAR_NOTIFICATIONS_SQL)  # guard: raw-sql - the field is owned by this persistence seam
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.execute(statement, {_SESSION_ID_PARAMETER: session_id})
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, SessionField.TURN_NOTIFICATIONS_SENT.value, len(rows))
            if not rows:
                existing = await db_session.execute(
                    text(_SELECT_SESSION_EXISTENCE_SQL),
                    {_SESSION_ID_PARAMETER: session_id},
                )
                if existing.first() is None:
                    raise AgentStatusIntegrityError(session_id, SessionField.TURN_NOTIFICATIONS_SENT.value, 0)
                return
        _emit_turn_notifications_updated(session_id, frozenset())

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
    ) -> AgentStatusCommit:
        """Commit a full status record only if its version and lifecycle still match."""
        attempted_transition = _attempted_transition(cause, status)
        statement = (
            update(db_models.Session)
            .where(
                db_models.Session.session_id == session_id,
                db_models.Session.agent_status_version == expected_version,
                _session_open(),
            )
            .values(
                agent_status=status.value,
                agent_status_reason=reason.value if reason else _EMPTY_TEXT,
                agent_status_since=since,
                runtime_activity_at=runtime_activity_at,
                open_tool_calls=encode_open_tool_calls(open_tool_calls),
                agent_status_version=db_models.Session.agent_status_version + 1,
            )
            .returning(db_models.Session.session_id)
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, attempted_transition, len(rows))
            if rows:
                _emit_agent_status_updated(
                    session_id,
                    status=status,
                    reason=reason,
                    since=since,
                    runtime_activity_at=runtime_activity_at,
                    open_tool_calls=open_tool_calls,
                )
                return AgentStatusCommit.COMMITTED
            result = await db_session.exec(
                select(
                    db_models.Session.agent_status_version,
                    db_models.Session.closed_at,
                    db_models.Session.lifecycle_status,
                ).where(db_models.Session.session_id == session_id)
            )
            current = result.first()
        if current is None:
            raise AgentStatusIntegrityError(session_id, attempted_transition, 0)
        if current.closed_at is not None or current.lifecycle_status in TERMINAL_LIFECYCLE_STATUSES:
            return AgentStatusCommit.SESSION_TERMINAL
        return AgentStatusCommit.VERSION_MOVED

    async def list_inferred_stall_candidates(self, rule: InferredStallRule, *, at: datetime) -> list[str]:
        """List ids matching scalar rule clauses; the guarded write remains authoritative."""
        cutoff = at - timedelta(seconds=rule.window_s)
        statement = select(db_models.Session.session_id).where(
            *_inferred_stall_predicate(rule, cutoff, include_tool_call_guard=False)
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            return list(result.scalars().all())

    async def commit_inferred_stall(
        self,
        session_id: str,
        rule: InferredStallRule,
        *,
        at: datetime,
    ) -> CommittedStall | None:
        """Commit a stall only while its complete rule still holds for this row."""
        cutoff = at - timedelta(seconds=rule.window_s)
        attempted_transition = _attempted_transition(InferredStallVerdict(rule), AgentStatusValue.STALLED)
        statement = (
            update(db_models.Session)
            .where(
                db_models.Session.session_id == session_id,
                *_inferred_stall_predicate(rule, cutoff),
            )
            .values(
                agent_status=AgentStatusValue.STALLED.value,
                agent_status_reason=rule.reason.value,
                agent_status_since=at,
                agent_status_version=db_models.Session.agent_status_version + 1,
            )
            .returning(db_models.Session.runtime_activity_at)
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, attempted_transition, len(rows))
            if rows:
                _emit_inferred_stall_updated(session_id, reason=rule.reason, since=at)
                logger.info(_INFERRED_STALL_COMMITTED_EVENT, session_id=session_id, reason=rule.reason.value)
                return CommittedStall(runtime_activity_at=rows[0][0])
            result = await db_session.exec(
                select(db_models.Session.session_id).where(db_models.Session.session_id == session_id)
            )
            exists = result.first()
        if exists is None:
            raise AgentStatusIntegrityError(session_id, attempted_transition, 0)
        logger.debug(_INFERRED_STALL_RULE_MOVED_EVENT, session_id=session_id, reason=rule.reason.value)
        return None

    async def list_inferred_stall_ids(self) -> list[str]:
        """List open inferred stalls whose notification claim may need catch-up."""
        reasons = tuple(rule.reason.value for rule in INFERRED_STALL_RULES)
        statement = select(db_models.Session.session_id).where(
            _session_open(),
            db_models.Session.agent_status == AgentStatusValue.STALLED.value,
            db_models.Session.agent_status_reason.in_(reasons),
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            return list(result.scalars().all())
