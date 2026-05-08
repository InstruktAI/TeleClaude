"""Fanout, extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import random
import shlex
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.conversation_messages import format_linked_output_message
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import get_active_links_for_session, get_peer_members, notify_stop
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES
from teleclaude.core.summarizer import summarize_agent_output
from teleclaude.tts.manager import TTSManager
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils.transcript import extract_last_agent_message, get_assistant_messages_since

from ._helpers import _MAX_FORWARDED_LINK_OUTPUT_CHARS

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

    async def _extract_agent_output_since(
        self,
        session_id: str,
        payload: "AgentStopPayload",
        since_timestamp: datetime,
    ) -> str | None:
        """Extract assistant text emitted after the provided prompt timestamp."""
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Incremental extract skipped (missing transcript path)", session=session_id)
            return None

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Incremental extract skipped (missing agent name)", session=session_id)
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Incremental extract skipped (unknown agent '%s')", agent_name_value)
            return None

        assistant_messages = get_assistant_messages_since(
            transcript_path,
            agent_name,
            since_timestamp=since_timestamp,
        )
        if not assistant_messages:
            return None

        collected: list[str] = []
        for message in assistant_messages:
            content = message.get("content")
            if isinstance(content, str):
                text = content.strip()
                if text:
                    collected.append(text)
                continue
            if not isinstance(content, list):
                continue

            message_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") not in {"text", "output_text"}:
                    continue
                text = str(block.get("text", "")).strip()
                if text:
                    message_parts.append(text)
            if message_parts:
                collected.append("\n\n".join(message_parts))

        rendered = "\n\n".join(part for part in collected if part).strip()
        if not rendered:
            logger.debug("Incremental extract skipped (no assistant text after prompt)", session=session_id)
            return None
        return rendered

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

    async def _forward_stop_to_initiator(self, session_id: str, linked_output: str | None = None) -> None:
        """Forward stop event to remote initiator via Redis.

        Uses session.title from DB (stable, canonical) rather than
        freshly generated title from summarizer.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        redis_section = session.get_origin_section("redis")
        target_computer = redis_section.get("target_computer")
        if not target_computer:
            return

        initiator_computer = str(target_computer)
        if initiator_computer == config.computer.name:
            return

        # Use stable title from session record
        title_b64 = "-"
        if session.title:
            title_b64 = base64.b64encode(session.title.encode()).decode()
        output_arg = ""
        if linked_output and linked_output.strip():
            distilled = linked_output.strip()
            if len(distilled) > _MAX_FORWARDED_LINK_OUTPUT_CHARS:
                distilled = distilled[:_MAX_FORWARDED_LINK_OUTPUT_CHARS]
            output_b64 = base64.b64encode(distilled.encode()).decode()
            output_arg = f" {output_b64}"

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/stop_notification {session_id} {config.computer.name} {title_b64}{output_arg}",
                metadata=MessageMetadata(),
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as exc:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, exc)

    async def _fanout_linked_stop_output(
        self,
        sender_session_id: str,
        distilled_output: str,
        *,
        source_computer: str | None = None,
    ) -> int:
        """Fan out distilled stop output to peers in active links, excluding sender."""
        links = await get_active_links_for_session(sender_session_id)
        if not links:
            return 0

        sender = await db.get_session(sender_session_id)
        sender_computer = source_computer or (sender.computer_name if sender else config.computer.name)
        framed_message = format_linked_output_message(
            sender_session_id=sender_session_id,
            sender_computer=sender_computer,
            content=distilled_output,
        )

        delivered = 0
        for link in links:
            peers = await get_peer_members(link_id=link.link_id, sender_session_id=sender_session_id)
            for peer in peers:
                target_computer = (
                    peer.computer_name
                    if peer.computer_name and peer.computer_name not in {LOCAL_COMPUTER, "local"}
                    else config.computer.name
                )
                actor_id = f"system:{sender_computer}:{sender_session_id}"
                actor_name = f"system@{sender_computer}"

                try:
                    sender_origin = (
                        sender.last_input_origin or InputOrigin.TERMINAL.value if sender else InputOrigin.TERMINAL.value
                    )
                    if target_computer == config.computer.name:
                        cmd = ProcessMessageCommand(
                            session_id=peer.session_id,
                            text=framed_message,
                            origin=sender_origin,
                            actor_id=actor_id,
                            actor_name=actor_name,
                            source_channel_id=link.link_id,
                        )
                        await get_command_service().process_message(cmd)
                    else:
                        await self.client.send_request(
                            computer_name=target_computer,
                            command=f"message {shlex.quote(framed_message)}",
                            session_id=peer.session_id,
                            metadata=MessageMetadata(
                                origin=sender_origin,
                                actor_id=actor_id,
                                actor_name=actor_name,
                            ),
                        )
                    delivered += 1
                except Exception as exc:
                    logger.warning(
                        "Linked stop output delivery failed: sender=%s peer=%s target=%s error=%s",
                        sender_session_id,
                        peer.session_id,
                        target_computer,
                        exc,
                    )

        if delivered:
            logger.info(
                "Linked stop output fan-out: sender=%s delivered=%d",
                sender_session_id,
                delivered,
            )
        return delivered
