"""Typed structures for the channels subsystem."""

from __future__ import annotations

from typing import TypeAlias

from typing_extensions import TypedDict

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


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
