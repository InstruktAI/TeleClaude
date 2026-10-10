"""WebSocket constants and shared state types for APIServer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from teleclaude.api.ws_options import WsStream
from teleclaude.config.machine import config
from teleclaude.core.models import JsonDict

API_WS_PING_INTERVAL_S = 20.0
API_WS_PING_TIMEOUT_S = 20.0
API_WS_CONTROL_SEND_TIMEOUT_S = config.api.ws_control_send_timeout_s
API_WS_DEFAULT_SEND_TIMEOUT_S = config.api.ws_default_send_timeout_s
API_WS_REPLACEABLE_SEND_TIMEOUT_S = config.api.ws_replaceable_send_timeout_s

API_WS_CONTROL_EVENTS = frozenset(
    {
        "agent_activity",
        "agent_availability",
        "error",
        "projects_initial",
        "preparation_initial",
        "session_closed",
        "session_started",
        "session_status",
        "session_updated",
        "sessions_initial",
    }
)
API_WS_REPLACEABLE_EVENTS = frozenset({"chiptunes_state", "chiptunes_track", "refresh"})

__all__ = [
    "API_WS_CONTROL_EVENTS",
    "API_WS_CONTROL_SEND_TIMEOUT_S",
    "API_WS_DEFAULT_SEND_TIMEOUT_S",
    "API_WS_PING_INTERVAL_S",
    "API_WS_PING_TIMEOUT_S",
    "API_WS_REPLACEABLE_EVENTS",
    "API_WS_REPLACEABLE_SEND_TIMEOUT_S",
    "_WsClientState",
]


@dataclass  # pyright: ignore[reportUnusedClass]
class _WsClientState:
    """Per-client sender state and projection options for one WebSocket connection.

    ``streams`` holds the streams whose initial state has been queued; a stream
    receives subsequent changes only once it is in the set. ``legacy`` marks a
    connection that opened without options and selects its streams with
    subscription frames.
    """

    queue: asyncio.Queue[tuple[str, JsonDict]] = field(default_factory=asyncio.Queue)
    sender_task: asyncio.Task[object] | None = None
    streams: set[WsStream] = field(default_factory=set)
    include_removed: bool = False
    legacy: bool = False
