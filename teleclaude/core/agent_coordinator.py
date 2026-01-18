"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop, notification) and routes them to:
1. Local listeners (via tmux injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

import base64
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.constants import LOCAL_COMPUTER
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentNotificationPayload,
    AgentPromptPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
)
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import notify_input_request, notify_stop
from teleclaude.core.session_utils import update_title_with_agent

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)


class AgentCoordinator:
    """Coordinator for agent events and inter-agent communication."""

    def __init__(self, client: "AdapterClient") -> None:
        self.client = client

    async def handle_session_start(self, context: AgentEventContext) -> None:
        """Handle session_start event - store native session details and update title if needed."""
        payload = cast(AgentSessionStartPayload, context.data)
        native_session_id = payload.session_id
        native_log_file = payload.transcript_path

        update_kwargs: dict[str, object] = {  # noqa: loose-dict - Dynamic session updates
            "native_session_id": str(native_session_id),
            "native_log_file": str(native_log_file),
        }

        await db.update_session(context.session_id, **update_kwargs)

        # Copy voice assignment if available
        voice = await db.get_voice(context.session_id)
        if voice:
            await db.assign_voice(str(native_session_id), voice)
            logger.debug("Copied voice '%s' to native_session_id %s", voice.name, str(native_session_id)[:8])

        logger.info(
            "Stored Agent session data: teleclaude=%s, native=%s",
            context.session_id[:8],
            str(native_session_id)[:8],
        )

        # Update session title if it still uses old $Computer format but we have agent info
        await self._update_title_if_needed(context.session_id)

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

    async def handle_prompt(self, context: AgentEventContext) -> None:
        """Handle agent prompt event - user input submitted."""
        session_id = context.session_id
        payload = cast(AgentPromptPayload, context.data)

        logger.debug(
            "Agent prompt event for session %s: %s",
            session_id[:8],
            payload.prompt[:50],
        )

        # Clear notification flag when new prompt starts
        await db.set_notification_flag(session_id, False)

    async def handle_stop(self, context: AgentEventContext) -> None:
        """Handle stop event - Agent session stopped.

        Assumes context.data is already enriched with title/summary by the Daemon.
        """
        session_id = context.session_id
        payload = cast(AgentStopPayload, context.data)
        title = payload.title
        source_computer = payload.source_computer

        logger.debug(
            "Agent stop event for session %s (title: %s)",
            session_id[:8],
            title[:20] if title else "none",
        )

        # 1. Notify local listeners (AI-to-AI on same computer)
        await self._notify_session_listener(session_id, title=title, source_computer=source_computer)

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

    # === Helper Methods (extracted from UiAdapter) ===

    async def _notify_session_listener(
        self,
        target_session_id: str,
        *,
        title: str | None = None,
        source_computer: str | None = None,
    ) -> None:
        """Notify local listeners via tmux injection."""
        target_session = await db.get_session(target_session_id)
        display_title = title or (target_session.title if target_session else "Unknown")
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
