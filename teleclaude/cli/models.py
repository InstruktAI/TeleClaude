"""Typed models for TeleClaude CLI and TUI."""

from __future__ import annotations

from typing import TypeAlias

from teleclaude.api_models import (
    AgentActivityEventDTO as AgentActivityEvent,
)
from teleclaude.api_models import (
    AgentAvailabilityDTO as AgentAvailabilityInfo,
)
from teleclaude.api_models import (
    ChiptunesCommandReceiptDTO as ChiptunesCommandReceiptInfo,
)
from teleclaude.api_models import (
    ChiptunesStateEventDTO as ChiptunesStateEvent,
)
from teleclaude.api_models import (
    ChiptunesStatusDTO as ChiptunesStatusInfo,
)
from teleclaude.api_models import (
    ChiptunesTrackEventDTO as ChiptunesTrackEvent,
)
from teleclaude.api_models import (
    ComputerDTO as ComputerInfo,
)
from teleclaude.api_models import (
    CreateSessionResponseDTO as CreateSessionResult,
)
from teleclaude.api_models import (
    ErrorEventDTO as ErrorEvent,
)
from teleclaude.api_models import (
    JobDTO as JobInfo,
)
from teleclaude.api_models import (
    ProjectDTO as ProjectInfo,
)
from teleclaude.api_models import (
    ProjectsInitialDataDTO as ProjectsInitialData,
)
from teleclaude.api_models import (
    ProjectsInitialEventDTO as ProjectsInitialEvent,
)
from teleclaude.api_models import (
    ProjectWithTodosDTO as ProjectWithTodosInfo,
)
from teleclaude.api_models import (
    RefreshDataDTO as RefreshData,
)
from teleclaude.api_models import (
    RefreshEventDTO as RefreshEvent,
)
from teleclaude.api_models import (
    SessionClosedDataDTO as SessionClosedData,
)
from teleclaude.api_models import (
    SessionClosedEventDTO as SessionClosedEvent,
)
from teleclaude.api_models import (
    SessionDTO as SessionInfo,
)
from teleclaude.api_models import (
    SessionLifecycleStatusEventDTO as SessionLifecycleStatusEvent,
)
from teleclaude.api_models import (
    SessionsInitialDataDTO as SessionsInitialData,
)
from teleclaude.api_models import (
    SessionsInitialEventDTO as SessionsInitialEvent,
)
from teleclaude.api_models import (
    SessionStartedEventDTO as SessionStartedEvent,
)
from teleclaude.api_models import (
    SessionUpdatedEventDTO as SessionUpdatedEvent,
)
from teleclaude.api_models import (
    SettingsDTO as SettingsInfo,
)
from teleclaude.api_models import (
    SettingsPatchDTO as SettingsPatchInfo,
)
from teleclaude.api_models import (
    TodoDTO as TodoInfo,
)
from teleclaude.api_models import (
    TTSSettingsPatchDTO as TTSSettingsPatchInfo,
)

__all__ = [
    "AgentActivityEvent",
    "AgentAvailabilityInfo",
    "ChiptunesCommandReceiptInfo",
    "ChiptunesStateEvent",
    "ChiptunesStatusInfo",
    "ChiptunesTrackEvent",
    "ComputerInfo",
    "CreateSessionResult",
    "ErrorEvent",
    "JobInfo",
    "JsonObject",
    "JsonValue",
    "ProjectInfo",
    "ProjectWithTodosInfo",
    "ProjectsInitialData",
    "ProjectsInitialEvent",
    "RefreshData",
    "RefreshEvent",
    "SessionClosedData",
    "SessionClosedEvent",
    "SessionInfo",
    "SessionLifecycleStatusEvent",
    "SessionStartedEvent",
    "SessionUpdatedEvent",
    "SessionsInitialData",
    "SessionsInitialEvent",
    "SettingsInfo",
    "SettingsPatchInfo",
    "SubscribeData",
    "SubscribeRequest",
    "TTSSettingsPatchInfo",
    "TodoInfo",
    "UnsubscribeData",
    "UnsubscribeRequest",
    "WsEvent",
]

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


WsEvent: TypeAlias = SessionsInitialEvent | ProjectsInitialEvent | SessionStartedEvent | SessionUpdatedEvent | SessionClosedEvent | SessionLifecycleStatusEvent | RefreshEvent | ErrorEvent | AgentActivityEvent | ChiptunesStateEvent | ChiptunesTrackEvent


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
