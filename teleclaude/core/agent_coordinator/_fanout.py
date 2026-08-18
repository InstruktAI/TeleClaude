"""Extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import random
from typing import TYPE_CHECKING
from uuid import uuid4

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import notify_stop
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.core.summarizer import summarize_agent_output
from teleclaude.tts.manager import TTSManager
from teleclaude.utils.transcript import extract_last_agent_message

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.events import AgentStopPayload

logger = get_logger(__name__)


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

        Turn-gated: the notification_sent flag prevents duplicate notifications
        from heartbeat-induced agent_stop events within the same turn.
        Cleared automatically by handle_user_prompt_submit on the next real prompt.
        """
        if await db.get_notification_flag(target_session_id):
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
        notified = await notify_stop(target_session_id, computer, title=display_title)
        if notified:
            await db.set_notification_flag(target_session_id, True)

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
