"""Extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import json
import random
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.db._sessions import TurnNotificationRecord
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import (
    NotificationKind,
    notify_distress,
    notify_distress_human_fallback,
    notify_stop,
)
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.core.summarizer import summarize_agent_output
from teleclaude.tts.manager import TTSManager
from teleclaude.utils.transcript import extract_last_agent_message

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.events import AgentStopPayload

logger = get_logger(__name__)
_DISTRESS_COMMAND = "/distress_notification {session_id} {computer} {caller} {kind} {title} {occurrence}"


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

    async def _extract_agent_output(self, session_id: str, payload: "AgentStopPayload") -> str | None:
        """Extract last agent output from transcript.

        Returns:
            Raw output text, or None if extraction fails or no output found.
        """
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Extract skipped (missing transcript path)", session=session_id)
            return None

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Extract skipped (missing agent name)", session=session_id)
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Extract skipped (unknown agent '%s')", agent_name_value)
            return None

        last_message = extract_last_agent_message(transcript_path, agent_name, 1)
        if not last_message or not last_message.strip():
            logger.debug("Extract skipped (no agent output)", session=session_id)
            return None

        return last_message

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
        self, target_session_id: str, notification_kind: NotificationKind, source_computer: str | None = None
    ) -> None:
        """Notify persistent listeners after claiming the matching turn slot."""
        record = (
            TurnNotificationRecord.BLOCKED
            if notification_kind is NotificationKind.BLOCKED
            else TurnNotificationRecord.TERMINAL_TURN_FAILED
        )
        claimed, records = await db.claim_turn_notification(target_session_id, record)
        if not claimed:
            logger.info(
                "turn_notification_slot_claimed",
                session_id=target_session_id,
                claimed_member=record,
                outcome="rejected",
                recorded_members=sorted(records),
            )
            return
        logger.info(
            "turn_notification_slot_claimed",
            session_id=target_session_id,
            claimed_member=record,
            outcome="claimed",
        )
        session = await db.get_session(target_session_id)
        title = session.title if session else None
        computer = source_computer or LOCAL_COMPUTER
        reached = await notify_distress(target_session_id, computer, notification_kind, title)
        remote_reached = await self._forward_distress_to_initiator(session, notification_kind, computer, title)
        fallback_delivered = False
        if not reached and not remote_reached:
            fallback_delivered = await notify_distress_human_fallback(
                target_session_id, computer, notification_kind, self.client, title
            )
        logger.info(
            "distress_audience_resolved",
            target_session_id=target_session_id,
            notification_kind=notification_kind,
            reached=sorted(reached),
            remote_initiator_session_id=(session.initiator_session_id if session else None),
            remote_reached=remote_reached,
            outcome=("subscriber_delivery" if reached or remote_reached else "human_fallback"),
            fallback_delivered=fallback_delivered,
        )

    async def _forward_distress_to_initiator(
        self, session: object | None, notification_kind: NotificationKind, computer: str, title: str | None
    ) -> bool:
        """Forward distress and count a remote subscriber only when delivery succeeds."""
        if session is None:
            return False
        session_id = getattr(session, "session_id", None)
        caller = getattr(session, "initiator_session_id", None)
        destination = getattr(session, "initiator_computer", None)
        if not all(isinstance(value, str) and value for value in (session_id, caller, destination)):
            return False
        if destination == config.computer.name:
            return False
        encoded_title = base64.b64encode(title.encode()).decode() if title else "-"
        try:
            request_id = await self.client.send_request(
                destination,
                _DISTRESS_COMMAND.format(
                    session_id=session_id,
                    computer=computer,
                    caller=caller,
                    kind=notification_kind,
                    title=encoded_title,
                    occurrence=uuid4().hex,
                ),
                MessageMetadata(),
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
