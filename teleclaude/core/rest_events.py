"""REST-origin outbox payload contracts."""

from __future__ import annotations

from typing import Mapping, TypedDict


class RestOutboxPayload(TypedDict, total=False):
    session_id: str
    args: list[str]
    text: str
    message_id: str


class RestOutboxMetadata(TypedDict, total=False):
    adapter_type: str
    project_path: str
    subdir: str
    channel_metadata: Mapping[str, object]
    launch_intent: Mapping[str, object]
    message_thread_id: int
    title: str
    channel_id: str
    raw_format: bool
    parse_mode: str


class RestOutboxResponse(TypedDict, total=False):
    status: str
    data: object
    error: str
    code: str
