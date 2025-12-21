"""Claude hook adapter."""

from __future__ import annotations

from typing import Callable

from teleclaude.core.events import AgentHookEvents


def _passthrough(data: dict[str, object]) -> dict[str, object]:
    return dict(data)


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    handlers: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {
        AgentHookEvents.AGENT_SESSION_START: _passthrough,
        AgentHookEvents.AGENT_STOP: _passthrough,
        AgentHookEvents.AGENT_NOTIFICATION: _passthrough,
        AgentHookEvents.AGENT_SESSION_END: _passthrough,
        AgentHookEvents.AGENT_ERROR: _passthrough,
    }
    return handlers[event_type](data)
