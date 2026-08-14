"""Telegram delivery adapter — sends high-level event notifications via Telegram DM."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.cartridges.notification import PushNotificationChange
from teleclaude.events.delivery.message import format_notification_message

logger = get_logger(__name__)


class TelegramDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to Telegram for actionable events."""

    def __init__(
        self,
        chat_id: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        shutdown_check: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize the adapter for one Telegram chat."""
        self._chat_id = chat_id
        self._send_fn = send_fn
        self._shutdown_check = shutdown_check or (lambda: False)

    def recipient(self) -> str:
        """Return the Telegram chat id targeted by this adapter."""
        return self._chat_id

    async def on_notification(
        self,
        change: PushNotificationChange,
    ) -> None:
        """Deliver a notification callback to Telegram when it is actionable and carries meaningful content."""
        if self._shutdown_check():
            return
        try:
            message = format_notification_message(change)
            await self._send_fn(chat_id=self._chat_id, content=message)
        except Exception:
            logger.exception(
                "TelegramDeliveryAdapter failed to send",
                event_type=change.event_type,
                notification_id=change.notification_id,
            )
