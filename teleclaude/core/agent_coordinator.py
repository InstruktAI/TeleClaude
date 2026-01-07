"""Agent Coordinator - orchestrates agent events and cross-computer communication.

Handles agent lifecycle events (start, stop, notification) and routes them to:
1. Local listeners (via terminal injection)
2. Remote initiators (via Redis transport)
3. Human UI (via AdapterClient feedback)
"""

import base64
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.core.db import db
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentNotificationPayload,
    AgentSessionEndPayload,
    AgentSessionStartPayload,
    AgentStopPayload,
)
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_listeners import get_listeners
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

        await db.update_ux_state(context.session_id, **update_kwargs)

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

        # Get agent info from UX state
        ux_state = await db.get_ux_state(session_id)
        if not ux_state or not ux_state.active_agent or not ux_state.thinking_mode:
            return  # No agent info available

        # Build new title with agent info
        new_title = update_title_with_agent(
            session.title,
            ux_state.active_agent,
            ux_state.thinking_mode,
            config.computer.name,
        )

        if new_title and new_title != session.title:
            await db.update_session(session_id, title=new_title)
            logger.info("Updated session title with agent info: %s", new_title)

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
            await self._forward_stop_to_initiator(session_id, title=title)

    async def handle_notification(self, context: AgentEventContext) -> None:
        """Handle notification event - input request."""
        session_id = context.session_id
        payload = cast(AgentNotificationPayload, context.data)
        message = payload.message

        # 1. Notify local listeners
        await self._forward_notification_to_listeners(session_id, str(message))

        # 2. Forward to remote initiator
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
        """Notify local listeners via terminal injection."""
        listeners = get_listeners(target_session_id)
        if not listeners:
            return

        target_session = await db.get_session(target_session_id)
        display_title = title or (target_session.title if target_session else "Unknown")
        computer_name = source_computer or "local"
        location_part = f" on {source_computer}" if source_computer else ""

        for listener in listeners:
            title_part = f' "{display_title}"' if title else f" ({display_title})"
            notification = (
                f"Session {target_session_id[:8]}{location_part}{title_part} finished its turn. "
                f"Use teleclaude__get_session_data(computer='{computer_name}', "
                f"session_id='{target_session_id}') to inspect."
            )

            delivered = await self._deliver_listener_message(
                listener.caller_session_id, listener.caller_tmux_session, notification
            )
            if delivered:
                logger.info("Notified caller %s", listener.caller_session_id[:8])
            else:
                logger.warning("Failed to notify caller %s", listener.caller_session_id[:8])

    async def _forward_stop_to_initiator(self, session_id: str, *, title: str | None = None) -> None:
        """Forward stop event to remote initiator via Redis."""
        session = await db.get_session(session_id)
        if not session:
            return

        redis_meta = session.adapter_metadata.redis
        if not redis_meta or not redis_meta.target_computer:
            return

        initiator_computer = redis_meta.target_computer
        if initiator_computer == config.computer.name:
            return

        title_arg = ""
        if title:
            title_b64 = base64.b64encode(title.encode()).decode()
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

    async def _forward_notification_to_listeners(self, target_session_id: str, message: str) -> None:
        """Forward notification to local listeners."""
        listeners = get_listeners(target_session_id)
        for listener in listeners:
            notification = (
                f"Session {target_session_id[:8]} needs input: {message} "
                f"Use teleclaude__send_message(computer='local', session_id='{target_session_id}', "
                f"message='your response') to respond."
            )
            delivered = await self._deliver_listener_message(
                listener.caller_session_id, listener.caller_tmux_session, notification
            )
            if not delivered:
                logger.warning("Failed to notify caller %s", listener.caller_session_id[:8])

    async def _deliver_listener_message(self, session_id: str, tmux_session: str, message: str) -> bool:
        """Deliver a notification to a listener via terminal delivery sink."""
        from teleclaude.core.terminal_delivery import deliver_listener_message

        return await deliver_listener_message(session_id, tmux_session, message)

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
