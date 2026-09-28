"""Periodic host for stored agent-status silence watchdogs."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core import tmux_bridge
from teleclaude.core.agent_status import apply_inferred_stall, evaluate_watchdogs
from teleclaude.core.db import db
from teleclaude.core.db._agent_status import TURN_NOTIFICATION_SEPARATOR, TurnNotificationRecord
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.session_listeners import (
    InferredStallEvidence,
    NotificationKind,
    build_inferred_stall_evidence,
)
from teleclaude.core.session_status import AgentStatusReason, AgentStatusValue

if TYPE_CHECKING:
    from teleclaude.core.models import Session


logger = get_logger(__name__)
AGENT_STATUS_WATCHDOG_INTERVAL_S = 10.0
AGENT_STATUS_PANE_CAPTURE_LINES = 40
_AGENT_STATUS_WATCHDOG_TASK_NAME = "agent-status-watchdog"


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


async def scan_agent_status_once(
    coordinator: AgentStatusNotifier,
    *,
    now: datetime | None = None,
) -> int:
    """Apply current watchdog verdicts and notify the audience with observed evidence."""
    observed_at = now or datetime.now(UTC)
    sessions = await db.list_sessions(all_open=True)
    transitions = 0
    for session in sessions:
        reason = evaluate_watchdogs(session, observed_at)
        pane_tail: str | None = None
        if reason is not None:
            pane_tail = await _capture_pane_tail(session) if reason is AgentStatusReason.NO_START else None
            transition = await apply_inferred_stall(db, session.session_id, reason, at=observed_at)
            if transition is not None:
                transitions += 1
            else:
                reason = None

        if reason is None and session.agent_status is AgentStatusValue.STALLED:
            if session.agent_status_reason not in {AgentStatusReason.NO_SIGNAL, AgentStatusReason.NO_START}:
                continue
            recorded = {
                TurnNotificationRecord(value)
                for value in session.turn_notifications_sent.split(TURN_NOTIFICATION_SEPARATOR)
                if value
            }
            if TurnNotificationRecord.INFERRED_STALL in recorded:
                continue
            reason = session.agent_status_reason
            pane_tail = await _capture_pane_tail(session) if reason is AgentStatusReason.NO_START else None
        elif reason is None:
            continue

        if reason is None:
            continue
        evidence = build_inferred_stall_evidence(reason, pane_tail)
        try:
            delivered = await coordinator._notify_session_distress(
                session.session_id,
                NotificationKind.TURN_FAILED,
                source_computer=config.computer.name,
                inferred_stall_evidence=evidence,
            )
            if not delivered:
                logger.warning(
                    "agent_status_watchdog_notification_not_delivered",
                    session_id=session.session_id,
                    reason=reason.value,
                )
        except Exception:
            logger.exception(
                "agent_status_watchdog_notification_failed",
                session_id=session.session_id,
                reason=reason.value,
            )
    return transitions


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
