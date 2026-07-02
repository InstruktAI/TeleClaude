"""Discord delivery adapter — sends high-level event notifications via Discord DM."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class DiscordDeliveryAdapter:
    """Receives pipeline push callbacks and delivers to Discord for actionable events."""

    def __init__(
        self,
        user_id: str,
        send_fn: Callable[..., Coroutine[Any, Any, str]],
        shutdown_check: Callable[[], bool] | None = None,
    ) -> None:
        """Initialize the adapter for one Discord user."""
        self._user_id = user_id
        self._send_fn = send_fn
        self._shutdown_check = shutdown_check or (lambda: False)

    def recipient(self) -> str:
        """Return the Discord user id targeted by this adapter."""
        return self._user_id

    async def on_notification(
        self,
        notification_id: int,
        event_type: str,
        _level: int,
        was_created: bool,
        is_meaningful: bool,
        actionable: bool,
    ) -> None:
        """Deliver a notification callback to Discord when it is actionable and carries meaningful content."""
        if not actionable or not (was_created or is_meaningful):
            return
        if self._shutdown_check():
            return
        try:
            verb = "created" if was_created else "updated"
            message = f"[{event_type}] Notification #{notification_id} {verb}."
            await self._send_fn(user_id=self._user_id, content=message)
        except Exception:
            logger.exception(
                "DiscordDeliveryAdapter failed to send",
                event_type=event_type,
                notification_id=notification_id,
            )
