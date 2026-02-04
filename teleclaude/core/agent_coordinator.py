"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop, notification) and routes them to:
1. Local listeners (via tmux injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

import base64
import random
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.agents import AgentName
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentNotificationPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
    UserPromptSubmitPayload,
)
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import notify_input_request, notify_stop
from teleclaude.core.session_utils import update_title_with_agent
from teleclaude.core.summarizer import summarize_text
from teleclaude.services.headless_snapshot_service import HeadlessSnapshotService
from teleclaude.tts.manager import TTSManager
from teleclaude.utils.transcript import extract_last_agent_message

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

SESSION_START_MESSAGES = [
    "Standing by with grep patterns locked and loaded. What can I find?",
    "Warmed up and ready to hunt down that bug!",
    "Cache cleared, mind fresh. What's the task?",
    "All systems nominal, ready to ship some code!",
    "Initialized and ready to make those tests pass. What needs fixing?",
    "Compiled with optimism and ready to refactor!",
    "Ready to turn coffee into code. Where do we start?",
    "Standing by like a well-indexed database!",
    "Alert and ready to parse whatever you need. What's up?",
    "Primed to help you ship that feature!",
    "Spun up and ready to debug. What's broken?",
    "Loaded and eager to make things work!",
    "Ready to dig into the details. What should I investigate?",
    "All systems go for some serious coding!",
    "Prepared to tackle whatever you throw at me. What's the challenge?",
    "Standing by to help ship something awesome!",
    "Ready to make the build green. What needs attention?",
    "Warmed up and waiting to assist!",
    "Initialized and ready to solve problems. What's the issue?",
    "All set to help you build something great!",
]


class AgentCoordinator:
    """Coordinator for agent events and inter-agent communication."""

    def __init__(
        self,
        client: "AdapterClient",
        tts_manager: TTSManager,
        headless_snapshot_service: HeadlessSnapshotService,
    ) -> None:
        self.client = client
        self.tts_manager = tts_manager
        self.headless_snapshot_service = headless_snapshot_service

    async def handle_event(self, context: AgentEventContext) -> None:
        """Handle any agent lifecycle event."""
        if context.event_type == AgentHookEvents.AGENT_SESSION_START:
            await self.handle_session_start(context)
        elif context.event_type == AgentHookEvents.AGENT_STOP:
            await self.handle_stop(context)
        elif context.event_type == AgentHookEvents.USER_PROMPT_SUBMIT:
            await self.handle_user_prompt_submit(context)
        elif context.event_type == AgentHookEvents.AGENT_NOTIFICATION:
            await self.handle_notification(context)
        elif context.event_type == AgentHookEvents.AGENT_SESSION_END:
            await self.handle_session_end(context)

    async def handle_session_start(self, context: AgentEventContext) -> None:
        """Handle session_start event - store native session details and update title if needed."""
        payload = cast(AgentSessionStartPayload, context.data)
        native_session_id = payload.session_id
        native_log_file = payload.transcript_path
        raw_cwd = payload.raw.get("cwd")

        update_kwargs: dict[str, object] = {}  # noqa: loose-dict - Dynamic session updates
        if native_session_id:
            update_kwargs["native_session_id"] = str(native_session_id)
        if native_log_file:
            update_kwargs["native_log_file"] = str(native_log_file)

        if isinstance(raw_cwd, str) and raw_cwd:
            session = await db.get_session(context.session_id)
            if session and not session.project_path:
                update_kwargs["project_path"] = raw_cwd
                update_kwargs["subdir"] = None
        if update_kwargs:
            await db.update_session(context.session_id, **update_kwargs)

        voice = await db.get_voice(context.session_id)
        if voice:
            await db.assign_voice(context.session_id, voice)
            logger.debug(
                "Reaffirmed voice from service '%s' for teleclaude_session_id %s",
                voice.service_name,
                context.session_id[:8],
            )

        logger.info(
            "Stored Agent session data: teleclaude=%s, native=%s",
            context.session_id[:8],
            str(native_session_id)[:8],
        )

        # Update session title if it still uses old $Computer format but we have agent info
        await self._update_title_if_needed(context.session_id)
        await self._maybe_send_headless_snapshot(context.session_id)
        await self._speak_session_start()

    async def _update_title_if_needed(self, session_id: str) -> None:
        """Update session title to include agent info if it uses old format."""
        session = await db.get_session(session_id)
        if not session:
            return

        # Check if title still uses old $Computer format
        if f"${config.computer.name}" not in session.title:
            return  # Already has new format or different computer

        # Get agent info from session
        if not session.active_agent or not session.thinking_mode:
            return  # No agent info available

        # Build new title with agent info
        new_title = update_title_with_agent(
            session.title,
            session.active_agent,
            session.thinking_mode,
            config.computer.name,
        )

        if new_title and new_title != session.title:
            await db.update_session(session_id, title=new_title)
            logger.info("Updated session title with agent info: %s", new_title)

    async def handle_user_prompt_submit(self, context: AgentEventContext) -> None:
        """Handle user prompt submission (currently a no-op)."""
        session_id = context.session_id
        payload = cast(UserPromptSubmitPayload, context.data)
        logger.debug(
            "User prompt submit ignored for session %s: %s",
            session_id[:8],
            payload.prompt[:50],
        )

    async def handle_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped."""
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        source_computer = payload.source_computer

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id[:8],
            "db",
        )

        await self._speak_stop_summary(session_id, payload)

        # 1. Notify local listeners (AI-to-AI on same computer)
        await self._notify_session_listener(session_id, source_computer=source_computer)

        # 2. Forward to remote initiator (AI-to-AI across computers)
        if not (source_computer and source_computer != config.computer.name):
            await self._forward_stop_to_initiator(session_id)

    async def handle_notification(self, context: AgentEventContext) -> None:
        """Handle notification event - input request."""
        session_id = context.session_id
        payload = cast(AgentNotificationPayload, context.data)
        message = payload.message
        source_computer = payload.source_computer

        # 1. Notify local listeners
        computer = source_computer or LOCAL_COMPUTER
        await notify_input_request(session_id, computer, str(message))

        # 2. Forward to remote initiator (skip if already forwarded from remote)
        if not source_computer:
            await self._forward_notification_to_initiator(session_id, str(message))

        # Update notification flag
        await db.set_notification_flag(session_id, True)

    async def handle_session_end(self, context: AgentEventContext) -> None:
        """Handle session_end event - agent session ended."""
        _payload = cast(AgentSessionEndPayload, context.data)
        logger.info("Agent %s for session %s", AgentHookEvents.AGENT_SESSION_END, context.session_id[:8])

    async def _maybe_send_headless_snapshot(self, session_id: str) -> None:
        session = await db.get_session(session_id)
        if not session or session.lifecycle_status != "headless":
            return
        if not session.active_agent or not session.native_log_file:
            logger.debug("Headless snapshot skipped (missing agent or transcript)", session=session_id[:8])
            return
        await self.headless_snapshot_service.send_snapshot(session, reason="agent_session_start", client=self.client)

    async def _speak_session_start(self) -> None:
        if not SESSION_START_MESSAGES:
            return
        message = random.choice(SESSION_START_MESSAGES)
        try:
            await self.tts_manager.speak(message)
        except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
            logger.warning("TTS session_start failed: %s", exc)

    async def _speak_stop_summary(self, session_id: str, payload: AgentStopPayload) -> None:
        session = await db.get_session(session_id)
        transcript_path = payload.transcript_path or (session.native_log_file if session else None)
        if not transcript_path:
            logger.debug("Stop summary skipped (missing transcript path)", session=session_id[:8])
            return

        raw_agent_name = payload.raw.get("agent_name")
        agent_name_value = raw_agent_name if isinstance(raw_agent_name, str) and raw_agent_name else None
        if not agent_name_value and session and session.active_agent:
            agent_name_value = session.active_agent
        if not agent_name_value:
            logger.debug("Stop summary skipped (missing agent name)", session=session_id[:8])
            return

        try:
            agent_name = AgentName.from_str(agent_name_value)
        except ValueError:
            logger.warning("Stop summary skipped (unknown agent '%s')", agent_name_value)
            return

        last_message = extract_last_agent_message(transcript_path, agent_name, 1)
        if not last_message:
            logger.debug("Stop summary skipped (no agent output)", session=session_id[:8])
            return

        try:
            _title, summary = await summarize_text(last_message)
        except Exception as exc:  # noqa: BLE001 - summarizer failures should not break stop handling
            logger.warning("Stop summary failed: %s", exc, extra={"session_id": session_id[:8]})
            return

        try:
            await self.tts_manager.speak(summary)
        except Exception as exc:  # noqa: BLE001 - TTS should never crash event handling
            logger.warning("TTS agent_stop failed: %s", exc, extra={"session_id": session_id[:8]})

    # === Helper Methods (extracted from UiAdapter) ===

    async def _notify_session_listener(
        self,
        target_session_id: str,
        *,
        source_computer: str | None = None,
    ) -> None:
        """Notify local listeners via tmux injection."""
        target_session = await db.get_session(target_session_id)
        display_title = target_session.title if target_session else "Unknown"
        computer = source_computer or LOCAL_COMPUTER
        await notify_stop(target_session_id, computer, title=display_title)

    async def _forward_stop_to_initiator(self, session_id: str) -> None:
        """Forward stop event to remote initiator via Redis.

        Uses session.title from DB (stable, canonical) rather than
        freshly generated title from summarizer.
        """
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        # Use stable title from session record
        title_arg = ""
        if session.title:
            title_b64 = base64.b64encode(session.title.encode()).decode()
            title_arg = f" {title_b64}"

        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/stop_notification {session_id} {config.computer.name}{title_arg}",
                metadata=MessageMetadata(),
            )
            logger.info("Forwarded stop to %s", initiator_computer)
        except Exception as e:
            logger.warning("Failed to forward stop to %s: %s", initiator_computer, e)

    async def _forward_notification_to_initiator(self, session_id: str, message: str) -> None:
        """Forward notification to remote initiator."""
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        message_b64 = base64.b64encode(message.encode()).decode()
        try:
            await self.client.send_request(
                computer_name=initiator_computer,
                command=f"/input_notification {session_id} {config.computer.name} {message_b64}",
                metadata=MessageMetadata(),
            )
        except Exception as e:
            logger.warning("Failed to forward notification to %s: %s", initiator_computer, e)
