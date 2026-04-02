"""Typed models for TeleClaude CLI and TUI."""

from __future__ import annotations

from teleclaude.api_models import (
    AgentActivityEventDTO,
    AgentAvailabilityEventDTO,
    ChiptunesStateEventDTO,
    ChiptunesTrackEventDTO,
    ErrorEventDTO,
    ProjectsInitialEventDTO,
    RefreshEventDTO,
    SessionClosedEventDTO,
    SessionLifecycleStatusEventDTO,
    SessionsInitialEventDTO,
    SessionStartedEventDTO,
    SessionUpdatedEventDTO,
)

__all__ = [
    "JsonObject",
    "JsonValue",
    "SubscribeData",
    "SubscribeRequest",
    "UnsubscribeData",
    "UnsubscribeRequest",
    "WsEvent",
]

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


type WsEvent = (
    SessionsInitialEventDTO
    | ProjectsInitialEventDTO
    | SessionStartedEventDTO
    | SessionUpdatedEventDTO
    | SessionClosedEventDTO
    | SessionLifecycleStatusEventDTO
    | RefreshEventDTO
    | ErrorEventDTO
    | AgentAvailabilityEventDTO
    | AgentActivityEventDTO
    | ChiptunesStateEventDTO
    | ChiptunesTrackEventDTO
)


# Subscribe/Unsubscribe requests (not DTOs, strictly for CLI -> Server)


class SubscribeData:  # pylint: disable=too-few-public-methods
    """Data payload for a channel subscription request."""

    def __init__(self, computer: str, types: list[str]):
        self.computer = computer
        self.types = types


class UnsubscribeData:  # pylint: disable=too-few-public-methods
    """Data payload for a channel unsubscription request."""

    def __init__(self, computer: str):
        self.computer = computer


class SubscribeRequest:  # pylint: disable=too-few-public-methods
    """WebSocket subscribe request envelope."""

    def __init__(self, subscribe: SubscribeData):
        self.subscribe = subscribe


class UnsubscribeRequest:  # pylint: disable=too-few-public-methods
    """WebSocket unsubscribe request envelope."""

    def __init__(self, unsubscribe: UnsubscribeData):
        self.unsubscribe = unsubscribe
