"""Fanout, extraction, TTS, snapshot, and notification mixin for AgentCoordinator."""

import base64
import random
import shlex
from datetime import datetime
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import (
    LOCAL_COMPUTER,
    format_system_message,
)
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.checkpoint_dispatch import inject_checkpoint_if_needed
from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_listeners import (
    get_active_links_for_session,
    get_peer_members,
    notify_stop,
)
from teleclaude.core.summarizer import generate_session_title, summarize_agent_output
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.tts.manager import TTSManager
from teleclaude.types.commands import ProcessMessageCommand
from teleclaude.utils.transcript import (
    extract_last_agent_message,
    extract_last_user_message_with_timestamp,
    extract_recent_transcript_turns,
)

from ._helpers import (
    _MAX_FORWARDED_LINK_OUTPUT_CHARS,
    SESSION_START_MESSAGES,
    _is_checkpoint_prompt,
    _to_utc,
)

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient
    from teleclaude.core.events import AgentStopPayload
    from teleclaude.core.models import Session

logger = get_logger(__name__)


class _FanoutMixin:  # pyright: ignore[reportUnusedClass]
    """Extraction, fanout, TTS, snapshot, and notification methods for AgentCoordinator."""

    if TYPE_CHECKING:
        client: "AdapterClient"
        tts_manager: TTSManager
        headless_snapshot_service: HeadlessSnapshotService

    async def _update_session_title_async(
        self, session_id: str, expected_prompt_at: datetime, prompt_text: str = ""
    ) -> None:
        """Best-effort asynchronous title update for the latest accepted prompt."""
        current = await db.get_session(session_id)
        if not current or _to_utc(current.last_message_sent_at) != _to_utc(expected_prompt_at):
            return

        current_title = (current.title or "").strip()

        # Slash-command titles are frozen — never overwrite them.
        if current_title.startswith("/"):
            return

        # Untitled session receiving a slash command: set title to the command and freeze.
        if "Untitled" in current_title and prompt_text.lstrip().startswith("/"):
            slash_title = prompt_text.strip()[:70]
            await db.update_session(session_id, title=slash_title)
            logger.info("Set slash-command title for session %s: %s", session_id, slash_title)
            return

        transcript_path = current.native_log_file
        if not current.active_agent or not transcript_path:
            return

        try:
            agent_name = AgentName.from_str(current.active_agent)
        except ValueError:
            return

        recent_turns = extract_recent_transcript_turns(transcript_path, agent_name, max_turns_per_role=3)
        if not recent_turns:
            return

        try:
            new_title = await generate_session_title(recent_turns)
        except Exception as exc:
            logger.warning("Title summarization failed: %s", exc)
            return

        if not new_title:
            return

        latest = await db.get_session(session_id)
        if not latest or _to_utc(latest.last_message_sent_at) != _to_utc(expected_prompt_at):
            return

        await db.update_session(session_id, title=new_title)
        logger.info("Updated session title from user input: %s", new_title)

    async def _maybe_send_headless_snapshot(self, session_id: str) -> None:
        session = await db.get_session(session_id)
        if not session or session.lifecycle_status != "headless":
            return
        if not session.active_agent or not session.native_log_file:
            logger.debug("Headless snapshot skipped (missing agent or transcript)", session=session_id)
            return
        await self.headless_snapshot_service.send_snapshot(session, reason="agent_session_start", client=self.client)

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

    async def _extract_user_input_for_codex(
        self, session_id: str, payload: "AgentStopPayload"
    ) -> tuple[str, datetime | None] | None:
        """Extract last user input from transcript for Codex sessions.

        Codex doesn't have user_prompt_submit hook, so we extract user input
        from the transcript on agent stop as a fallback.
        """
        session = await db.get_session(session_id)
        if not session:
            return None

        # Only for Codex sessions
        agent_name_value = session.active_agent
        if agent_name_value != AgentName.CODEX.value:
            return None

        transcript_path = payload.transcript_path or session.native_log_file
        if not transcript_path:
            logger.debug("Codex user input extraction skipped (no transcript)", session=session_id)
            return None

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            return None

        extracted = extract_last_user_message_with_timestamp(transcript_path, agent_name)
        if not extracted:
            logger.debug("Codex user input extraction skipped (no user message)", session=session_id)
            return None
        last_user_input, input_timestamp = extracted

        # Don't persist our own checkpoint message as user input
        if _is_checkpoint_prompt(last_user_input):
            logger.debug("Codex user input skipped (checkpoint message) for session %s", session_id)
            return None

        logger.debug(
            "Extracted Codex user input: session=%s input=%s...",
            session_id,
            last_user_input[:50],
        )
        return last_user_input, input_timestamp

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

        redis_meta = session.get_metadata().get_transport().get_redis()
        if not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
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
        except Exception as e:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, e)

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
        sender_label = sender.title if sender and sender.title else sender_session_id
        sender_computer = source_computer or (sender.computer_name if sender else config.computer.name)
        framed_message = format_system_message(
            f'Linked output from "{sender_label}" ({sender_session_id}) on {sender_computer}',
            distilled_output,
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
                    if target_computer == config.computer.name:
                        cmd = ProcessMessageCommand(
                            session_id=peer.session_id,
                            text=framed_message,
                            origin=InputOrigin.REDIS.value,
                            actor_id=actor_id,
                            actor_name=actor_name,
                        )
                        await get_command_service().process_message(cmd)
                    else:
                        await self.client.send_request(
                            computer_name=target_computer,
                            command=f"message {shlex.quote(framed_message)}",
                            session_id=peer.session_id,
                            metadata=MessageMetadata(
                                origin=InputOrigin.REDIS.value,
                                channel_metadata={
                                    "actor_id": actor_id,
                                    "actor_name": actor_name,
                                    "actor_role": "system",
                                    "actor_agent": "system",
                                    "actor_computer": sender_computer,
                                },
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

    async def _maybe_inject_checkpoint(self, session_id: str, session: "Session | None") -> None:
        """Conditionally inject a checkpoint message into the agent's tmux pane.

        Claude/Gemini: handled by hook output in receiver.py (invisible checkpoint).
        Codex: falls through to tmux injection below.
        """
        if not session:
            return

        try:
            await inject_checkpoint_if_needed(
                session_id,
                route="codex_tmux",
                include_elapsed_since_turn_start=True,
                default_agent=AgentName.from_str(get_default_agent()),
            )
        except Exception as exc:
            logger.warning("Checkpoint injection failed for session %s: %s", session_id, exc)
