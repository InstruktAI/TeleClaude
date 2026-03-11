"""Discord delivery adapter — sends high-level event notifications via Discord DM."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.events.envelope import EventLevel

logger = get_logger(__name__)


class DiscordDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to Discord for WORKFLOW+ events."""

    def __init__(
        self,
        user_id: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        min_level: int = int(EventLevel.WORKFLOW),
    ) -> None:
        self._user_id = user_id
        self._send_fn = send_fn
        self._min_level = min_level

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        level: int,
        was_created: bool,
        is_meaningful: bool,
    ) -> None:
        if not was_created:
            return
        if level < self._min_level:
            return
        try:
            message = f"[{event_type}] Notification #{notification_id} created."
            await self._send_fn(user_id=self._user_id, content=message)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception(
                "DiscordDeliveryAdapter failed to send",
                event_type=event_type,
                notification_id=notification_id,
            )
