"""Shared launch-intent helpers for session creation endpoints."""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.api_models import CreateSessionRequest
from teleclaude.core.agents import assert_agent_enabled, get_default_agent
from teleclaude.core.models import SessionLaunchKind


def resolve_enabled_agent(requested_agent: str | None) -> str:
    """Return a configured agent name or surface the API validation failure."""
    if requested_agent:
        try:
            return assert_agent_enabled(requested_agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return get_default_agent()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def resolve_launch_kind(request: CreateSessionRequest) -> SessionLaunchKind:
    """Normalize implicit message launch without inferring resume from native IDs."""
    launch_kind = SessionLaunchKind(request.launch_kind)
    if launch_kind == SessionLaunchKind.AGENT and request.message:
        return SessionLaunchKind.AGENT_THEN_MESSAGE
    return launch_kind


def effective_launch_agent(validated_request_agent: str | None) -> str:
    """Resolve the agent used for derived launch intents."""
    return validated_request_agent or resolve_enabled_agent(None)
