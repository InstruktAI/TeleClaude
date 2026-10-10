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
from teleclaude.api_models_operations import OperationFailedEventDTO, OperationSucceededEventDTO

__all__ = [
    "JsonObject",
    "JsonValue",
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
    | OperationSucceededEventDTO
    | OperationFailedEventDTO
)
