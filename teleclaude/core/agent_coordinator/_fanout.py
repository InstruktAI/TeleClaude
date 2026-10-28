"""Extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import json
import random
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal, cast
from uuid import uuid4

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.config.machine import config
from teleclaude.constants import LOCAL_COMPUTER, SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.inbound.fleet import FleetView, observe_fleet
from teleclaude.core.models import MessageMetadata, Session, SessionOriginMetadata
from teleclaude.core.reconciliation import SUPERVISORY_SILENCE_OBSERVATIONS_FEATURE_ID
from teleclaude.core.session_listeners import (
    DELIVERY_BLOCK_EVIDENCE_METADATA_KEY,
    DELIVERY_BLOCK_PANE_TAIL_FIELD,
    INFERRED_STALL_EVIDENCE_METADATA_KEY,
    INFERRED_STALL_PANE_TAIL_FIELD,
    INFERRED_STALL_REASON_FIELD,
    STARTUP_DELIVERY_UNCERTAIN_EVIDENCE_METADATA_KEY,
    DeliveryBlockEvidence,
    InferredStallEvidence,
    NotificationKind,
    SessionListener,
    StartupDeliveryUncertainEvidence,
    StopNotificationVariant,
    notify_distress,
    notify_distress_human_fallback,
    notify_stop,
)
from teleclaude.core.session_output import StopOutputKind, StopOutputResult
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.core.session_status import TurnNotificationRecord
from teleclaude.core.summarizer import summarize_agent_output
from teleclaude.core.supervisory_silence import SilenceObservation
from teleclaude.tts.manager import TTSManager
from teleclaude.utils.transcript._extraction import extract_stop_agent_output

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.events import AgentStopPayload

logger = get_logger(__name__)
_DISTRESS_COMMAND = "/distress_notification {session_id} {computer} {caller} {kind} {title} {occurrence} {occurred_at}"
_STOP_NOTIFICATION_COMMAND = (
    "/stop_notification {session_id} {computer} {caller} {title} {occurrence} {variant} {occurred_at}"
)
_WIRE_ABSENT = "-"
_ATTENTION_METADATA_KEY: Final[Literal["attention_observation"]] = "attention_observation"
_ATTENTION_PROVIDER_KEY = "provider"
_ATTENTION_NATIVE_EVENT_KEY = "native_event"
_ATTENTION_DETAILS_KEY = "details"
_ATTENTION_OBSERVED_AT_KEY = "observed_at"
_ATTENTION_INGRESS_ID_KEY = "ingress_id"
_SILENCE_OBSERVATION_METADATA_KEY: Final[Literal["silence_observation"]] = "silence_observation"
_SILENCE_TARGET_SESSION_ID_KEY = "target_session_id"
_SILENCE_TARGET_COMPUTER_KEY = "target_computer"
_SILENCE_RUNTIME_KEY = "runtime"
_SILENCE_RUN_ID_KEY = "run_id"
_SILENCE_TURN_ID_KEY = "turn_id"
_SILENCE_KIND_KEY = "kind"
_SILENCE_OBSERVED_AT_KEY = "observed_at"
_SILENCE_CLOCK_EVIDENCE_AT_KEY = "clock_evidence_at"
_SILENCE_WINDOW_KEY = "window_s"
_SILENCE_CLOCK_KEY = "silence_clock"
_SILENCE_TIMEOUT_OWNER_KEY = "timeout_owner"
_SILENCE_PANE_TAIL_KEY = "pane_tail"
_SILENCE_PANE_AVAILABLE_KEY = "pane_available"
_SILENCE_INSPECTION_REFERENCE_KEY = "inspection_reference"
_DISTRESS_OUTCOME_SUBSCRIBER_DELIVERY = "subscriber_delivery"
_DISTRESS_OUTCOME_HUMAN_FALLBACK = "human_fallback"
_DISTRESS_OUTCOME_NO_FALLBACK = "no_fallback"
_DISTRESS_NO_FALLBACK_BLOCKED_ALREADY_OBSERVED = "blocked_already_observed_this_turn"
_SILENCE_REMOTE_DELIVERY_OUTCOME_EVENT = "silence_observation_remote_delivery_outcome"
_SILENCE_REMOTE_CAPABILITY_UNAVAILABLE_EVENT = "silence_observation_remote_capability_unavailable"
_SILENCE_PEER_CAPABILITY_MISSING = "feature_not_advertised"
_SILENCE_PEER_VIEW_UNAVAILABLE = "peer_view_unavailable"


class _SilenceDeliveryOutcome(StrEnum):
    """Outcome of one remote silence-observation handoff."""

    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"


def _wire_moment(value: datetime | None) -> str:
    """Encode an occurrence moment as one whitespace-free transport argument."""
    return value.astimezone(UTC).isoformat() if value is not None else _WIRE_ABSENT


def _attention_observation_metadata(
    observation: AgentAttentionObservation | None,
    inferred_stall_evidence: InferredStallEvidence | None,
    delivery_block_evidence: DeliveryBlockEvidence | None,
    startup_delivery_uncertain_evidence: StartupDeliveryUncertainEvidence | None,
    silence_observation: SilenceObservation | None = None,
) -> SessionOriginMetadata:
    """Serialize native or daemon-observed evidence for the remote parent path."""
    metadata: SessionOriginMetadata = cast(SessionOriginMetadata, {})
    if observation is not None:
        metadata[_ATTENTION_METADATA_KEY] = {
            _ATTENTION_PROVIDER_KEY: observation.provider,
            _ATTENTION_NATIVE_EVENT_KEY: observation.native_event,
            _ATTENTION_DETAILS_KEY: dict(observation.details),
            _ATTENTION_OBSERVED_AT_KEY: observation.observed_at.isoformat() if observation.observed_at else None,
            _ATTENTION_INGRESS_ID_KEY: observation.ingress_id,
        }
    if inferred_stall_evidence is not None:
        metadata[INFERRED_STALL_EVIDENCE_METADATA_KEY] = {
            INFERRED_STALL_REASON_FIELD: inferred_stall_evidence.reason.value,
            INFERRED_STALL_PANE_TAIL_FIELD: inferred_stall_evidence.pane_tail,
        }
    if delivery_block_evidence is not None:
        metadata[DELIVERY_BLOCK_EVIDENCE_METADATA_KEY] = {
            DELIVERY_BLOCK_PANE_TAIL_FIELD: delivery_block_evidence.pane_tail,
        }
    if startup_delivery_uncertain_evidence is not None:
        metadata[STARTUP_DELIVERY_UNCERTAIN_EVIDENCE_METADATA_KEY] = {}
    if silence_observation is not None:
        metadata[_SILENCE_OBSERVATION_METADATA_KEY] = {
            _SILENCE_TARGET_SESSION_ID_KEY: silence_observation.target_session_id,
            _SILENCE_TARGET_COMPUTER_KEY: silence_observation.target_computer,
            _SILENCE_RUNTIME_KEY: silence_observation.runtime,
            _SILENCE_RUN_ID_KEY: silence_observation.run_id,
            _SILENCE_TURN_ID_KEY: silence_observation.turn_id,
            _SILENCE_KIND_KEY: silence_observation.kind.value,
            _SILENCE_OBSERVED_AT_KEY: (
                silence_observation.observed_at.isoformat() if silence_observation.observed_at else None
            ),
            _SILENCE_CLOCK_EVIDENCE_AT_KEY: (
                silence_observation.clock_evidence_at.isoformat() if silence_observation.clock_evidence_at else None
            ),
            _SILENCE_WINDOW_KEY: silence_observation.window_s,
            _SILENCE_CLOCK_KEY: silence_observation.silence_clock.value,
            _SILENCE_TIMEOUT_OWNER_KEY: (
                silence_observation.timeout_owner.value if silence_observation.timeout_owner else None
            ),
            _SILENCE_PANE_TAIL_KEY: silence_observation.pane_tail,
            _SILENCE_PANE_AVAILABLE_KEY: silence_observation.pane_available,
            _SILENCE_INSPECTION_REFERENCE_KEY: silence_observation.inspection_reference,
        }
    return metadata


class _FanoutMixin:  # pyright: ignore[reportUnusedClass]
    """Extraction, fanout, TTS, snapshot, and notification methods for AgentCoordinator."""

    if TYPE_CHECKING:
        client: "AdapterClient"
        tts_manager: TTSManager

    async def _speak_session_start(self, session_id: str) -> None:
        if not SESSION_START_MESSAGES:
            return
        message = random.choice(SESSION_START_MESSAGES)
        try:
            await self.tts_manager.speak(message, session_id=session_id)
        except Exception as exc:
            logger.warning("TTS session_start failed: %s", exc)

    async def _extract_agent_output(
        self, session_id: str, payload: "AgentStopPayload", *, response_entry_id: str | None = None
    ) -> StopOutputResult:
        """Extract the corresponding stop response without falling back to history."""
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Extract skipped (missing transcript path)", session=session_id)
            return StopOutputResult(StopOutputKind.UNAVAILABLE)

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Extract skipped (missing agent name)", session=session_id)
            return StopOutputResult(StopOutputKind.UNAVAILABLE)

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Extract skipped (unknown agent '%s')", agent_name_value)
            return StopOutputResult(StopOutputKind.UNAVAILABLE)

        return extract_stop_agent_output(transcript_path, agent_name, response_entry_id=response_entry_id)

    async def _summarize_output(self, session_id: str, raw_output: str) -> str | None:
        """Summarize raw agent output via LLM.

        Returns:
            Summary text, or None if summarization fails.
        """
        if not raw_output.strip():
            logger.debug("Summarization skipped (empty normalized output)", session=session_id)
            return None
        try:
            _title, summary = await summarize_agent_output(raw_output)
            return summary
        except Exception as exc:
            logger.warning("Summarization failed: %s", exc, extra={"session_id": session_id})
            return None

    async def _notify_session_listener(
        self,
        target_session_id: str,
        *,
        variant: StopNotificationVariant,
        source_computer: str | None = None,
        title_override: str | None = None,
        occurred_at: datetime | None,
    ) -> None:
        """Notify local listeners via tmux injection (once per turn).

        Terminal outcomes contend for one per-turn notification slot.
        """
        claimed, _records = await db.claim_turn_notification(
            target_session_id, TurnNotificationRecord.TERMINAL_TURN_END
        )
        if not claimed:
            logger.debug(
                "Skipping duplicate stop notification for session %s (already notified this turn)",
                target_session_id,
            )
            return
        target_session = await db.get_session(target_session_id)
        display_title = title_override or (target_session.title if target_session else "Unknown")
        # Strip additional context appended during session dispatch — it bloats notifications.
        if "\n\nADDITIONAL CONTEXT" in display_title:
            display_title = display_title.split("\n\nADDITIONAL CONTEXT")[0]
        computer = source_computer or LOCAL_COMPUTER
        await notify_stop(
            target_session_id,
            computer,
            title=display_title,
            variant=variant,
            occurred_at=occurred_at,
        )

    async def _notify_session_distress(
        self,
        target_session_id: str,
        notification_kind: NotificationKind,
        source_computer: str | None = None,
        observation: AgentAttentionObservation | None = None,
        inferred_stall_evidence: InferredStallEvidence | None = None,
        delivery_block_evidence: DeliveryBlockEvidence | None = None,
        startup_delivery_uncertain_evidence: StartupDeliveryUncertainEvidence | None = None,
        occurrence_key: str | None = None,
        silence_observation: SilenceObservation | None = None,
        silence_audience: list[SessionListener] | None = None,
    ) -> bool:
        """Notify parents while retaining terminal and fallback slot semantics.

        Delivery-observed block evidence is a native-style blocked occurrence:
        it claims the blocked slot and follows the blocked fallback rules. Only
        an inferred stall claims its own slot. An uncertain startup delivery
        claims none, so the target's later turn notifications are unaffected,
        and its caller-supplied occurrence key makes a retried report reuse the
        payload already recorded for a watcher.
        """
        blocked_claimed = True
        if startup_delivery_uncertain_evidence is not None:
            pass
        elif silence_observation is not None:
            pass
        elif inferred_stall_evidence is None:
            record = (
                TurnNotificationRecord.BLOCKED
                if notification_kind is NotificationKind.BLOCKED
                else TurnNotificationRecord.TERMINAL_TURN_FAILED
            )
            blocked_claimed, records = await db.claim_turn_notification(target_session_id, record)
            if not blocked_claimed:
                logger.info(
                    "turn_notification_slot_claimed",
                    session_id=target_session_id,
                    claimed_member=record,
                    outcome="rejected",
                    recorded_members=sorted(records),
                )
                if notification_kind is NotificationKind.TURN_FAILED:
                    return False
            else:
                logger.info(
                    "turn_notification_slot_claimed",
                    session_id=target_session_id,
                    claimed_member=record,
                    outcome="claimed",
                )
        else:
            # Claimed before delivery, like every other kind: an inferred stall is
            # attempted once, and an undeliverable one is logged and dropped.
            stall_claimed, records = await db.claim_turn_notification(
                target_session_id, TurnNotificationRecord.INFERRED_STALL
            )
            if not stall_claimed:
                return TurnNotificationRecord.INFERRED_STALL in records
        session = await db.get_session(target_session_id)
        title = session.title if session else None
        computer = source_computer or LOCAL_COMPUTER
        occurrence_key = occurrence_key or (
            observation.ingress_id if observation and observation.ingress_id else uuid4().hex
        )
        # A native observation carries the moment it was observed; an inferred
        # stall or delivery block occurs at the moment it is inferred.
        occurred_at = (
            observation.observed_at
            if observation is not None
            else silence_observation.observed_at
            if silence_observation is not None
            else datetime.now(UTC)
        )
        reached = await notify_distress(
            target_session_id,
            computer,
            notification_kind,
            title,
            observation=observation,
            inferred_stall_evidence=inferred_stall_evidence,
            delivery_block_evidence=delivery_block_evidence,
            startup_delivery_uncertain_evidence=startup_delivery_uncertain_evidence,
            silence_observation=silence_observation,
            silence_audience=silence_audience,
            occurrence_key=occurrence_key,
            occurred_at=occurred_at,
        )
        if silence_observation is not None:
            remote_reached = await self._forward_silence_observation(
                silence_audience or [],
                target_session_id=target_session_id,
                computer=computer,
                title=title,
                observation=silence_observation,
                occurrence_key=occurrence_key,
                occurred_at=occurred_at,
            )
        else:
            remote_reached = await self._forward_distress_to_initiator(
                session,
                notification_kind,
                computer,
                title,
                observation=observation,
                inferred_stall_evidence=inferred_stall_evidence,
                delivery_block_evidence=delivery_block_evidence,
                startup_delivery_uncertain_evidence=startup_delivery_uncertain_evidence,
                occurrence_key=occurrence_key,
                occurred_at=occurred_at,
            )
        fallback_delivered = False
        fallback_eligible = silence_observation is None and (
            inferred_stall_evidence is not None or notification_kind is not NotificationKind.BLOCKED or blocked_claimed
        )
        if fallback_eligible and not reached and not remote_reached:
            fallback_delivered = await notify_distress_human_fallback(
                target_session_id,
                computer,
                notification_kind,
                self.client,
                title,
                inferred_stall_evidence,
                delivery_block_evidence,
                startup_delivery_uncertain_evidence,
            )
        delivered = bool(reached or remote_reached or fallback_delivered)
        outcome = (
            _DISTRESS_OUTCOME_SUBSCRIBER_DELIVERY if reached or remote_reached else _DISTRESS_OUTCOME_HUMAN_FALLBACK
        )
        no_fallback_reason = None
        if not reached and not remote_reached and not fallback_eligible:
            outcome = _DISTRESS_OUTCOME_NO_FALLBACK
            no_fallback_reason = _DISTRESS_NO_FALLBACK_BLOCKED_ALREADY_OBSERVED
        logger.info(
            "distress_audience_resolved",
            target_session_id=target_session_id,
            notification_kind=notification_kind,
            reached=sorted(reached),
            remote_initiator_session_id=(session.initiator_session_id if session else None),
            remote_reached=remote_reached,
            outcome=outcome,
            reason=no_fallback_reason,
            fallback_delivered=fallback_delivered,
            occurrence_key=occurrence_key,
        )
        return delivered

    async def _forward_distress_to_initiator(
        self,
        session: Session | None,
        notification_kind: NotificationKind,
        computer: str,
        title: str | None,
        *,
        observation: AgentAttentionObservation | None,
        inferred_stall_evidence: InferredStallEvidence | None,
        delivery_block_evidence: DeliveryBlockEvidence | None,
        startup_delivery_uncertain_evidence: StartupDeliveryUncertainEvidence | None,
        occurrence_key: str,
        occurred_at: datetime | None,
    ) -> bool:
        """Forward distress and count a remote subscriber only when delivery succeeds."""
        if session is None:
            return False
        session_id = session.session_id
        caller = session.initiator_session_id
        destination = session.initiator_computer
        if not caller or not destination:
            return False
        if destination == config.computer.name:
            return False
        encoded_title = base64.b64encode(title.encode()).decode() if title else "-"
        try:
            metadata = MessageMetadata(
                origin_metadata=_attention_observation_metadata(
                    observation,
                    inferred_stall_evidence,
                    delivery_block_evidence,
                    startup_delivery_uncertain_evidence,
                )
            )
            request_id = await self.client.send_request(
                destination,
                _DISTRESS_COMMAND.format(
                    session_id=session_id,
                    computer=computer,
                    caller=caller,
                    kind=notification_kind,
                    title=encoded_title,
                    occurrence=occurrence_key,
                    occurred_at=_wire_moment(occurred_at),
                ),
                metadata,
                principal=SYSTEM_DAEMON_PRINCIPAL,
            )
            response = json.loads(await self.client.read_response(request_id, target_computer=destination))
            data = response.get("data") if isinstance(response, dict) else None
            delivered = data.get("delivered") if isinstance(data, dict) else None
            result = delivered is True
        except (OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError):
            result = False
        logger.info(
            "distress_forward_result",
            session_id=session_id,
            initiator_session_id=caller,
            destination_computer=destination,
            delivered=result,
        )
        return result

    async def _forward_silence_observation(
        self,
        audience: list[SessionListener],
        *,
        target_session_id: str,
        computer: str,
        title: str | None,
        observation: SilenceObservation,
        occurrence_key: str | None,
        occurred_at: datetime | None,
    ) -> bool:
        """Forward a silence observation only to remote persistent callers in its resolved audience."""
        remote_reached = False
        encoded_title = base64.b64encode(title.encode()).decode() if title else _WIRE_ABSENT
        current_listeners = await db.get_listeners_for_target(target_session_id)
        current_pairs = {
            (listener.caller_session_id, listener.caller_computer)
            for listener in current_listeners
            if not listener.one_shot
        }
        remote_audience = [
            listener
            for listener in audience
            if (listener.caller_computer or config.computer.name) != config.computer.name
            and (listener.caller_session_id, listener.caller_computer) in current_pairs
        ]
        fleet_view: FleetView | None = None
        if remote_audience:
            try:
                fleet_view = await observe_fleet(self.client)
            except (OSError, RedisError, RuntimeError) as exc:
                logger.warning(
                    _SILENCE_REMOTE_CAPABILITY_UNAVAILABLE_EVENT,
                    target_session_id=target_session_id,
                    reason=type(exc).__name__,
                )
        metadata = MessageMetadata(
            origin_metadata=_attention_observation_metadata(
                None,
                None,
                None,
                None,
                observation,
            )
        )
        for listener in audience:
            caller_computer = listener.caller_computer or config.computer.name
            if (
                caller_computer == config.computer.name
                or (listener.caller_session_id, listener.caller_computer) not in current_pairs
            ):
                continue
            peer = (
                next(
                    (member for member in fleet_view.peers if member.name == caller_computer),
                    None,
                )
                if fleet_view is not None
                else None
            )
            if peer is None or SUPERVISORY_SILENCE_OBSERVATIONS_FEATURE_ID not in peer.capability_set:
                logger.info(
                    _SILENCE_REMOTE_DELIVERY_OUTCOME_EVENT,
                    target_session_id=target_session_id,
                    caller_session_id=listener.caller_session_id,
                    computer=caller_computer,
                    outcome=_SilenceDeliveryOutcome.UNAVAILABLE,
                    reason=_SILENCE_PEER_CAPABILITY_MISSING
                    if fleet_view is not None
                    else _SILENCE_PEER_VIEW_UNAVAILABLE,
                )
                continue
            try:
                request_id = await self.client.send_request(
                    caller_computer,
                    _DISTRESS_COMMAND.format(
                        session_id=target_session_id,
                        computer=computer,
                        caller=listener.caller_session_id,
                        kind=NotificationKind.SILENCE_OBSERVATION,
                        title=encoded_title,
                        occurrence=occurrence_key or uuid4().hex,
                        occurred_at=_wire_moment(occurred_at),
                    ),
                    metadata,
                    principal=SYSTEM_DAEMON_PRINCIPAL,
                )
                response = json.loads(await self.client.read_response(request_id, target_computer=caller_computer))
                response_data = response.get("data") if isinstance(response, dict) else None
                delivered = response_data.get("delivered") if isinstance(response_data, dict) else None
                outcome = _SilenceDeliveryOutcome.ACCEPTED if delivered is True else _SilenceDeliveryOutcome.UNAVAILABLE
                logger.info(
                    _SILENCE_REMOTE_DELIVERY_OUTCOME_EVENT,
                    target_session_id=target_session_id,
                    caller_session_id=listener.caller_session_id,
                    computer=caller_computer,
                    outcome=outcome,
                )
                remote_reached = remote_reached or delivered is True
            except (OSError, RuntimeError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                logger.info(
                    _SILENCE_REMOTE_DELIVERY_OUTCOME_EVENT,
                    target_session_id=target_session_id,
                    caller_session_id=listener.caller_session_id,
                    computer=caller_computer,
                    outcome=_SilenceDeliveryOutcome.UNAVAILABLE,
                    reason=type(exc).__name__,
                )
                continue
        return remote_reached

    async def _forward_stop_to_initiator(
        self, session_id: str, variant: StopNotificationVariant, *, occurred_at: datetime | None
    ) -> None:
        """Forward stop event to a remote initiator via Redis.

        The initiator's session id travels on the wire alongside its
        destination: the receiving daemon has no local row for `session_id`
        (it was created on this computer, not there) and so no listener row
        to consult either — delivery on the far end resolves the caller
        directly rather than through the local listener table.

        Uses session.title from DB (stable, canonical) rather than
        freshly generated title from summarizer.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        if not session.initiator_session_id:
            return

        initiator_computer = session.initiator_computer
        if not initiator_computer:
            logger.warning(
                "stop_forward_missing_destination",
                session_id=session_id,
                initiator_session_id=session.initiator_session_id,
            )
            return

        if initiator_computer == config.computer.name:
            return

        # Use stable title from session record
        title_b64 = "-"
        if session.title:
            title_b64 = base64.b64encode(session.title.encode()).decode()
        occurrence_key = uuid4().hex

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=_STOP_NOTIFICATION_COMMAND.format(
                    session_id=session_id,
                    computer=config.computer.name,
                    caller=session.initiator_session_id,
                    title=title_b64,
                    occurrence=occurrence_key,
                    variant=variant.value,
                    occurred_at=_wire_moment(occurred_at),
                ),
                metadata=MessageMetadata(),
                principal=SYSTEM_DAEMON_PRINCIPAL,
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as exc:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, exc)
