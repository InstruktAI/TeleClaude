"""Consume messages from Redis Stream channels using consumer groups."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from instrukt_ai_logging import get_logger
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from teleclaude.channels.types import ConsumedMessage

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConsumerGroupSpec:
    """Consumer group information for Redis stream reads."""

    group: str
    consumer: str


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


def _decode_redis_value(value: bytes | str) -> str:
    """Decode a Redis bytes-or-string value into text."""
    return value.decode() if isinstance(value, bytes) else value


def _parse_consumed_message(
    msg_id: bytes | str,
    fields: dict[bytes | str, bytes | str],
) -> tuple[ConsumedMessage | None, bytes | str]:
    """Parse one Redis stream entry into a consumed message and ack id."""
    decoded_id = _decode_redis_value(msg_id)
    payload_raw = fields.get(b"payload") or fields.get("payload")
    if payload_raw is None:
        logger.warning("Message %s has no payload field; acknowledging to prevent redelivery", decoded_id)
        return None, msg_id

    payload_str = _decode_redis_value(payload_raw)
    try:
        parsed_payload = json.loads(payload_str)
    except json.JSONDecodeError:
        parsed_payload = {"raw": payload_str}

    payload: dict[str, Any] = parsed_payload  # guard: loose-dict - Channel payload is arbitrary user JSON
    return ConsumedMessage(id=decoded_id, payload=payload), msg_id


def _resolve_consumer_group(
    consumer_group: ConsumerGroupSpec | str,
    group_args: tuple[str, ...],
) -> tuple[str, str]:
    """Normalize consumer-group inputs across legacy and structured call styles."""
    if isinstance(consumer_group, ConsumerGroupSpec):
        return consumer_group.group, consumer_group.consumer
    if not group_args:
        raise TypeError("consumer name is required when consumer_group is passed as a string")
    return consumer_group, group_args[0]


def _collect_consumed_messages(
    raw: list[tuple[bytes | str, list[tuple[bytes | str, dict[bytes | str, bytes | str]]]]],
) -> tuple[list[ConsumedMessage], list[bytes | str]]:
    """Decode consumed Redis entries and collect ack ids."""
    messages: list[ConsumedMessage] = []
    ack_ids: list[bytes | str] = []
    for _stream_name, entries in raw:
        for msg_id, fields in entries:
            message, ack_id = _parse_consumed_message(msg_id, fields)
            if message is not None:
                messages.append(message)
            ack_ids.append(ack_id)
    return messages, ack_ids


async def consume(
    redis: Redis,
    channel: str,
    consumer_group: ConsumerGroupSpec | str,
    *group_args: str,
    count: int = 10,
    block_ms: int = 0,
) -> list[ConsumedMessage]:
    """Read new messages from a channel consumer group.

    Args:
        redis: Connected Redis client.
        channel: Full channel key (e.g. ``channel:myproject:events``).
        group: Consumer group name.
        count: Maximum messages to read per call.
        block_ms: How long to block waiting for messages (0 = no block).

    Returns:
        List of ConsumedMessage dicts with ``id`` and ``payload`` fields.  Each
        message is automatically acknowledged after being returned.
    """
    group_name, consumer_name = _resolve_consumer_group(consumer_group, group_args)

    raw = await redis.xreadgroup(
        group_name,
        consumer_name,
        {channel: ">"},
        count=count,
        block=block_ms if block_ms > 0 else None,
    )
    if not raw:
        return []

    messages, ack_ids = _collect_consumed_messages(raw)

    if ack_ids:
        await redis.xack(channel, group_name, *ack_ids)

    return messages
