"""Typed models for TeleClaude CLI and TUI."""

from __future__ import annotations

from typing import TypeAlias, Union

from teleclaude.adapters.rest_models import (
    AgentAvailabilityDTO as AgentAvailabilityInfo,
)
from teleclaude.adapters.rest_models import (
    ComputerDTO as ComputerInfo,
)
from teleclaude.adapters.rest_models import (
    CreateSessionResponseDTO as CreateSessionResult,
)
from teleclaude.adapters.rest_models import (
    ProjectDTO as ProjectInfo,
)
from teleclaude.adapters.rest_models import (
    ProjectsInitialDataDTO as ProjectsInitialData,
)
from teleclaude.adapters.rest_models import (
    ProjectsInitialEventDTO as ProjectsInitialEvent,
)
from teleclaude.adapters.rest_models import (
    ProjectWithTodosDTO as ProjectWithTodosInfo,
)
from teleclaude.adapters.rest_models import (
    RefreshDataDTO as RefreshData,
)
from teleclaude.adapters.rest_models import (
    RefreshEventDTO as RefreshEvent,
)
from teleclaude.adapters.rest_models import (
    SessionRemovedDataDTO as SessionRemovedData,
)
from teleclaude.adapters.rest_models import (
    SessionRemovedEventDTO as SessionRemovedEvent,
)
from teleclaude.adapters.rest_models import (
    SessionsInitialDataDTO as SessionsInitialData,
)
from teleclaude.adapters.rest_models import (
    SessionsInitialEventDTO as SessionsInitialEvent,
)
from teleclaude.adapters.rest_models import (
    SessionSummaryDTO as SessionInfo,
)
from teleclaude.adapters.rest_models import (
    SessionUpdateEventDTO as SessionUpdateEvent,
)
from teleclaude.adapters.rest_models import (
    TodoDTO as TodoInfo,
)

__all__ = [
    "AgentAvailabilityInfo",
    "ComputerInfo",
    "CreateSessionResult",
    "ProjectInfo",
    "ProjectsInitialData",
    "ProjectsInitialEvent",
    "ProjectWithTodosInfo",
    "RefreshData",
    "RefreshEvent",
    "SessionRemovedData",
    "SessionRemovedEvent",
    "SessionsInitialData",
    "SessionsInitialEvent",
    "SessionInfo",
    "SessionUpdateEvent",
    "TodoInfo",
    "JsonValue",
    "JsonObject",
    "WsEvent",
    "SubscribeData",
    "UnsubscribeData",
    "SubscribeRequest",
    "UnsubscribeRequest",
]

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


WsEvent: TypeAlias = Union[
    SessionsInitialEvent, ProjectsInitialEvent, SessionUpdateEvent, SessionRemovedEvent, RefreshEvent
]


# Subscribe/Unsubscribe requests (not DTOs, strictly for CLI -> Server)


class SubscribeData:
    def __init__(self, computer: str, types: list[str]):
        self.computer = computer
        self.types = types


class UnsubscribeData:
    def __init__(self, computer: str):
        self.computer = computer


class SubscribeRequest:
    def __init__(self, subscribe: SubscribeData):
        self.subscribe = subscribe


class UnsubscribeRequest:
    def __init__(self, unsubscribe: UnsubscribeData):
        self.unsubscribe = unsubscribe
