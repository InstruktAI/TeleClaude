"""WebSocket constants and shared state types for APIServer."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

API_WS_PING_INTERVAL_S = 20.0
API_WS_PING_TIMEOUT_S = 20.0
API_WS_CONTROL_SEND_TIMEOUT_S = float(os.getenv("API_WS_CONTROL_SEND_TIMEOUT_S", "30"))
API_WS_DEFAULT_SEND_TIMEOUT_S = float(os.getenv("API_WS_DEFAULT_SEND_TIMEOUT_S", "15"))
API_WS_REPLACEABLE_SEND_TIMEOUT_S = float(os.getenv("API_WS_REPLACEABLE_SEND_TIMEOUT_S", "5"))

API_WS_CONTROL_EVENTS = frozenset(
    {
        "agent_activity",
        "error",
        "notification",
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


@dataclass
class _WsClientState:
    """Per-client sender state for serialized WebSocket writes."""

    queue: asyncio.Queue[tuple[str, dict[str, object]]] = field(default_factory=asyncio.Queue)
    sender_task: asyncio.Task[object] | None = None
