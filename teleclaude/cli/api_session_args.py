"""Typed argument shapes for CLI API session creation and dispatch."""

from __future__ import annotations

from enum import StrEnum
from typing import NotRequired, Required, TypedDict

from teleclaude.core.command_input import CommandInputMode


class RunSessionField(StrEnum):
    """Run-session fields the client reads or writes by name outside the argument shape."""

    MANUALLY_STARTED = "manually_started"


class CreateSessionArgs(TypedDict, total=False):
    """Accepted keyword arguments for session creation."""

    computer: Required[str]
    project_path: Required[str]
    agent: NotRequired[str | None]
    thinking_mode: NotRequired[str]
    launch_kind: NotRequired[str]
    native_session_id: NotRequired[str | None]
    subdir: NotRequired[str | None]
    title: NotRequired[str | None]
    message: NotRequired[str | None]
    skip_listener_registration: NotRequired[bool]
    metadata: NotRequired[dict[str, object] | None]  # guard: loose-dict - dynamic payload
    command_input_mode: NotRequired[CommandInputMode]
    command_input_source_text: NotRequired[str | None]
    company: NotRequired[str | None]
    job: NotRequired[str | None]


class RunSessionArgs(TypedDict, total=False):
    """Accepted keyword arguments for slash-command sessions."""

    command: Required[str]
    project_path: Required[str]
    computer: NotRequired[str]
    args: NotRequired[str]
    agent: NotRequired[str]
    thinking_mode: NotRequired[str]
    detach: NotRequired[bool]
    additional_context: NotRequired[str]
    entry_point: NotRequired[str]
    company: NotRequired[str | None]
    job: NotRequired[str | None]
    manually_started: NotRequired[bool]
