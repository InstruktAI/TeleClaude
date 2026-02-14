"""Bridge between internal event bus and the webhook hook dispatcher."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.events import (
    AgentActivityEvent,
    AgentEventContext,
    ErrorEventContext,
    EventContext,
    EventType,
    SessionLifecycleContext,
    TeleClaudeEvents,
)
from teleclaude.hooks.webhook_models import HookEvent

if TYPE_CHECKING:
    from teleclaude.hooks.dispatcher import HookDispatcher

logger = get_logger(__name__)

# Map internal EventType to HookEvent source
_SOURCE_MAP: dict[str, str] = {
    "session_started": "system",
    "session_closed": "system",
    "session_updated": "system",
    "agent_event": "agent",
    "agent_activity": "agent",
    "error": "system",
    "system_command": "system",
}


class EventBusBridge:
    """Subscribes to the internal event bus and forwards events to the hook dispatcher."""

    def __init__(self, dispatcher: HookDispatcher) -> None:
        self._dispatcher = dispatcher

    def register(self, event_bus: object) -> None:
        """Subscribe to all event types on the bus.

        Args:
            event_bus: The EventBus instance to subscribe to.
        """
        from teleclaude.core.event_bus import EventBus

        bus = event_bus
        if not isinstance(bus, EventBus):
            raise TypeError(f"Expected EventBus, got {type(bus)}")

        for event_type in (
            TeleClaudeEvents.SESSION_STARTED,
            TeleClaudeEvents.SESSION_CLOSED,
            TeleClaudeEvents.SESSION_UPDATED,
            TeleClaudeEvents.AGENT_EVENT,
            TeleClaudeEvents.AGENT_ACTIVITY,
            TeleClaudeEvents.ERROR,
        ):
            bus.subscribe(event_type, self._handle)

    async def _handle(self, event_type: EventType, context: EventContext) -> None:
        """Normalize internal event to HookEvent and dispatch."""
        source = _SOURCE_MAP.get(event_type, "system")
        properties: dict[str, str | int | float | bool | list[str] | None] = {}
        payload: Mapping[str, object] = {}

        if isinstance(context, SessionLifecycleContext):
            properties["session_id"] = context.session_id
            hook_type = f"session.{event_type.replace('session_', '')}"

        elif isinstance(context, AgentEventContext):
            properties["session_id"] = context.session_id
            properties["agent_event_type"] = context.event_type
            hook_type = f"agent.{context.event_type}"
            if hasattr(context.data, "raw"):
                payload = dict(context.data.raw)

        elif isinstance(context, AgentActivityEvent):
            properties["session_id"] = context.session_id
            properties["agent_event_type"] = context.event_type
            if context.tool_name:
                properties["tool_name"] = context.tool_name
            hook_type = f"agent.activity.{context.event_type}"

        elif isinstance(context, ErrorEventContext):
            if context.session_id:
                properties["session_id"] = context.session_id
            properties["severity"] = context.severity
            if context.source:
                properties["error_source"] = context.source
            if context.code:
                properties["error_code"] = context.code
            hook_type = f"error.{context.severity}"
            payload = {"message": context.message}

        else:
            hook_type = event_type

        event = HookEvent.now(
            source=source,
            type=hook_type,
            properties=properties,
            payload=payload,
        )

        try:
            await self._dispatcher.dispatch(event)
        except Exception as exc:
            logger.error("Bridge dispatch failed: %s", exc, exc_info=True)
