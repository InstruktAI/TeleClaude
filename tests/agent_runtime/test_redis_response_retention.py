"""Functional check for ephemeral Redis response-stream retention."""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Self, cast

import pytest

from teleclaude.transport.redis_transport._request_response import _RequestResponseMixin

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]


class _RedisMemory:
    def __init__(self) -> None:
        self.stream: str | None = None
        self.ttl: int | None = None

    def pipeline(self, transaction: bool = True) -> _RedisTransaction:
        return _RedisTransaction(self, transaction=transaction)


class _RedisTransaction:
    def __init__(self, redis: _RedisMemory, *, transaction: bool) -> None:
        self._redis = redis
        self._transaction = transaction
        self._stream: str | None = None
        self._ttl: int | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def xadd(self, stream: str, data: dict[bytes, bytes], *, maxlen: int) -> Self:
        del data, maxlen
        self._stream = stream
        return self

    def expire(self, stream: str, ttl: int) -> Self:
        assert stream == self._stream
        self._ttl = ttl
        return self

    async def execute(self) -> list[bytes | bool]:
        assert self._transaction
        assert self._stream is not None
        assert self._ttl is not None
        self._redis.stream = self._stream
        self._redis.ttl = self._ttl
        return [b"1-0", True]


class _RedisResponseBoundary(_RequestResponseMixin):
    def __init__(self) -> None:
        self.computer_name = "local"
        self.message_stream_maxlen = 100
        self.output_stream_maxlen = 10
        self.output_stream_ttl = 3600
        self.redis = _RedisMemory()

    async def _get_redis(self) -> Redis:
        return cast("Redis", self.redis)


async def test_one_shot_response_stream_expires_at_configured_ttl() -> None:
    boundary = _RedisResponseBoundary()

    response_id = await boundary.send_response("request-id", "response")

    assert response_id
    assert boundary.redis.stream is not None
    assert boundary.redis.ttl == boundary.output_stream_ttl
