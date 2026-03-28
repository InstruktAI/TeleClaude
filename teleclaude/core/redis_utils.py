"""Redis utility functions for non-blocking operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)


async def scan_keys(redis: Redis, pattern: str | bytes) -> list[bytes]:
    """
    Non-blocking alternative to KEYS command using SCAN cursor iteration.

    Unlike redis.keys() which blocks the server while scanning all keys,
    this function uses SCAN with a cursor to iterate through keys in
    batches, allowing the Redis server to continue serving other requests.

    Args:
        redis: Async Redis client instance
        pattern: Key pattern to match (e.g., "sessions:*", b"computer:*:heartbeat")

    Returns:
        List of matching key names as bytes

    Example:
        keys = await scan_keys(redis, "sessions:*")
        for key in keys:
            value = await redis.get(key)
    """
    # Ensure pattern is bytes
    if isinstance(pattern, str):
        pattern_bytes = pattern.encode("utf-8")
    else:
        pattern_bytes = pattern

    keys: list[bytes] = []
    cursor: int = 0

    while True:
        # SCAN returns (cursor, keys) tuple
        # count=100 is a hint to Redis for batch size
        result: tuple[int, list[bytes]] = await redis.scan(cursor, match=pattern_bytes, count=100)
        cursor, batch = result

        keys.extend(batch)

        # cursor == 0 indicates scan is complete
        if cursor == 0:
            break

    logger.debug("SCAN found %d keys matching pattern %s", len(keys), pattern)
    return keys
