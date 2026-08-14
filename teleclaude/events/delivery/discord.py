"""Discord delivery adapter — sends high-level event notifications via Discord DM."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.core.person_messaging import DISCORD_BACKLINK_BUILT_LOG, DISCORD_BACKLINK_MISS_LOG
from teleclaude.events.cartridges.notification import PushNotificationChange
from teleclaude.events.delivery.message import format_notification_message
from teleclaude.services.discord import render_discord_backlink

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
        change: PushNotificationChange,
    ) -> None:
        """Deliver a notification callback to Discord when it is actionable and carries meaningful content."""
        if self._shutdown_check():
            return
        try:
            message = format_notification_message(change)
            if change.discord_backlink_url:
                message, _ = render_discord_backlink(message, change.discord_backlink_url)
            message_id = await self._send_fn(user_id=self._user_id, content=message)
            if change.discord_backlink_url:
                logger.info(
                    DISCORD_BACKLINK_BUILT_LOG,
                    origin_session_id=change.human_action.origin_session_id if change.human_action else None,
                    notification_id=change.notification_id,
                    destination=self._user_id,
                    backlink_url=change.discord_backlink_url,
                    message_id=message_id,
                )
            elif change.discord_backlink_miss_reason:
                logger.info(
                    DISCORD_BACKLINK_MISS_LOG,
                    origin_session_id=change.human_action.origin_session_id if change.human_action else None,
                    notification_id=change.notification_id,
                    destination=self._user_id,
                    reason=change.discord_backlink_miss_reason,
                )
        except Exception:
            logger.exception(
                "DiscordDeliveryAdapter failed to send",
                event_type=change.event_type,
                notification_id=change.notification_id,
            )
