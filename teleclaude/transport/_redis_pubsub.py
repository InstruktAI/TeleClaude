"""Shared Redis pub/sub surface consumed by transport bridges."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class RedisPubSub(Protocol):
    """Redis pub/sub methods used by transport bridges."""

    async def psubscribe(self, *patterns: str) -> object: ...

    async def get_message(self, *, ignore_subscribe_messages: bool, timeout: float) -> Mapping[str, object] | None: ...

    async def punsubscribe(self, *patterns: str) -> object: ...

    async def aclose(self) -> object: ...
