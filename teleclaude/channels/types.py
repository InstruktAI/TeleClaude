"""Typed structures for the channels subsystem."""

from __future__ import annotations

from typing import Any, TypedDict


class ChannelInfo(TypedDict):
    """Description of an active Redis Stream channel."""

    key: str
    project: str
    topic: str
    length: int


class ConsumedMessage(TypedDict):
    """A single message read from a consumer group."""

    id: str
    payload: dict[str, Any]  # guard: loose-dict - Channel payload is arbitrary user JSON
