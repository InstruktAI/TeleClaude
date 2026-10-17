"""Typed persistence adapter for agent-status transitions and notification gates."""

from __future__ import annotations

import json
from collections.abc import Set
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict, cast

from instrukt_ai_logging import get_logger
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import aliased
from sqlmodel.ext.asyncio.session import AsyncSession as SqlAsyncSession

from teleclaude.config.machine import config
from teleclaude.core import db_models
from teleclaude.core.agent_status import (
    AgentEventCause,
    AgentRunStart,
    AgentStatusCause,
    AgentStatusCommit,
    AgentStatusIntegrityError,
    _attempted_transition,
)
from teleclaude.core.models import SessionField
from teleclaude.core.runtime_events import publish_session_source_change
from teleclaude.core.session_status import (
    TERMINAL_LIFECYCLE_STATUSES,
    AgentStatusReason,
    AgentStatusValue,
    TurnNotificationRecord,
)
from teleclaude.core.supervisory_silence import (
    SilenceClaim,
    SilenceClock,
    SilenceObservationKind,
    SilenceRule,
)
from teleclaude.events.schemas.system import RuntimeSessionChange

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
_SESSION_ID_PARAMETER = "session_id"
_RECORD_PARAMETER = "record"
_TERMINAL_PARAMETER = "terminal"
_TERMINAL_END_PARAMETER = "terminal_end"
_TERMINAL_FAILED_PARAMETER = "terminal_failed"
_MULTIPLE_CLAIM_ROWS_ERROR = "claim_turn_notification updated multiple rows for session %s"
_MISSING_CLAIM_SESSION_ERROR = "claim_turn_notification found no session %s"
_AGENT_STATUS_ROW_COUNT_ERROR = "Agent status transition %s for session %s affected %s rows"
_EMPTY_TEXT = ""
_EMPTY_JSON_ARRAY = "[]"
_SILENCE_CLAIM_CONFLICT_EVENT = "silence_observation_claim_rejected"
_SILENCE_OBSERVATION_CLAIMED_EVENT = "silence_observation_claimed"

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
    runtime_run_id: str | None
    runtime_turn_id: str | None


async def _emit_turn_notifications_updated(session_id: str, records: frozenset[TurnNotificationRecord]) -> None:
    await publish_session_source_change(
        session_id,
        RuntimeSessionChange.UPDATED,
        changed_fields=(SessionField.TURN_NOTIFICATIONS_SENT.value,),
    )


async def _emit_agent_status_updated(
    session_id: str,
    *,
    status: AgentStatusValue,
    reason: AgentStatusReason | None,
    since: datetime | None,
    runtime_activity_at: datetime | None,
    open_tool_calls: frozenset[str],
    runtime_run_id: str | None,
    runtime_turn_id: str | None,
) -> None:
    updated_fields = _AgentStatusUpdatedFields(
        agent_status=status.value,
        agent_status_reason=reason.value if reason else _EMPTY_TEXT,
        agent_status_since=since,
        runtime_activity_at=runtime_activity_at,
        open_tool_calls=sorted(open_tool_calls),
        runtime_run_id=runtime_run_id,
        runtime_turn_id=runtime_turn_id,
    )
    await publish_session_source_change(
        session_id,
        RuntimeSessionChange.UPDATED,
        changed_fields=tuple(updated_fields),
    )


def _session_open() -> object:
    terminal_statuses = tuple(status.value for status in TERMINAL_LIFECYCLE_STATUSES)
    return db_models.Session.closed_at.is_(None) & or_(
        db_models.Session.lifecycle_status.is_(None),
        db_models.Session.lifecycle_status.not_in(terminal_statuses),
    )


def _silence_observation_predicate(
    rule: SilenceRule,
    cutoff: datetime,
) -> object:
    predicate = [
        _session_open(),
        db_models.Session.agent_status == rule.status.value,
        db_models.Session.runtime_run_id.is_not(None),
    ]
    if rule.kind is SilenceObservationKind.ACTIVE_TURN:
        predicate.append(db_models.Session.runtime_turn_id.is_not(None))
    if rule.tool_calls_must_be_closed:
        predicate.append(func.json_array_length(db_models.Session.open_tool_calls) == 0)
    if rule.agent_must_be_assigned:
        predicate.extend(
            [
                db_models.Session.active_agent.is_not(None),
                db_models.Session.active_agent != _EMPTY_TEXT,
            ]
        )
    listener_query = select(db_models.SessionListenerRow.caller_session_id).where(
        db_models.SessionListenerRow.target_session_id == db_models.Session.session_id,
        db_models.SessionListenerRow.caller_session_id != db_models.Session.session_id,
        db_models.SessionListenerRow.one_shot.is_(False),
    )
    if rule.kind is SilenceObservationKind.STARTUP:
        listener_query = listener_query.where(
            db_models.SessionListenerRow.startup_run_id == db_models.Session.runtime_run_id
        )
    caller_session = aliased(db_models.Session)
    local_caller = select(caller_session.session_id).where(
        caller_session.session_id == db_models.SessionListenerRow.caller_session_id,
        caller_session.closed_at.is_(None),
        or_(
            caller_session.lifecycle_status.is_(None),
            caller_session.lifecycle_status.not_in(tuple(status.value for status in TERMINAL_LIFECYCLE_STATUSES)),
        ),
        caller_session.tmux_session_name.is_not(None),
        caller_session.tmux_session_name != _EMPTY_TEXT,
    )
    remote_caller = db_models.SessionListenerRow.caller_computer.is_not(None) & (
        db_models.SessionListenerRow.caller_computer != config.computer.name
    )
    listener_query = listener_query.where(or_(local_caller.exists(), remote_caller))
    predicate.append(listener_query.exists())
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
                await _emit_turn_notifications_updated(session_id, records)
                return True, records
            result = await db_session.execute(
                text(_SELECT_TURN_NOTIFICATIONS_SQL),
                {_SESSION_ID_PARAMETER: session_id},
            )
            stored = result.first()
            if stored is None:
                raise AgentStatusIntegrityError(session_id, record.value, 0)
            return False, decode_turn_notifications(stored[0], session_id=session_id)

    async def install_runtime_run(self, session_id: str, runtime_run_id: str) -> bool:
        """Install one launch identity and clear its predecessor's start evidence atomically."""
        statement = (
            update(db_models.Session)
            .where(db_models.Session.session_id == session_id, _session_open())
            .values(
                runtime_run_id=runtime_run_id,
                runtime_start_observed=False,
                agent_status_version=db_models.Session.agent_status_version + 1,
            )
            .returning(db_models.Session.session_id)
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            await db_session.commit()
        if len(rows) > 1:
            attempted = _attempted_transition(AgentRunStart(run_id=runtime_run_id), AgentStatusValue.UNKNOWN)
            raise AgentStatusIntegrityError(session_id, attempted, len(rows))
        return bool(rows)

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
    ) -> AgentStatusCommit:
        """Commit a full status record only if its version and lifecycle still match."""
        attempted_transition = _attempted_transition(cause, status)
        reset_notifications = isinstance(cause, AgentRunStart) or (
            isinstance(cause, AgentEventCause) and cause.new_turn
        )
        conditions = [
            db_models.Session.session_id == session_id,
            db_models.Session.agent_status_version == expected_version,
            _session_open(),
        ]
        if expected_runtime_run_id is not None:
            conditions.append(db_models.Session.runtime_run_id == expected_runtime_run_id)
        statement = (
            update(db_models.Session)
            .where(*conditions)
            .values(
                agent_status=status.value,
                agent_status_reason=reason.value if reason else _EMPTY_TEXT,
                agent_status_since=since,
                runtime_activity_at=runtime_activity_at,
                open_tool_calls=encode_open_tool_calls(open_tool_calls),
                runtime_run_id=runtime_run_id,
                runtime_turn_id=runtime_turn_id,
                turn_notifications_sent=(
                    _EMPTY_JSON_ARRAY if reset_notifications else db_models.Session.turn_notifications_sent
                ),
                agent_status_version=db_models.Session.agent_status_version + 1,
            )
            .returning(db_models.Session.session_id)
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            if rows and isinstance(cause, AgentRunStart):
                await db_session.exec(
                    update(db_models.SessionListenerRow)
                    .where(
                        db_models.SessionListenerRow.target_session_id == session_id,
                        db_models.SessionListenerRow.one_shot.is_(False),
                    )
                    .values(startup_run_id=runtime_run_id if cause.startup_work_expected else None)
                )
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, attempted_transition, len(rows))
            if rows:
                if reset_notifications:
                    await _emit_turn_notifications_updated(session_id, frozenset())
                await _emit_agent_status_updated(
                    session_id,
                    status=status,
                    reason=reason,
                    since=since,
                    runtime_activity_at=runtime_activity_at,
                    open_tool_calls=open_tool_calls,
                    runtime_run_id=runtime_run_id,
                    runtime_turn_id=runtime_turn_id,
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

    async def list_silence_observation_candidates(self, rule: SilenceRule, *, at: datetime) -> list[str]:
        """List targets matching the current run, activity, and supervisor relationship."""
        cutoff = at - timedelta(seconds=rule.window_s)
        statement = select(db_models.Session.session_id).where(*_silence_observation_predicate(rule, cutoff))
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            return list(result.scalars().all())

    async def claim_silence_observation(
        self,
        session_id: str,
        rule: SilenceRule,
        *,
        at: datetime,
    ) -> SilenceClaim | None:
        """Claim one current run/turn observation without changing recorded activity."""
        cutoff = at - timedelta(seconds=rule.window_s)
        unclaimed = text(
            "NOT EXISTS (SELECT 1 FROM json_each(sessions.turn_notifications_sent) WHERE value = :silence_claim)"
        ).bindparams(silence_claim=TurnNotificationRecord.INFERRED_STALL.value)
        statement = (
            update(db_models.Session)
            .where(
                db_models.Session.session_id == session_id,
                *_silence_observation_predicate(rule, cutoff),
                unclaimed,
            )
            .values(
                turn_notifications_sent=func.json_insert(
                    db_models.Session.turn_notifications_sent,
                    "$[#]",
                    TurnNotificationRecord.INFERRED_STALL.value,
                ),
                agent_status_version=db_models.Session.agent_status_version + 1,
            )
            .returning(
                db_models.Session.runtime_run_id,
                db_models.Session.runtime_turn_id,
                db_models.Session.runtime_activity_at,
                db_models.Session.agent_status_since,
                db_models.Session.turn_notifications_sent,
            )
        )
        async with cast(_AgentStatusDatabase, self)._session() as db_session:
            result = await db_session.exec(statement)
            rows = result.all()
            await db_session.commit()
            if len(rows) > 1:
                raise AgentStatusIntegrityError(session_id, rule.kind.value, len(rows))
            if not rows:
                logger.debug(_SILENCE_CLAIM_CONFLICT_EVENT, session_id=session_id, kind=rule.kind.value)
                return None
        runtime_run_id, runtime_turn_id, runtime_activity_at, status_since, raw_notifications = rows[0]
        if not isinstance(runtime_run_id, str) or not runtime_run_id:
            raise AgentStatusIntegrityError(session_id, rule.kind.value, 0)
        clock_evidence_at = (
            runtime_activity_at
            if rule.silence_clock is SilenceClock.LAST_SIGNAL
            and runtime_activity_at is not None
            and (status_since is None or runtime_activity_at >= status_since)
            else status_since
        )
        if clock_evidence_at is None:
            raise AgentStatusIntegrityError(session_id, rule.kind.value, 0)
        if clock_evidence_at.tzinfo is None:
            clock_evidence_at = clock_evidence_at.replace(tzinfo=UTC)
        else:
            clock_evidence_at = clock_evidence_at.astimezone(UTC)
        await _emit_turn_notifications_updated(
            session_id,
            decode_turn_notifications(raw_notifications, session_id=session_id),
        )
        logger.info(
            _SILENCE_OBSERVATION_CLAIMED_EVENT,
            session_id=session_id,
            run_id=runtime_run_id,
            turn_id=runtime_turn_id,
            kind=rule.kind.value,
        )
        return SilenceClaim(
            target_session_id=session_id,
            run_id=runtime_run_id,
            turn_id=runtime_turn_id,
            kind=rule.kind,
            observed_at=at,
            clock_evidence_at=clock_evidence_at,
        )
