"""Shared launch-intent helpers for session creation endpoints."""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.api.auth import CallerIdentity
from teleclaude.api.session_direct_messages import _resolve_direct_caller_session
from teleclaude.api_models import CreateSessionRequest
from teleclaude.core.agent_dispatch import classify_fresh_agent_preference
from teleclaude.core.agents import normalize_agent_name
from teleclaude.core.models import (
    AgentDispatchMode,
    Session,
    SessionLaunchIntent,
    SessionLaunchKind,
)


def resolve_enabled_agent(requested_agent: str | None) -> str:
    """Validate agent identity without applying origin-machine policy."""
    if requested_agent:
        try:
            return normalize_agent_name(requested_agent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail="agent required for a fixed launch")


def resolve_launch_kind(request: CreateSessionRequest) -> SessionLaunchKind:
    """Normalize implicit message launch without inferring resume from native IDs."""
    launch_kind = SessionLaunchKind(request.launch_kind)
    if launch_kind == SessionLaunchKind.AGENT and request.message:
        return SessionLaunchKind.AGENT_THEN_MESSAGE
    return launch_kind


async def build_launch_intent(
    request: CreateSessionRequest,
    identity: CallerIdentity,
    validated_request_agent: str | None,
    thinking_mode: str,
) -> tuple[SessionLaunchIntent | None, Session | None]:
    """Build the typed launch intent for a new session."""
    launch_kind = resolve_launch_kind(request)

    if launch_kind == SessionLaunchKind.EMPTY:
        return SessionLaunchIntent(kind=SessionLaunchKind.EMPTY), None

    if launch_kind == SessionLaunchKind.AGENT_RESUME:
        if not request.agent:
            raise HTTPException(status_code=400, detail="agent required for agent_resume")
        effective_agent = validated_request_agent or resolve_enabled_agent(request.agent)
        return (
            SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_RESUME,
                agent=effective_agent,
                thinking_mode=thinking_mode,
                native_session_id=request.native_session_id,
                dispatch_mode=AgentDispatchMode.FIXED,
            ),
            None,
        )

    dispatch_mode, preferred_agent = classify_fresh_agent_preference(
        validated_request_agent,
        caller_system_role=identity.system_role,
    )

    if launch_kind == SessionLaunchKind.AGENT_THEN_MESSAGE:
        if request.message is None:
            raise HTTPException(status_code=400, detail="message required for agent_then_message")
        caller_session: Session | None = None
        if request.direct and identity.session_id:
            caller_session = await _resolve_direct_caller_session(identity.session_id)
            return (
                SessionLaunchIntent(
                    kind=SessionLaunchKind.AGENT,
                    agent=validated_request_agent,
                    thinking_mode=thinking_mode,
                    dispatch_mode=dispatch_mode,
                    preferred_agent=preferred_agent,
                ),
                caller_session,
            )
        return (
            SessionLaunchIntent(
                kind=SessionLaunchKind.AGENT_THEN_MESSAGE,
                agent=validated_request_agent,
                thinking_mode=thinking_mode,
                message=request.message,
                dispatch_mode=dispatch_mode,
                preferred_agent=preferred_agent,
            ),
            caller_session,
        )

    return (
        SessionLaunchIntent(
            kind=SessionLaunchKind.AGENT,
            agent=validated_request_agent,
            thinking_mode=thinking_mode,
            dispatch_mode=dispatch_mode,
            preferred_agent=preferred_agent,
        ),
        None,
    )
