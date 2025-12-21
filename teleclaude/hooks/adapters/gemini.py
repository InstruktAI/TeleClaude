"""Gemini hook adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, cast

from teleclaude.core.events import AgentHookEvents


def _passthrough(data: dict[str, object]) -> dict[str, object]:
    return dict(data)


def _resolve_transcript_path(session_id: str, transcript_path: str) -> str:
    if transcript_path:
        return transcript_path

    session_prefix = session_id.split("-", 1)[0]
    search_root = Path.home() / ".gemini" / "tmp"
    pattern = f"**/chats/session-*-{session_prefix}.json"
    matches = list(search_root.rglob(pattern))
    if not matches:
        raise ValueError(f"Gemini transcript not found for session {session_id}")
    latest = max(matches, key=lambda path: path.stat().st_mtime)
    return str(latest)


def _with_transcript(data: dict[str, object]) -> dict[str, object]:
    session_id = cast(str, data["session_id"])
    transcript_path = cast(str, data.get("transcript_path", ""))
    normalized = dict(data)
    normalized["transcript_path"] = _resolve_transcript_path(session_id, transcript_path)
    return normalized


def normalize_payload(event_type: str, data: dict[str, object]) -> dict[str, object]:
    handlers: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {
        AgentHookEvents.AGENT_SESSION_START: _with_transcript,
        AgentHookEvents.AGENT_STOP: _with_transcript,
        AgentHookEvents.AGENT_NOTIFICATION: _passthrough,
        AgentHookEvents.AGENT_SESSION_END: _passthrough,
        AgentHookEvents.AGENT_ERROR: _passthrough,
    }
    return handlers[event_type](data)
