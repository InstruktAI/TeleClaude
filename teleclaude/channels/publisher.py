"""Publish messages to Redis Stream channels."""

from __future__ import annotations

import json
from typing import Any

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis

from teleclaude.channels.types import ChannelInfo

logger = get_logger(__name__)

CHANNEL_PREFIX = "channel"


def channel_key(project: str, topic: str) -> str:
    """Build the canonical Redis Stream key for a channel."""
    return f"{CHANNEL_PREFIX}:{project}:{topic}"


async def publish(
    redis: Redis,
    channel: str,
    payload: dict[str, Any],  # guard: loose-dict - Channel payload is arbitrary user JSON
) -> str:
    """Publish a message to a Redis Stream channel.

    Publishing to a non-existent channel creates it automatically (Redis Streams behavior).

    Args:
        redis: Connected Redis client.
        channel: Full channel key (e.g. ``channel:myproject:events``).
        payload: Arbitrary JSON-serialisable dict.

    Returns:
        The Redis Stream message ID.
    """
    msg_id = await redis.xadd(channel, {"payload": json.dumps(payload)})
    decoded = msg_id.decode() if hasattr(msg_id, "decode") else str(msg_id)
    logger.info("Published to %s: %s", channel, decoded)
    return decoded


async def list_channels(redis: Redis, project: str | None = None) -> list[ChannelInfo]:
    """List active channels by scanning Redis Stream keys.

    Args:
        redis: Connected Redis client.
        project: Optional project filter. When provided, only channels matching
                 ``channel:{project}:*`` are returned.

    Returns:
        List of ChannelInfo dicts with ``key``, ``project``, ``topic``, and ``length`` fields.
    """
    pattern = f"{CHANNEL_PREFIX}:{project}:*" if project else f"{CHANNEL_PREFIX}:*"
    channels: list[ChannelInfo] = []
    async for key_bytes in redis.scan_iter(match=pattern, _type="stream"):
        key = key_bytes.decode() if hasattr(key_bytes, "decode") else str(key_bytes)
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        length = await redis.xlen(key)
        channels.append(
            ChannelInfo(
                key=key,
                project=parts[1],
                topic=parts[2],
                length=length,
            )
        )
    return channels
