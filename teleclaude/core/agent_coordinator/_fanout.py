"""Extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import json
import random
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.db._sessions import TurnNotificationRecord
from teleclaude.core.events import AgentAttentionObservation
from teleclaude.core.models import MessageMetadata, Session, SessionOriginMetadata
from teleclaude.core.session_listeners import (
    NotificationKind,
    notify_distress,
    notify_distress_human_fallback,
    notify_stop,
)
from teleclaude.core.session_output import StopOutputKind, StopOutputResult, classify_stop_output
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.core.summarizer import summarize_agent_output
from teleclaude.tts.manager import TTSManager
from teleclaude.utils.transcript import extract_stop_agent_message

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.events import AgentStopPayload

logger = get_logger(__name__)
_DISTRESS_COMMAND = "/distress_notification {session_id} {computer} {caller} {kind} {title} {occurrence}"
_ATTENTION_METADATA_KEY = "attention_observation"
_ATTENTION_PROVIDER_KEY = "provider"
_ATTENTION_NATIVE_EVENT_KEY = "native_event"
_ATTENTION_DETAILS_KEY = "details"
_ATTENTION_OBSERVED_AT_KEY = "observed_at"
_ATTENTION_INGRESS_ID_KEY = "ingress_id"
_DISTRESS_OUTCOME_SUBSCRIBER_DELIVERY = "subscriber_delivery"
_DISTRESS_OUTCOME_HUMAN_FALLBACK = "human_fallback"
_DISTRESS_OUTCOME_NO_FALLBACK = "no_fallback"
_DISTRESS_NO_FALLBACK_NEUTRAL_NOTIFICATION = "neutral_notification"
_DISTRESS_NO_FALLBACK_BLOCKED_ALREADY_OBSERVED = "blocked_already_observed_this_turn"


def _attention_observation_metadata(observation: AgentAttentionObservation | None) -> SessionOriginMetadata:
    """Serialize provider evidence once for the addressed remote parent path."""
    if observation is None:
        return cast(SessionOriginMetadata, {})
    return cast(
        SessionOriginMetadata,
        {
            _ATTENTION_METADATA_KEY: {
                _ATTENTION_PROVIDER_KEY: observation.provider,
                _ATTENTION_NATIVE_EVENT_KEY: observation.native_event,
                _ATTENTION_DETAILS_KEY: dict(observation.details),
                _ATTENTION_OBSERVED_AT_KEY: observation.observed_at.isoformat() if observation.observed_at else None,
                _ATTENTION_INGRESS_ID_KEY: observation.ingress_id,
            }
        },
    )


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

    async def _extract_agent_output(self, session_id: str, payload: "AgentStopPayload") -> StopOutputResult:
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

        native_entry_id = payload.native_turn_id
        message = extract_stop_agent_message(
            transcript_path,
            agent_name,
            native_entry_id=native_entry_id,
        )
        if message is None:
            logger.debug("Extract unavailable (no corresponding agent response)", session=session_id)
            return StopOutputResult(StopOutputKind.UNAVAILABLE)
        return classify_stop_output(message)

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
        source_computer: str | None = None,
        title_override: str | None = None,
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
        await notify_stop(target_session_id, computer, title=display_title)

    async def _notify_session_distress(
        self,
        target_session_id: str,
        notification_kind: NotificationKind,
        source_computer: str | None = None,
        observation: AgentAttentionObservation | None = None,
    ) -> None:
        """Notify parents while retaining terminal and fallback slot semantics."""
        blocked_claimed = False
        if notification_kind is not NotificationKind.NATIVE_NOTIFICATION:
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
                    return
            else:
                logger.info(
                    "turn_notification_slot_claimed",
                    session_id=target_session_id,
                    claimed_member=record,
                    outcome="claimed",
                )
        session = await db.get_session(target_session_id)
        title = session.title if session else None
        computer = source_computer or LOCAL_COMPUTER
        occurrence_key = observation.ingress_id if observation and observation.ingress_id else uuid4().hex
        reached = await notify_distress(
            target_session_id,
            computer,
            notification_kind,
            title,
            observation=observation,
            occurrence_key=occurrence_key,
        )
        remote_reached = await self._forward_distress_to_initiator(
            session,
            notification_kind,
            computer,
            title,
            observation=observation,
            occurrence_key=occurrence_key,
        )
        fallback_delivered = False
        fallback_eligible = notification_kind is not NotificationKind.NATIVE_NOTIFICATION and (
            notification_kind is not NotificationKind.BLOCKED or blocked_claimed
        )
        if fallback_eligible and not reached and not remote_reached:
            fallback_delivered = await notify_distress_human_fallback(
                target_session_id, computer, notification_kind, self.client, title
            )
        outcome = (
            _DISTRESS_OUTCOME_SUBSCRIBER_DELIVERY if reached or remote_reached else _DISTRESS_OUTCOME_HUMAN_FALLBACK
        )
        no_fallback_reason = None
        if not reached and not remote_reached and not fallback_eligible:
            outcome = _DISTRESS_OUTCOME_NO_FALLBACK
            no_fallback_reason = (
                _DISTRESS_NO_FALLBACK_NEUTRAL_NOTIFICATION
                if notification_kind is NotificationKind.NATIVE_NOTIFICATION
                else _DISTRESS_NO_FALLBACK_BLOCKED_ALREADY_OBSERVED
            )
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

    async def _forward_distress_to_initiator(
        self,
        session: Session | None,
        notification_kind: NotificationKind,
        computer: str,
        title: str | None,
        *,
        observation: AgentAttentionObservation | None,
        occurrence_key: str,
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
            metadata = MessageMetadata(origin_metadata=_attention_observation_metadata(observation))
            request_id = await self.client.send_request(
                destination,
                _DISTRESS_COMMAND.format(
                    session_id=session_id,
                    computer=computer,
                    caller=caller,
                    kind=notification_kind,
                    title=encoded_title,
                    occurrence=occurrence_key,
                ),
                metadata,
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

    async def _forward_stop_to_initiator(self, session_id: str) -> None:
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

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=(
                    f"/stop_notification {session_id} {config.computer.name} {session.initiator_session_id} {title_b64} {uuid4().hex}"
                ),
                metadata=MessageMetadata(),
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as exc:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, exc)
