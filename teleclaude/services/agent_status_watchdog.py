"""Periodic host for stored agent-status silence watchdogs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import tmux_bridge
from teleclaude.core.agent_status import (
    INFERRED_STALL_RULES,
    AgentStatusIntegrityError,
    InferredStallVerdict,
    transition_agent_status,
)
from teleclaude.core.db import db
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.session_listeners import (
    InferredStallEvidence,
    NotificationKind,
    build_inferred_stall_evidence,
)
from teleclaude.core.session_status import AgentStatusReason, TurnNotificationRecord

if TYPE_CHECKING:
    from teleclaude.core.models import Session


logger = get_logger(__name__)
AGENT_STATUS_WATCHDOG_INTERVAL_S = 10.0
AGENT_STATUS_PANE_CAPTURE_LINES = 40
_AGENT_STATUS_WATCHDOG_TASK_NAME = "agent-status-watchdog"
_CATCH_UP_ROW_LABEL = "catch_up_notification"
_WATCHDOG_ROW_FAILED_EVENT = "agent_status_watchdog_row_failed"
_WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT = "agent_status_watchdog_notification_not_delivered"


class WatchdogScanPhase(StrEnum):
    """One isolated phase of an agent-status watchdog scan."""

    CATCH_UP = "catch_up"
    VERDICT = "verdict"


class AgentStatusNotifier(Protocol):
    """Coordinator surface used to deliver an inferred stall to its audience."""

    async def _notify_session_distress(
        self,
        target_session_id: str,
        notification_kind: NotificationKind,
        source_computer: str | None = None,
        observation: AgentAttentionObservation | None = None,
        inferred_stall_evidence: InferredStallEvidence | None = None,
    ) -> bool: ...


async def _capture_pane_tail(session: Session) -> str | None:
    """Capture bounded local startup evidence when a tmux pane exists."""
    if not session.tmux_session_name:
        return None
    try:
        pane_tail = await tmux_bridge.capture_pane(
            session.tmux_session_name,
            capture_lines=AGENT_STATUS_PANE_CAPTURE_LINES,
        )
    except Exception as exc:
        logger.warning(
            "agent_status_watchdog_pane_capture_failed",
            session_id=session.session_id,
            error=str(exc),
        )
        return None
    return pane_tail or None


async def _notify_inferred_stall(
    coordinator: AgentStatusNotifier,
    session: Session,
    reason: AgentStatusReason,
    pane_tail: str | None,
) -> None:
    evidence = build_inferred_stall_evidence(reason, pane_tail)
    delivered = await coordinator._notify_session_distress(
        session.session_id,
        NotificationKind.TURN_FAILED,
        source_computer=config.computer.name,
        inferred_stall_evidence=evidence,
    )
    if not delivered:
        logger.warning(
            _WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT,
            session_id=session.session_id,
            reason=reason.value,
        )


async def _deliver_unclaimed_stall_notifications(coordinator: AgentStatusNotifier) -> None:
    for session_id in await db.list_inferred_stall_ids():
        try:
            session = await db.get_session(session_id)
            if session is None:
                raise AgentStatusIntegrityError(session_id, _CATCH_UP_ROW_LABEL, 0)
            reason = session.agent_status_reason
            if reason not in {rule.reason for rule in INFERRED_STALL_RULES}:
                continue
            if reason is None:
                continue
            if TurnNotificationRecord.INFERRED_STALL in session.turn_notifications_sent:
                continue
            pane_tail = await _capture_pane_tail(session) if reason is AgentStatusReason.NO_START else None
            await _notify_inferred_stall(coordinator, session, reason, pane_tail)
        except Exception as exc:
            logger.exception(
                _WATCHDOG_ROW_FAILED_EVENT,
                session_id=session_id,
                phase=WatchdogScanPhase.CATCH_UP.value,
                reason=str(exc),
            )


async def _apply_inferred_stall_verdicts(coordinator: AgentStatusNotifier, *, at: datetime) -> int:
    applied_count = 0
    for rule in INFERRED_STALL_RULES:
        for session_id in await db.list_inferred_stall_candidates(rule, at=at):
            try:
                transition = await transition_agent_status(
                    db,
                    session_id,
                    InferredStallVerdict(rule),
                    at=at,
                )
                if transition is None:
                    continue
                applied_count += 1
                session = await db.get_session(session_id)
                if session is None:
                    raise AgentStatusIntegrityError(session_id, rule.reason.value, 0)
                pane_tail = await _capture_pane_tail(session) if rule.reason is AgentStatusReason.NO_START else None
                await _notify_inferred_stall(coordinator, session, rule.reason, pane_tail)
            except Exception as exc:
                logger.exception(
                    _WATCHDOG_ROW_FAILED_EVENT,
                    session_id=session_id,
                    phase=WatchdogScanPhase.VERDICT.value,
                    reason=str(exc),
                )
    return applied_count


async def scan_agent_status_once(
    coordinator: AgentStatusNotifier,
    *,
    now: datetime | None = None,
) -> int:
    """Catch up old notifications, then apply current stall verdicts per row."""
    observed_at = now or datetime.now(UTC)
    await _deliver_unclaimed_stall_notifications(coordinator)
    return await _apply_inferred_stall_verdicts(coordinator, at=observed_at)


async def run_agent_status_watchdog(
    shutdown_event: asyncio.Event,
    coordinator: AgentStatusNotifier,
) -> None:
    """Scan local non-terminal sessions until the daemon begins shutdown."""
    while not shutdown_event.is_set():
        try:
            await scan_agent_status_once(coordinator)
        except Exception:
            logger.exception(_AGENT_STATUS_WATCHDOG_TASK_NAME + "_scan_failed")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=AGENT_STATUS_WATCHDOG_INTERVAL_S)
        except TimeoutError:
            continue
