"""Telegram delivery adapter — sends high-level event notifications via Telegram DM."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventLevel

logger = get_logger(__name__)


class TelegramDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to Telegram for WORKFLOW+ events."""

    def __init__(
        self,
        chat_id: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        min_level: int = int(EventLevel.WORKFLOW),
    ) -> None:
        """Initialize the adapter for one Telegram chat."""
        self._chat_id = chat_id
        self._send_fn = send_fn
        self._min_level = min_level

    def recipient(self) -> str:
        """Return the Telegram chat id targeted by this adapter."""
        return self._chat_id

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        level: int,
        was_created: bool,
        _is_meaningful: bool,
    ) -> None:  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Deliver a notification callback to Telegram when it meets the level threshold."""
        if not was_created:
            return
        if level < self._min_level:
            return
        try:
            message = f"[{event_type}] Notification #{notification_id} created."
            await self._send_fn(chat_id=self._chat_id, content=message)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "TelegramDeliveryAdapter failed to send",
                event_type=event_type,
                notification_id=notification_id,
            )
