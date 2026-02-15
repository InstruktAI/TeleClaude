"""Consume messages from Redis Stream channels using consumer groups."""

from __future__ import annotations

import json
from typing import Any

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from teleclaude.channels.types import ConsumedMessage

logger = get_logger(__name__)


async def ensure_consumer_group(redis: Redis, channel: str, group: str) -> None:
    """Create a consumer group if it does not already exist.

    Uses ``MKSTREAM`` so the stream is created if absent.
    """
    try:
        await redis.xgroup_create(channel, group, id="0", mkstream=True)
        logger.info("Created consumer group %s on %s", group, channel)
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            pass  # group already exists
        else:
            raise


async def consume(
    redis: Redis,
    channel: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 0,
) -> list[ConsumedMessage]:
    """Read new messages from a channel consumer group.

    Args:
        redis: Connected Redis client.
        channel: Full channel key (e.g. ``channel:myproject:events``).
        group: Consumer group name.
        consumer: Consumer name within the group.
        count: Maximum messages to read per call.
        block_ms: How long to block waiting for messages (0 = no block).

    Returns:
        List of ConsumedMessage dicts with ``id`` and ``payload`` fields.  Each
        message is automatically acknowledged after being returned.
    """
    raw = await redis.xreadgroup(
        group,
        consumer,
        {channel: ">"},
        count=count,
        block=block_ms if block_ms > 0 else None,
    )
    if not raw:
        return []

    messages: list[ConsumedMessage] = []
    ack_ids: list[bytes | str] = []
    for _stream_name, entries in raw:
        for msg_id, fields in entries:
            decoded_id = msg_id.decode() if hasattr(msg_id, "decode") else str(msg_id)
            payload_raw = fields.get(b"payload") or fields.get("payload")
            if payload_raw is None:
                logger.warning("Message %s has no payload field; acknowledging to prevent redelivery", decoded_id)
                ack_ids.append(msg_id)
                continue
            payload_str = payload_raw.decode() if hasattr(payload_raw, "decode") else str(payload_raw)
            try:
                parsed = json.loads(payload_str)
            except json.JSONDecodeError:
                parsed = {"raw": payload_str}
            payload: dict[str, Any] = parsed  # guard: loose-dict - Channel payload is arbitrary user JSON
            messages.append(ConsumedMessage(id=decoded_id, payload=payload))
            ack_ids.append(msg_id)

    if ack_ids:
        await redis.xack(channel, group, *ack_ids)

    return messages
