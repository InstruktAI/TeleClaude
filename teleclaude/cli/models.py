"""Typed models for TeleClaude CLI and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


@dataclass(frozen=True)
class AgentAvailabilityInfo:
    agent: Literal["claude", "gemini", "codex"]
    available: bool | None
    unavailable_until: str | None
    reason: str | None
    error: str | None = None


@dataclass(frozen=True)
class ComputerInfo:
    name: str
    status: str
    user: str | None
    host: str | None
    is_local: bool
    tmux_binary: str | None = None


@dataclass(frozen=True)
class ProjectInfo:
    computer: str
    name: str
    path: str
    description: str | None


@dataclass(frozen=True)
class TodoInfo:
    slug: str
    status: str
    description: str | None
    has_requirements: bool
    has_impl_plan: bool
    build_status: str | None = None
    review_status: str | None = None


@dataclass(frozen=True)
class ProjectWithTodosInfo:
    computer: str
    name: str
    path: str
    description: str | None
    todos: list[TodoInfo]


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    thinking_mode: str
    active_agent: str | None
    status: str
    created_at: str | None
    last_activity: str | None
    last_input: str | None
    last_output: str | None
    tmux_session_name: str | None
    initiator_session_id: str | None
    computer: str | None = None


@dataclass(frozen=True)
class CreateSessionResult:
    status: str
    session_id: str | None
    tmux_session_name: str | None


@dataclass(frozen=True)
class SessionsInitialData:
    sessions: list[SessionInfo]
    computer: str | None = None


@dataclass(frozen=True)
class ProjectsInitialData:
    projects: list[ProjectInfo | ProjectWithTodosInfo]
    computer: str | None = None


@dataclass(frozen=True)
class SessionRemovedData:
    session_id: str


@dataclass(frozen=True)
class RefreshData:
    computer: str | None = None


@dataclass(frozen=True)
class SessionsInitialEvent:
    event: Literal["sessions_initial"]
    data: SessionsInitialData


@dataclass(frozen=True)
class ProjectsInitialEvent:
    event: Literal["projects_initial", "preparation_initial"]
    data: ProjectsInitialData


@dataclass(frozen=True)
class SessionUpdateEvent:
    event: Literal["session_updated", "session_created"]
    data: SessionInfo


@dataclass(frozen=True)
class SessionRemovedEvent:
    event: Literal["session_removed"]
    data: SessionRemovedData


@dataclass(frozen=True)
class RefreshEvent:
    event: Literal["computer_updated", "project_updated", "projects_updated"]
    data: RefreshData


WsEvent = SessionsInitialEvent | ProjectsInitialEvent | SessionUpdateEvent | SessionRemovedEvent | RefreshEvent


@dataclass(frozen=True)
class SubscribeData:
    computer: str
    types: list[str]


@dataclass(frozen=True)
class UnsubscribeData:
    computer: str


@dataclass(frozen=True)
class SubscribeRequest:
    subscribe: SubscribeData


@dataclass(frozen=True)
class UnsubscribeRequest:
    unsubscribe: UnsubscribeData
