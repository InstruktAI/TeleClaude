"""WhatsApp delivery adapter — sends high-level event notifications via WhatsApp."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventLevel

logger = get_logger(__name__)


class WhatsAppDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to WhatsApp for WORKFLOW+ events."""

    def __init__(
        self,
        phone_number: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        min_level: int = int(EventLevel.WORKFLOW),
    ) -> None:
        """Initialize the adapter for one WhatsApp recipient."""
        self._phone_number = phone_number
        self._send_fn = send_fn
        self._min_level = min_level

    def recipient(self) -> str:
        """Return the WhatsApp phone number targeted by this adapter."""
        return self._phone_number

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        level: int,
        was_created: bool,
        _is_meaningful: bool,
    ) -> None:  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Deliver a notification callback to WhatsApp when it meets the level threshold."""
        if not was_created:
            return
        if level < self._min_level:
            return
        try:
            message = f"[{event_type}] Notification #{notification_id} created."
            await self._send_fn(phone_number=self._phone_number, content=message)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "WhatsAppDeliveryAdapter failed to send",
                event_type=event_type,
                notification_id=notification_id,
            )
