"""Recover a Codex completion whose provider Stop hook was not delivered."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import CODEX_HOOK_STOP_TIMEOUT_SEC
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import AgentHookEvents, AgentStopCompletionSource
from teleclaude.core.session_status import SessionLifecycleStatus
from teleclaude.utils.transcript import CodexTaskLifecycleKind, extract_latest_codex_task_lifecycle

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)
_AGENT_STOP_RECOVERY_DECIDED_EVENT = "agent_stop_recovery_decided"


class CodexStopRecoveryOutcome(StrEnum):
    """Closed outcomes for recovery scheduling decisions."""

    SCHEDULED = "scheduled"
    REJECTED = "rejected"
    ENQUEUED = "enqueued"
    FAILED = "failed"


class CodexStopRecoveryReason(StrEnum):
    """Closed reasons for accepting or rejecting a recovery candidate."""

    ABORTED = "aborted"
    AWAITING_STOP_BUDGET = "awaiting_stop_budget"
    ELIGIBLE = "eligible"
    NOT_NEWER_THAN_INPUT = "not_newer_than_input"
    SUPERSEDED_LIFECYCLE = "superseded_lifecycle"
    SUPERSEDED_INPUT = "superseded_input"
    ORDINARY_STOP_RECORDED = "ordinary_stop_recorded"
    SESSION_NOT_LIVE = "session_not_live"
    ENQUEUE_FAILED = "enqueue_failed"


_pending_recoveries: dict[tuple[str, str], asyncio.Task[None]] = {}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _is_live_codex_session(session: Session) -> bool:
    """Return whether a session can still own a recovered Codex completion."""
    return (
        session.active_agent == AgentName.CODEX.value
        and session.runtime_start_observed
        and session.lifecycle_status == SessionLifecycleStatus.ACTIVE
        and session.closed_at is None
        and bool(session.native_session_id)
    )


def _record_decision(
    *,
    session_id: str,
    native_session_id: str | None,
    turn_id: str,
    outcome: CodexStopRecoveryOutcome,
    reason: CodexStopRecoveryReason,
    completed_at: datetime,
    accepted_input_at: datetime,
) -> None:
    """Emit one body-free decision with stable correlation fields."""
    logger.info(
        _AGENT_STOP_RECOVERY_DECIDED_EVENT,
        session_id=session_id,
        native_session_id=native_session_id,
        native_turn_id=turn_id,
        outcome=outcome.value,
        reason=reason.value,
        native_completed_at=completed_at.isoformat(),
        accepted_input_at=accepted_input_at.isoformat(),
    )


async def schedule_codex_stop_recovery(session: Session) -> None:
    """Schedule one delayed recovery when native completion outlives the Stop budget."""
    if not _is_live_codex_session(session) or not session.native_log_file:
        return
    observation = extract_latest_codex_task_lifecycle(session.native_log_file)
    if observation is None:
        return
    accepted_input_at = _as_utc(session.last_message_sent_at)
    if accepted_input_at is None:
        return
    if observation.kind is CodexTaskLifecycleKind.ABORTED:
        _record_decision(
            session_id=session.session_id,
            native_session_id=session.native_session_id,
            turn_id=observation.turn_id,
            outcome=CodexStopRecoveryOutcome.REJECTED,
            reason=CodexStopRecoveryReason.ABORTED,
            completed_at=observation.occurred_at,
            accepted_input_at=accepted_input_at,
        )
        return
    if observation.kind is not CodexTaskLifecycleKind.COMPLETED:
        return
    if observation.occurred_at <= accepted_input_at:
        _record_decision(
            session_id=session.session_id,
            native_session_id=session.native_session_id,
            turn_id=observation.turn_id,
            outcome=CodexStopRecoveryOutcome.REJECTED,
            reason=CodexStopRecoveryReason.NOT_NEWER_THAN_INPUT,
            completed_at=observation.occurred_at,
            accepted_input_at=accepted_input_at,
        )
        return

    key = (session.session_id, observation.turn_id)
    pending = _pending_recoveries.get(key)
    if pending is not None and not pending.done():
        return
    deadline = (
        observation.occurred_at.timestamp()
        + CODEX_HOOK_STOP_TIMEOUT_SEC
        + max(0.0, float(config.polling.output_cadence_s))
    )
    task = asyncio.create_task(
        _enqueue_recovery(
            session_id=session.session_id,
            native_session_id=session.native_session_id,
            turn_id=observation.turn_id,
            completed_at=observation.occurred_at,
            accepted_input_at=accepted_input_at,
            deadline=deadline,
        ),
        name=f"recover-codex-stop-{session.session_id}-{observation.turn_id}",
    )
    _pending_recoveries[key] = task

    def clear_completed_recovery(completed_task: asyncio.Task[None]) -> None:
        if _pending_recoveries.get(key) is completed_task:
            _pending_recoveries.pop(key, None)

    task.add_done_callback(clear_completed_recovery)
    _record_decision(
        session_id=session.session_id,
        native_session_id=session.native_session_id,
        turn_id=observation.turn_id,
        outcome=CodexStopRecoveryOutcome.SCHEDULED,
        reason=CodexStopRecoveryReason.AWAITING_STOP_BUDGET,
        completed_at=observation.occurred_at,
        accepted_input_at=accepted_input_at,
    )


def cancel_codex_stop_recoveries(session_id: str) -> None:
    """Cancel all recovery candidates owned by a poller that is ending."""
    for key, task in tuple(_pending_recoveries.items()):
        if key[0] != session_id:
            continue
        task.cancel()
        _pending_recoveries.pop(key, None)


async def _enqueue_recovery(
    *,
    session_id: str,
    native_session_id: str | None,
    turn_id: str,
    completed_at: datetime,
    accepted_input_at: datetime,
    deadline: float,
) -> None:
    """Re-read durable state at the deadline before enqueuing one ordinary stop event."""
    try:
        await asyncio.sleep(max(0.0, deadline - datetime.now(UTC).timestamp()))
        session = await db.get_session(session_id)
        if session is None or not _is_live_codex_session(session) or not session.native_log_file:
            _record_decision(
                session_id=session_id,
                native_session_id=native_session_id,
                turn_id=turn_id,
                outcome=CodexStopRecoveryOutcome.REJECTED,
                reason=CodexStopRecoveryReason.SESSION_NOT_LIVE,
                completed_at=completed_at,
                accepted_input_at=accepted_input_at,
            )
            return
        latest = extract_latest_codex_task_lifecycle(session.native_log_file)
        if (
            latest is None
            or latest.kind is not CodexTaskLifecycleKind.COMPLETED
            or latest.turn_id != turn_id
            or latest.occurred_at != completed_at
        ):
            _record_decision(
                session_id=session_id,
                native_session_id=native_session_id,
                turn_id=turn_id,
                outcome=CodexStopRecoveryOutcome.REJECTED,
                reason=CodexStopRecoveryReason.SUPERSEDED_LIFECYCLE,
                completed_at=completed_at,
                accepted_input_at=accepted_input_at,
            )
            return
        if _as_utc(session.last_message_sent_at) != accepted_input_at:
            _record_decision(
                session_id=session_id,
                native_session_id=native_session_id,
                turn_id=turn_id,
                outcome=CodexStopRecoveryOutcome.REJECTED,
                reason=CodexStopRecoveryReason.SUPERSEDED_INPUT,
                completed_at=completed_at,
                accepted_input_at=accepted_input_at,
            )
            return
        last_stop_at = _as_utc(session.last_agent_stop_at)
        if last_stop_at is not None and last_stop_at >= completed_at:
            _record_decision(
                session_id=session_id,
                native_session_id=native_session_id,
                turn_id=turn_id,
                outcome=CodexStopRecoveryOutcome.REJECTED,
                reason=CodexStopRecoveryReason.ORDINARY_STOP_RECORDED,
                completed_at=completed_at,
                accepted_input_at=accepted_input_at,
            )
            return
        await db.enqueue_hook_event(
            session_id,
            AgentHookEvents.AGENT_STOP.value,
            {
                "session_id": session.native_session_id,
                "transcript_path": session.native_log_file,
                "agent_name": AgentName.CODEX.value,
                "completion_source": AgentStopCompletionSource.CODEX_TASK_RECOVERY.value,
                "native_turn_id": turn_id,
                "native_completed_at": completed_at.isoformat(),
                "accepted_input_at": accepted_input_at.isoformat(),
            },
        )
        _record_decision(
            session_id=session_id,
            native_session_id=native_session_id,
            turn_id=turn_id,
            outcome=CodexStopRecoveryOutcome.ENQUEUED,
            reason=CodexStopRecoveryReason.ELIGIBLE,
            completed_at=completed_at,
            accepted_input_at=accepted_input_at,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        _record_decision(
            session_id=session_id,
            native_session_id=native_session_id,
            turn_id=turn_id,
            outcome=CodexStopRecoveryOutcome.FAILED,
            reason=CodexStopRecoveryReason.ENQUEUE_FAILED,
            completed_at=completed_at,
            accepted_input_at=accepted_input_at,
        )
