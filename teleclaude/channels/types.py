"""Typed structures for the channels subsystem."""

from __future__ import annotations

from typing import TypedDict

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]


class ChannelInfo(TypedDict):
    """Description of an active Redis Stream channel."""

    key: str
    project: str
    topic: str
    length: int


class ConsumedMessage(TypedDict):
    """A single message read from a consumer group."""

    id: str
    payload: dict[str, JsonValue]
