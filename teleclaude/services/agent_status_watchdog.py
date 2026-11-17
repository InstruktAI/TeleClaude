"""Periodic host for stored agent-status watchdogs.

Each scan runs two isolated phases: claiming missing-signal observations for
silent targets, and reconciling a turn end the runtime completed but never
reported while control payloads or procedure events wait on it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core import tmux_bridge
from teleclaude.core.agent_status import TurnEndEvidence
from teleclaude.core.db import db
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.session_listeners import NotificationKind, SessionListener
from teleclaude.core.session_status import is_agent_turn_running, is_session_terminal
from teleclaude.core.session_transcript import session_transcript
from teleclaude.core.silence_audience import resolve_silence_audience
from teleclaude.core.supervisory_silence import SILENCE_RULES, SilenceClaim, SilenceObservation, SilenceRule
from teleclaude.utils.transcript._iterators import read_turn_completion

if TYPE_CHECKING:
    from teleclaude.core.models import Session


logger = get_logger(__name__)
AGENT_STATUS_WATCHDOG_INTERVAL_S = 10.0
_AGENT_STATUS_WATCHDOG_TASK_NAME = "agent-status-watchdog"
_WATCHDOG_ROW_FAILED_EVENT = "agent_status_watchdog_row_failed"
_WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT = "agent_status_watchdog_notification_not_delivered"
_INSPECTION_REFERENCE_TEMPLATE = "telec sessions tail {target_session_id} --pane"
_SILENCE_OCCURRENCE_KEY_TEMPLATE = "silence:{run_id}:{turn_id}:{kind}"
_EMPTY_SILENCE_TURN_ID = "-"
_SILENCE_DELIVERY_GENERATION_MOVED = "generation_moved"
_SILENCE_DELIVERY_AUDIENCE_REVOKED = "audience_revoked"


class WatchdogScanPhase(StrEnum):
    """One isolated phase of an agent-status watchdog scan."""

    CLAIM = "claim"
    RECONCILE = "reconcile"


class AgentStatusNotifier(Protocol):
    """Coordinator surface used to deliver an inferred stall and to record a reconciled turn end."""

    async def _notify_session_distress(
        self,
        target_session_id: str,
        notification_kind: NotificationKind,
        *,
        source_computer: str | None = None,
        observation: AgentAttentionObservation | None = None,
        silence_observation: SilenceObservation | None = None,
        occurrence_key: str | None = None,
        silence_audience: list[SessionListener] | None = None,
    ) -> bool: ...

    async def reconcile_native_turn_end(self, session_id: str, evidence: TurnEndEvidence) -> bool: ...


async def _capture_pane_tail(session: Session) -> str | None:
    """Capture bounded local startup evidence when a tmux pane exists."""
    if not session.tmux_session_name:
        return None
    try:
        pane_tail = await tmux_bridge.capture_pane(
            session.tmux_session_name,
            capture_lines=tmux_bridge.PANE_EVIDENCE_LINES,
        )
    except Exception as exc:
        logger.warning(
            "agent_status_watchdog_pane_capture_failed",
            session_id=session.session_id,
            error=str(exc),
        )
        return None
    return pane_tail or None


async def _notify_silence_observation(
    coordinator: AgentStatusNotifier,
    session: Session,
    rule: SilenceRule,
    claim: SilenceClaim,
    audience: list[SessionListener],
) -> None:
    pane_tail = await _capture_pane_tail(session)
    current_session = await db.get_session(session.session_id)
    if (
        current_session is None
        or current_session.runtime_run_id != claim.run_id
        or current_session.runtime_turn_id != claim.turn_id
    ):
        logger.info(
            _WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT,
            session_id=session.session_id,
            kind=claim.kind.value,
            reason=_SILENCE_DELIVERY_GENERATION_MOVED,
        )
        return
    current_audience = await resolve_silence_audience(session.session_id)
    current_pairs = {(listener.caller_session_id, listener.caller_computer) for listener in current_audience}
    audience = [
        listener for listener in audience if (listener.caller_session_id, listener.caller_computer) in current_pairs
    ]
    if not audience:
        logger.info(
            _WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT,
            session_id=session.session_id,
            kind=claim.kind.value,
            reason=_SILENCE_DELIVERY_AUDIENCE_REVOKED,
        )
        return
    observation = SilenceObservation(
        target_session_id=session.session_id,
        target_computer=config.computer.name,
        runtime=session.active_agent,
        run_id=claim.run_id,
        turn_id=claim.turn_id,
        kind=claim.kind,
        observed_at=claim.observed_at,
        clock_evidence_at=claim.clock_evidence_at,
        window_s=rule.window_s,
        silence_clock=rule.silence_clock,
        timeout_owner=rule.timeout_owner,
        pane_tail=pane_tail,
        pane_available=pane_tail is not None,
        inspection_reference=_INSPECTION_REFERENCE_TEMPLATE.format(target_session_id=session.session_id),
    )
    occurrence_key = _SILENCE_OCCURRENCE_KEY_TEMPLATE.format(
        run_id=claim.run_id,
        turn_id=claim.turn_id or _EMPTY_SILENCE_TURN_ID,
        kind=claim.kind.value,
    )
    delivered = await coordinator._notify_session_distress(
        session.session_id,
        NotificationKind.SILENCE_OBSERVATION,
        source_computer=config.computer.name,
        silence_observation=observation,
        occurrence_key=occurrence_key,
        silence_audience=audience,
    )
    if not delivered:
        logger.warning(
            _WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT,
            session_id=session.session_id,
            kind=claim.kind.value,
        )


async def _claim_silence_observations(coordinator: AgentStatusNotifier, *, at: datetime) -> int:
    claimed_count = 0
    for rule in SILENCE_RULES:
        for session_id in await db.list_silence_observation_candidates(rule, at=at):
            try:
                audience = await resolve_silence_audience(session_id)
                if not audience:
                    continue
                claim = await db.claim_silence_observation(session_id, rule, at=at)
                if claim is None:
                    continue
                claimed_count += 1
                session = await db.get_session(session_id)
                if (
                    session is None
                    or session.runtime_run_id != claim.run_id
                    or session.runtime_turn_id != claim.turn_id
                ):
                    logger.warning(
                        _WATCHDOG_NOTIFICATION_NOT_DELIVERED_EVENT,
                        session_id=session_id,
                        kind=rule.kind.value,
                    )
                    continue
                await _notify_silence_observation(coordinator, session, rule, claim, audience)
            except Exception as exc:
                logger.exception(
                    _WATCHDOG_ROW_FAILED_EVENT,
                    session_id=session_id,
                    phase=WatchdogScanPhase.CLAIM.value,
                    reason=str(exc),
                )
    return claimed_count


async def _reconcile_lost_turn_ends(coordinator: AgentStatusNotifier) -> int:
    """Record the provider-completed turn end of each session still believed running with work waiting.

    Waiting work is an undelivered control payload or a pending assigned procedure event.

    The snapshot is read first, then the native evidence, then the hook-ingress
    answer, so the coordinator's conditional commit rejects anything that
    happened after the snapshot.
    """
    reconciled_count = 0
    waiting_sessions = dict.fromkeys(
        [
            *await db.fetch_sessions_with_pending_control_payloads(),
            *await db.fetch_sessions_with_pending_procedure_events(),
        ]
    )
    for session_id in waiting_sessions:
        try:
            session = await db.get_session(session_id)
            if (
                session is None
                or session.computer_name != config.computer.name
                or not session.receives_terminal_input
                or is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at)
                or not is_agent_turn_running(
                    last_input_at=session.last_message_sent_at,
                    last_agent_stop_at=session.last_agent_stop_at,
                    last_agent_idle_at=session.last_agent_idle_at,
                )
            ):
                continue
            transcript = session_transcript(session)
            if transcript is None:
                continue
            completed_at = await asyncio.to_thread(read_turn_completion, transcript)
            if completed_at is None or await db.has_undispatched_hook_events(session_id):
                continue
            if await coordinator.reconcile_native_turn_end(session_id, TurnEndEvidence(completed_at, session)):
                reconciled_count += 1
        except Exception as exc:
            logger.exception(
                _WATCHDOG_ROW_FAILED_EVENT,
                session_id=session_id,
                phase=WatchdogScanPhase.RECONCILE.value,
                reason=str(exc),
            )
    return reconciled_count


async def scan_agent_status_once(
    coordinator: AgentStatusNotifier,
    *,
    now: datetime | None = None,
) -> int:
    """Claim current missing-signal observations per target, then reconcile lost turn ends."""
    observed_at = now or datetime.now(UTC)
    claimed_count = await _claim_silence_observations(coordinator, at=observed_at)
    return claimed_count + await _reconcile_lost_turn_ends(coordinator)


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
