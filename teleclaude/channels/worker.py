"""Background worker that polls subscribed channels and dispatches to targets."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from instrukt_ai_logging import get_logger

from teleclaude.channels.consumer import consume, ensure_consumer_group

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from teleclaude.config.schema import ChannelSubscription

logger = get_logger(__name__)

# Consumer group / consumer name for the subscription worker
_WORKER_GROUP = "teleclaude-worker"
_WORKER_CONSUMER = "main"

# Polling interval when no messages are received
_POLL_INTERVAL_S = 5.0


async def _dispatch_to_target(
    target: dict[str, Any],  # guard: loose-dict - Subscription target schema is intentionally unstructured
    payload: dict[str, Any],  # guard: loose-dict - Channel payload is arbitrary user JSON
) -> None:
    """Route a consumed message to the subscription target.

    Supported target types:
    - ``{"type": "notification", "channel": "..."}`` -- queue a notification
    - ``{"type": "command", "project": "...", "command": "..."}`` -- run agent command
    """
    target_type = target.get("type", "notification")

    if target_type == "notification":
        notification_channel = target.get("channel", "telegram")
        message = payload.get("summary") or payload.get("message") or str(payload)
        logger.info(
            "Channel dispatch -> notification",
            notification_channel=notification_channel,
            message_preview=message[:80],
        )
        # Notification enqueue requires per-recipient routing via the NotificationRouter.
        # The worker logs the intent; full delivery integration is deferred to daemon wiring.
        logger.debug("Notification dispatch recorded", target=target)

    elif target_type == "command":
        project = target.get("project", "")
        command = target.get("command", "")
        logger.info("Channel dispatch -> command", project=project, command=command)
        # Command dispatch is deferred to a future integration point.
        # For now, log intent without execution.
        logger.debug("Command dispatch not yet wired", target=target)

    else:
        logger.warning("Unknown subscription target type: %s", target_type)


def _matches_filter(
    msg_filter: dict[str, Any] | None,  # guard: loose-dict - Subscription filter is intentionally unstructured
    payload: dict[str, Any],  # guard: loose-dict - Channel payload is arbitrary user JSON
) -> bool:
    """Check whether a message payload satisfies the subscription filter.

    When *msg_filter* is ``None`` or empty, every message matches.  Otherwise
    each key in the filter must be present in the payload with an equal value.
    """
    if not msg_filter:
        return True
    return all(payload.get(k) == v for k, v in msg_filter.items())


async def run_subscription_worker(
    redis: "Redis",
    subscriptions: list["ChannelSubscription"],
    *,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Poll subscribed channels and dispatch matched messages.

    This coroutine runs indefinitely (until *shutdown_event* is set or the task
    is cancelled).  It creates consumer groups as needed, then enters a polling
    loop that reads from each channel and dispatches matching messages to their
    configured targets.

    Args:
        redis: Connected async Redis client.
        subscriptions: Channel subscriptions from config.
        shutdown_event: Optional event that signals graceful shutdown.
    """
    if not subscriptions:
        logger.info("No channel subscriptions configured; worker idle")
        return

    # Ensure consumer groups exist for all subscribed channels.
    for sub in subscriptions:
        try:
            await ensure_consumer_group(redis, sub.channel, _WORKER_GROUP)
        except Exception:  # noqa: BLE001 - skip broken channels, keep others alive
            logger.warning("Failed to create consumer group for %s", sub.channel)

    logger.info("Channel subscription worker started", subscription_count=len(subscriptions))

    while True:
        if shutdown_event and shutdown_event.is_set():
            break

        for sub in subscriptions:
            try:
                messages = await consume(
                    redis,
                    sub.channel,
                    _WORKER_GROUP,
                    _WORKER_CONSUMER,
                    count=10,
                    block_ms=0,
                )
            except Exception:  # noqa: BLE001 - resilient polling
                logger.warning("Channel consume error on %s", sub.channel, exc_info=True)
                continue

            for msg in messages:
                if not _matches_filter(sub.filter, msg["payload"]):
                    continue
                try:
                    await _dispatch_to_target(sub.target, msg["payload"])
                except Exception:  # noqa: BLE001 - never crash the worker on a single dispatch
                    logger.warning("Dispatch failed for message %s on %s", msg["id"], sub.channel, exc_info=True)

        try:
            await asyncio.sleep(_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            break

    logger.info("Channel subscription worker stopped")
