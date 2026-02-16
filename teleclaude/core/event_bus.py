"""Global in-process event bus for TeleClaude."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Literal

from instrukt_ai_logging import get_logger
from typing_extensions import TypedDict

from teleclaude.core.event_guard import create_event_guard
from teleclaude.core.events import EventContext, EventType

logger = get_logger(__name__)

EventHandler = Callable[[EventType, EventContext], Awaitable[object]]


class DispatchEnvelope(TypedDict, total=False):
    status: Literal["success", "error"]
    data: object | None
    error: str
    code: str


class EventBus:
    """Simple async event bus for core events."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}

    def subscribe(self, event: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(create_event_guard(handler, emit=self.emit))
        logger.debug("Subscribed handler for event: %s (total: %d)", event, len(self._handlers[event]))

    def clear(self) -> None:
        """Clear all registered handlers (primarily for tests)."""
        self._handlers.clear()

    def emit(self, event: EventType, context: EventContext) -> None:
        """Emit an event to all handlers (fire-and-forget)."""
        handlers = self._handlers.get(event)
        if not handlers:
            logger.warning("No handler registered for event: %s", event)
            return

        loop = asyncio.get_running_loop()
        for handler in handlers:
            loop.create_task(handler(event, context))


event_bus = EventBus()
