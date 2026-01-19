"""Global in-process event bus for TeleClaude."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.core.events import EventContext, EventType

logger = get_logger(__name__)

EventHandler = Callable[[EventType, EventContext], Awaitable[object]]


class EventBus:
    """Simple async event bus for core events."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}

    def subscribe(self, event: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)
        logger.trace("Subscribed handler for event: %s (total: %d)", event, len(self._handlers[event]))

    async def emit(self, event: EventType, context: EventContext) -> dict[str, object]:
        """Emit an event to all handlers."""
        handlers = self._handlers.get(event)
        if not handlers:
            logger.warning("No handler registered for event: %s", event)
            return {"status": "error", "error": f"No handler registered for event: {event}", "code": "NO_HANDLER"}

        tasks = [handler(event, context) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_results: list[object] = []
        errors: list[Exception] = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Handler %d failed for event %s: %s", i, event, result, exc_info=True)
                errors.append(result)
            else:
                success_results.append(result)

        if success_results:
            logger.debug(
                "Dispatch completed for event: %s (%d success, %d failed)", event, len(success_results), len(errors)
            )
            return {"status": "success", "data": success_results[0]}

        if errors:
            raise errors[0]

        return {"status": "success", "data": None}
