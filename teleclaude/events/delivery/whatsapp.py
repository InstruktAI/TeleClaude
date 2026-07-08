"""WhatsApp delivery adapter — sends high-level event notifications via WhatsApp."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.delivery.debounce import should_deliver

logger = get_logger(__name__)


class WhatsAppDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to WhatsApp for actionable events."""

    def __init__(
        self,
        phone_number: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        shutdown_check: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize the adapter for one WhatsApp recipient."""
        self._phone_number = phone_number
        self._send_fn = send_fn
        self._shutdown_check = shutdown_check or (lambda: False)

    def recipient(self) -> str:
        """Return the WhatsApp phone number targeted by this adapter."""
        return self._phone_number

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        _level: int,
        was_created: bool,
        is_meaningful: bool,
        actionable: bool,
    ) -> None:
        """Deliver a notification callback to WhatsApp when it is actionable and carries meaningful content."""
        if not should_deliver(actionable, was_created, is_meaningful):
            return
        if self._shutdown_check():
            return
        try:
            verb = "created" if was_created else "updated"
            message = f"[{event_type}] Notification #{notification_id} {verb}."
            await self._send_fn(phone_number=self._phone_number, content=message)
        except Exception:
            logger.exception(
                "WhatsAppDeliveryAdapter failed to send",
                event_type=event_type,
                notification_id=notification_id,
            )
