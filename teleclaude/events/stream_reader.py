"""Read the platform event stream in append order for the item trail."""

from __future__ import annotations

from typing import Any, Final

from redis.exceptions import RedisError

from teleclaude.events.wire import StreamEntry

STREAM_ID_SEPARATOR: Final = "-"
FIRST: Final = "-"
LAST: Final = "+"
SINGLE: Final = 1


class StreamUnavailable(Exception):
    """The retained stream could not be read: the backend failed, so nothing about its content is established."""


def _after(position: str) -> str:
    """The smallest position after ``position``."""
    millis, _, sequence = position.partition(STREAM_ID_SEPARATOR)
    return f"{millis}{STREAM_ID_SEPARATOR}{int(sequence) + 1}"


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class RedisStreamReader:
    """The retained platform stream, read through the producer\'s own client."""

    def __init__(self, redis_client: Any, stream: str, capacity: int) -> None:
        self._redis = redis_client
        self._stream = stream
        self.capacity = capacity

    async def length(self) -> int:
        try:
            return int(await self._redis.xlen(self._stream))
        except (RedisError, OSError, RuntimeError, ValueError) as error:
            raise StreamUnavailable(str(error) or type(error).__name__) from error

    async def oldest(self) -> str | None:
        try:
            found = await self._redis.xrange(self._stream, min=FIRST, max=LAST, count=SINGLE)
        except (RedisError, OSError, RuntimeError, ValueError) as error:
            raise StreamUnavailable(str(error) or type(error).__name__) from error
        return _text(found[0][0]) if found else None

    async def newest(self) -> str | None:
        try:
            found = await self._redis.xrevrange(self._stream, max=LAST, min=FIRST, count=SINGLE)
        except (RedisError, OSError, RuntimeError, ValueError) as error:
            raise StreamUnavailable(str(error) or type(error).__name__) from error
        return _text(found[0][0]) if found else None

    async def entries(self, after: str | None, through: str, count: int) -> list[tuple[str, StreamEntry]]:
        start = _after(after) if after is not None else FIRST
        try:
            found = await self._redis.xrange(self._stream, min=start, max=through, count=count)
        except (RedisError, OSError, RuntimeError, ValueError) as error:
            raise StreamUnavailable(str(error) or type(error).__name__) from error
        return [(_text(entry_id), fields) for entry_id, fields in found]
