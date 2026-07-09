"""Targeted notification delivery — routes an addressed recipient to its resolved channel.

An addressed actionable notification bypasses the admin fan-out entirely and
delivers to the addressed principal's own resolved channel. The three DM
channels (Telegram/Discord/WhatsApp) ride the shared trailing-debounce window
keyed on the resolved recipient, the same mechanism the admin adapters use;
email delivers immediately since it sits outside debounce's channel scope. An
unresolvable recipient withholds the push and logs a warning — it never falls
back to the admin fan-out, per
``project/design/architecture/notification-delivery#failure-modes``.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.config.schema import MessagingChannel
from teleclaude.core.person_messaging import (
    ChannelCredentialError,
    PersonNotFoundError,
    render_minimal_html,
    resolve_person_channel,
)
from teleclaude.events.delivery.debounce import DeliveryChannel, DeliveryDebouncer, should_deliver
from teleclaude.events.delivery.message import format_notification_message
from teleclaude.services.discord import send_discord_dm
from teleclaude.services.email import send_email
from teleclaude.services.telegram import send_telegram_dm
from teleclaude.services.whatsapp import send_whatsapp_message

logger = get_logger(__name__)

_EMAIL_SUBJECT_PREFIX = "TeleClaude notification"

_DM_DELIVERY_CHANNELS: dict[MessagingChannel, DeliveryChannel] = {
    MessagingChannel.TELEGRAM: DeliveryChannel.TELEGRAM,
    MessagingChannel.DISCORD: DeliveryChannel.DISCORD,
    MessagingChannel.WHATSAPP: DeliveryChannel.WHATSAPP,
}


async def _send_dm(channel: MessagingChannel, target: str, message: str) -> None:
    """Send ``message`` to ``target`` on a DM channel's existing send primitive."""
    if channel is MessagingChannel.TELEGRAM:
        await send_telegram_dm(target, message)
    elif channel is MessagingChannel.DISCORD:
        await send_discord_dm(target, message)
    else:
        await send_whatsapp_message(
            target,
            message,
            phone_number_id=config.whatsapp.phone_number_id or "",
            access_token=config.whatsapp.access_token or "",
            api_version=config.whatsapp.api_version,
        )


async def _send_targeted_email(target: str, message: str, event_type: str) -> None:
    """Send ``message`` to ``target`` via the email send primitive, immediately."""
    subject = f"{_EMAIL_SUBJECT_PREFIX}: {event_type}"
    await send_email(target, subject, render_minimal_html(message), message)


def build_targeted_push_callback(
    debouncer: DeliveryDebouncer,
) -> Callable[[int, str, int, bool, bool, bool, str, float | None, str | None], Coroutine[Any, Any, None]]:
    """Build the push callback that routes an addressed recipient to its resolved channel.

    A no-op when the projected change carries no recipient (the broadcast path
    handles those). DM channels schedule through ``debouncer``, the same
    instance the admin adapters share, keyed on the resolved send target; email
    delivers immediately. An unresolvable recipient withholds delivery and logs
    a warning instead of falling back to the admin fan-out.
    """

    async def _on_notification(
        notification_id: int,
        event_type: str,
        _level: int,
        was_created: bool,
        is_meaningful: bool,
        actionable: bool,
        group_identity: str,
        delivery_debounce_s: float | None,
        recipient: str | None,
    ) -> None:
        if recipient is None:
            return
        if not should_deliver(actionable, was_created, is_meaningful):
            return

        try:
            resolved = resolve_person_channel(recipient)
        except (PersonNotFoundError, ChannelCredentialError) as exc:
            logger.warning(
                "targeted notification recipient unresolvable",
                notification_id=notification_id,
                event_type=event_type,
                recipient=recipient,
                error=str(exc),
            )
            return

        message = format_notification_message(event_type, notification_id, was_created)

        if resolved.channel is MessagingChannel.EMAIL:
            await _send_targeted_email(resolved.target, message, event_type)
            return

        delivery_channel = _DM_DELIVERY_CHANNELS[resolved.channel]

        async def _runner() -> None:
            await _send_dm(resolved.channel, resolved.target, message)

        debouncer.schedule(
            channel=delivery_channel,
            recipient=resolved.target,
            event_type=event_type,
            group_identity=group_identity,
            debounce_s=delivery_debounce_s,
            runner=_runner,
        )

    return _on_notification
