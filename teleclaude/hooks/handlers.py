"""Internal handler registry for webhook service."""

from __future__ import annotations

from typing import Awaitable, Callable

from instrukt_ai_logging import get_logger

from teleclaude.hooks.webhook_models import HookEvent

logger = get_logger(__name__)

InternalHandler = Callable[[HookEvent], Awaitable[None]]


class HandlerRegistry:
    """Registry for internal event handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, InternalHandler] = {}

    def register(self, key: str, handler: InternalHandler) -> None:
        """Register an internal handler."""
        self._handlers[key] = handler
        logger.debug("Registered internal handler: %s", key)

    def get(self, key: str) -> InternalHandler | None:
        """Get a handler by key."""
        return self._handlers.get(key)

    def keys(self) -> list[str]:
        """List all registered handler keys."""
        return list(self._handlers.keys())
