"""Telegram delivery adapter — sends high-level event notifications via Telegram DM."""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from instrukt_ai_logging import get_logger

from teleclaude_events.envelope import EventLevel

logger = get_logger(__name__)


class TelegramDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to Telegram for WORKFLOW+ events."""

    def __init__(
        self,
        chat_id: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        min_level: int = int(EventLevel.WORKFLOW),
    ) -> None:
        self._chat_id = chat_id
        self._send_fn = send_fn
        self._min_level = min_level

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        was_created: bool,
        is_meaningful: bool,
    ) -> None:
        if not was_created:
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
