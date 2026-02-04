"""Event guard helpers for consistent error handling."""

from __future__ import annotations

from typing import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.core.events import ErrorEventContext, EventContext, EventType, TeleClaudeEvents

logger = get_logger(__name__)

EventHandler = Callable[[EventType, EventContext], Awaitable[object]]


def create_event_guard(
    handler: EventHandler,
    *,
    emit: Callable[[EventType, EventContext], None],
    handler_name: str | None = None,
) -> EventHandler:
    """Wrap handler to emit a standardized error event on failure."""

    name = handler_name or f"{handler.__module__}.{handler.__qualname__}"

    async def _guarded(event_name: EventType, context: EventContext) -> object:
        try:
            return await handler(event_name, context)
        except Exception as exc:
            logger.error("Event handler failed: %s (%s)", name, event_name, exc_info=True)
            if event_name != TeleClaudeEvents.ERROR:
                session_id = getattr(context, "session_id", None)
                emit(
                    TeleClaudeEvents.ERROR,
                    ErrorEventContext(
                        session_id=session_id,
                        message=str(exc),
                        source=name,
                        details={"event": event_name, "handler": name},
                        severity="error",
                        retryable=False,
                    ),
                )
            return None

    return _guarded
