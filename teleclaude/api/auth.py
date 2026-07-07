"""Daemon-side role enforcement for telec API endpoints.
Provides FastAPI dependencies for dual-factor caller identity verification
and role-based clearance checks. Replaces legacy wrapper-side
tool filtering with tamper-resistant server-side enforcement.

Identity verification flow:
1. X-Caller-Session-Id present → verify against DB (and tmux cross-check when present)
2. Otherwise, X-Telec-Email (TTY-scoped telec login) maps to human role via global config
3. Otherwise, fall back to default unidentified terminal role
4. Insufficient clearance → 403

The system_role is derived from daemon-owned session state in the database.
The human_role comes from DB session record or terminal email mapping.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

from teleclaude.cli.telec import is_command_allowed
from teleclaude.constants import (
    HUMAN_ROLE_ADMIN,
    ROLE_INTEGRATOR,
    ROLE_ORCHESTRATOR,
    ROLE_SYSTEM,
    ROLE_WORKER,
)
from teleclaude.core import db_models
from teleclaude.core.db import SessionIdentityError, db, resolve_session_principal
from teleclaude.core.identity import get_identity_resolver

if TYPE_CHECKING:
    from teleclaude.core.models import Session


# In-memory session cache for verify_caller (avoids DB hit per authenticated request)
_SESSION_CACHE_TTL = 30.0  # seconds
_SESSION_CACHE_MAX = 256
_session_cache: dict[str, tuple[float, Session]] = {}

# In-memory token cache to avoid repeated ledger lookups on hot paths
_TOKEN_CACHE_TTL = 30.0  # seconds — matches session cache TTL
_TOKEN_CACHE_MAX = 256
_token_cache: dict[str, tuple[float, db_models.SessionToken]] = {}


def _get_cached_session(session_id: str) -> Session | None:
    """Get session from cache if present and not expired."""
    entry = _session_cache.get(session_id)
    if entry is None:
        return None
    ts, session = entry
    if time.monotonic() - ts > _SESSION_CACHE_TTL:
        _session_cache.pop(session_id, None)
        return None
    return session


def get_cached_session(session_id: str) -> Session | None:
    """Return a cached session when present."""
    return _get_cached_session(session_id)


def _put_cached_session(session_id: str, session: Session) -> None:
    """Store session in cache with eviction when full."""
    if len(_session_cache) >= _SESSION_CACHE_MAX:
        # Evict oldest entry
        oldest_key = min(_session_cache, key=lambda k: _session_cache[k][0])
        _session_cache.pop(oldest_key, None)
    _session_cache[session_id] = (time.monotonic(), session)


def invalidate_session_cache(session_id: str) -> None:
    """Invalidate a specific session from the auth cache (call on session update/close)."""
    _session_cache.pop(session_id, None)


def _get_cached_token(token: str) -> db_models.SessionToken | None:
    """Get token record from cache if present and not expired."""
    entry = _token_cache.get(token)
    if entry is None:
        return None
    ts, record = entry
    if time.monotonic() - ts > _TOKEN_CACHE_TTL:
        _token_cache.pop(token, None)
        return None
    return record


def _put_cached_token(token: str, record: db_models.SessionToken) -> None:
    """Store token record in cache with eviction when full."""
    if len(_token_cache) >= _TOKEN_CACHE_MAX:
        oldest_key = min(_token_cache, key=lambda k: _token_cache[k][0])
        _token_cache.pop(oldest_key, None)
    _token_cache[token] = (time.monotonic(), record)


def invalidate_token_cache(session_id: str) -> None:
    """Invalidate all cached tokens for a session (call on session close)."""
    stale = [t for t, (_, rec) in _token_cache.items() if getattr(rec, "session_id", None) == session_id]
    for t in stale:
        _token_cache.pop(t, None)


def _normalize_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _resolve_terminal_role(email_header: str | None) -> str | None:
    """Resolve human role from email via the shared IdentityResolver."""
    email = _normalize_email(email_header)
    if not email:
        return None
    return get_identity_resolver().resolve_by_email(email).person_role


def _requires_terminal_login() -> bool:
    """Return True when global config has multiple registered users."""
    return get_identity_resolver().is_multi_user


def _derive_session_system_role(session: Session) -> str | None:
    """Derive system role from daemon-owned session state.

    Priority:
    1. Explicit `session.system_role` if present and valid.
    2. Worker heuristic: sessions with a `working_slug` are worker sessions.
    3. Otherwise unknown (treated as non-worker for system-role restrictions).
    """
    if session.system_role:
        normalized = session.system_role.strip().lower()
        if normalized in {ROLE_WORKER, ROLE_SYSTEM, ROLE_INTEGRATOR, ROLE_ORCHESTRATOR}:
            return normalized

    if session.working_slug:
        return ROLE_WORKER
    return None


@dataclass(frozen=True)
class CallerIdentity:
    """Verified caller identity for role clearance checks."""

    session_id: str
    system_role: str | None  # e.g. "worker" or None (orchestrator/admin)
    human_role: str | None  # e.g. "admin", "member", etc.
    tmux_session_name: str | None  # for diagnostic use only
    email: str | None = None  # authenticated email from terminal login or web header
    principal: str | None = None  # "human:<email>" or "system:<id>" (token-auth only)
    principal_role: str | None = None  # role carried with the token (token-auth only)


async def _get_verified_session(session_id: str) -> Session:
    """Load a verified session from cache or DB."""
    session = _get_cached_session(session_id)
    if session is None:
        session = await db.get_session(session_id)
        if not session:
            raise HTTPException(status_code=401, detail="unknown session")
        _put_cached_session(session_id, session)
    return session


async def _verify_token_identity(x_session_token: str) -> CallerIdentity:
    """Resolve caller identity from a session token."""
    token_record = _get_cached_token(x_session_token)
    if token_record is None:
        token_record = await db.validate_session_token(x_session_token)
        if token_record is not None:
            _put_cached_token(x_session_token, token_record)
    if not token_record:
        raise HTTPException(status_code=401, detail="invalid or expired session token")

    session = await _get_verified_session(token_record.session_id)
    # Defense-in-depth: a revoke_session_tokens hiccup during close must not let
    # tokens outlive their session. Reject any token whose owner is closed/closing
    # regardless of ledger state (which is the primary revocation barrier).
    if session.closed_at is not None or session.lifecycle_status in ("closed", "closing"):
        raise HTTPException(status_code=401, detail="session no longer active")
    return CallerIdentity(
        session_id=token_record.session_id,
        system_role=_derive_session_system_role(session),
        human_role=session.human_role,
        tmux_session_name=session.tmux_session_name,
        principal=token_record.principal,
        principal_role=token_record.role,
    )


def _build_terminal_identity(
    *,
    email_header: str | None,
    tmux_session_name: str | None,
) -> CallerIdentity:
    """Resolve caller identity for non-session callers."""
    normalized_email = _normalize_email(email_header)
    terminal_role = _resolve_terminal_role(email_header)
    if terminal_role:
        return CallerIdentity(
            session_id="",
            system_role=None,
            human_role=terminal_role,
            tmux_session_name=tmux_session_name,
            email=normalized_email,
        )
    if _requires_terminal_login():
        raise HTTPException(status_code=401, detail="login required in multi-user mode")
    return CallerIdentity(
        session_id="",
        system_role=None,
        human_role=HUMAN_ROLE_ADMIN,
        tmux_session_name=tmux_session_name,
        email=normalized_email,
    )


def _resolve_human_role(session: Session, x_telec_email: str | None) -> str | None:
    """Resolve human role with terminal-email fallback."""
    if session.human_role:
        return session.human_role
    fallback_email = x_telec_email or getattr(session, "human_email", None)
    if not fallback_email:
        return None
    return _resolve_terminal_role(fallback_email)


async def _verify_session_identity(
    *,
    caller_session_id: str,
    x_telec_email: str | None,
    x_tmux_session: str | None,
) -> CallerIdentity:
    """Resolve caller identity for an existing TeleClaude session."""
    session = await _get_verified_session(caller_session_id)
    if x_tmux_session and session.tmux_session_name and x_tmux_session != session.tmux_session_name:
        raise HTTPException(status_code=403, detail="session identity mismatch")

    resolved_email = _normalize_email(x_telec_email) or getattr(session, "human_email", None)
    # Carry the resolved principal so a human-rooted session surfaces human:<email>
    # and a system session surfaces system:<id>. A session that carries only a
    # human_role (no principal, no human_email, no system_role) has no resolvable
    # principal and keeps principal=None, still authorizing on its human_role.
    try:
        principal, principal_role = resolve_session_principal(session)
    except SessionIdentityError:
        principal, principal_role = None, None
    return CallerIdentity(
        session_id=caller_session_id,
        system_role=_derive_session_system_role(session),
        human_role=_resolve_human_role(session, x_telec_email),
        tmux_session_name=session.tmux_session_name,
        email=resolved_email,
        principal=principal,
        principal_role=principal_role,
    )


async def verify_caller(
    x_session_token: Annotated[str | None, Header()] = None,
    x_caller_session_id: Annotated[str | None, Header()] = None,
    x_telec_email: Annotated[str | None, Header()] = None,
    x_web_user_email: Annotated[str | None, Header()] = None,
    x_tmux_session: Annotated[str | None, Header()] = None,
) -> CallerIdentity:
    """FastAPI dependency: verify caller identity via dual-factor check.

    Factor 1: session_id from $TMPDIR/teleclaude_identity.json (file, writable by agent)
    Factor 2: tmux session name from tmux server (unforgeable from within session)

    Both must agree with the daemon's DB records when present.

    Returns:
        CallerIdentity with session_id, system_role, and human_role.

    Raises:
        HTTPException(401): Missing or unknown session_id.
        HTTPException(403): Tmux cross-check mismatch (session_id forgery attempt).
    """
    # Token path: agent sessions present the session token via X-Session-Token header.
    # This takes priority over the legacy dual-factor path so daemon-spawned agents
    # can authenticate even when human_role is absent.
    if x_session_token:
        return await _verify_token_identity(x_session_token)

    if not x_caller_session_id:
        return _build_terminal_identity(
            email_header=x_telec_email or x_web_user_email,
            tmux_session_name=x_tmux_session,
        )

    return await _verify_session_identity(
        caller_session_id=x_caller_session_id,
        x_telec_email=x_telec_email,
        x_tmux_session=x_tmux_session,
    )


async def optional_caller_identity(
    x_session_token: Annotated[str | None, Header()] = None,
    x_caller_session_id: Annotated[str | None, Header()] = None,
    x_telec_email: Annotated[str | None, Header()] = None,
    x_web_user_email: Annotated[str | None, Header()] = None,
    x_tmux_session: Annotated[str | None, Header()] = None,
) -> CallerIdentity | None:
    """Resolve caller identity for an OPEN route without ever gating it.

    For routes that accept anonymous callers today (e.g. ``POST /todos/dump``),
    identity is captured as pure attribution. Any identity-resolution failure
    ``verify_caller`` would raise — the unknown-credential 401s, the multi-user
    ``"login required"`` 401, and the dual-factor tmux-mismatch 403 — is swallowed
    to ``None`` so a caller that creates successfully today still succeeds. The
    route stores ``None`` when no identity resolves; it never rejects.
    """
    try:
        return await verify_caller(
            x_session_token=x_session_token,
            x_caller_session_id=x_caller_session_id,
            x_telec_email=x_telec_email,
            x_web_user_email=x_web_user_email,
            x_tmux_session=x_tmux_session,
        )
    except HTTPException:
        return None


def _is_tool_denied(tool_name: str, identity: CallerIdentity) -> bool:
    """Check if a tool (mapped from endpoint) is denied for this identity."""
    human_role = identity.human_role
    if human_role is None and identity.principal is not None:
        human_role = identity.principal_role
    return not is_command_allowed(tool_name, identity.system_role, human_role)


def require_clearance(tool_name: str):  # type: ignore[no-untyped-def]
    """FastAPI dependency factory: check role clearance for a specific tool.

    Maps CLI endpoint names to command-surface names and checks role clearance.

    Args:
        tool_name: Command name (e.g. "telec sessions start")

    Returns:
        A FastAPI dependency function that returns CallerIdentity on success or
        raises HTTPException(403) on clearance failure.
    """

    async def _check(identity: CallerIdentity = Depends(verify_caller)) -> CallerIdentity:
        if _is_tool_denied(tool_name, identity):
            role_desc = identity.system_role or identity.human_role or "unauthorized"
            raise HTTPException(
                status_code=403,
                detail=f"role '{role_desc}' is not permitted to call {tool_name}",
            )
        return identity

    return _check


async def _is_self_agent_restart_request(request: Request, session_id: str, identity: CallerIdentity) -> bool:
    """Return True when the restart request is scoped to the caller's own session."""
    if not identity.session_id or identity.session_id != session_id:
        return False
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
        return False
    try:
        payload: object = await request.json()
    except ValueError:
        return False
    return isinstance(payload, Mapping) and payload.get("self_restart") is True


async def clearance_sessions_agent_restart(
    request: Request,
    session_id: str,
    identity: CallerIdentity = Depends(verify_caller),
) -> CallerIdentity:
    """Authorize session restarts, allowing any caller to restart only itself."""
    if await _is_self_agent_restart_request(request, session_id, identity):
        return identity
    tool_name = "telec sessions restart"
    if identity.system_role == ROLE_WORKER or _is_tool_denied(tool_name, identity):
        role_desc = identity.system_role or identity.human_role or "unauthorized"
        raise HTTPException(
            status_code=403,
            detail=f"role '{role_desc}' is not permitted to call {tool_name}",
        )
    return identity


async def clearance_sessions_end(
    session_id: str,
    identity: CallerIdentity = Depends(verify_caller),
) -> CallerIdentity:
    """Authorize session ends, allowing a parentless session to end itself.

    A caller may end its OWN session past the standard verb band when the target
    has no orchestrating parent (``initiator_session_id is None``) — the
    runner-dispatched driver case. ``initiator_session_id`` is daemon-set session
    state, never caller-supplied, so a sub-worker cannot forge a parentless row.
    Every other shape (cross-session end, sub-worker self-end) falls through to
    the standard rule.
    """
    if identity.session_id and identity.session_id == session_id:
        session = await _get_verified_session(session_id)
        if session.initiator_session_id is None:
            return identity
    tool_name = "telec sessions end"
    if _is_tool_denied(tool_name, identity):
        role_desc = identity.system_role or identity.human_role or "unauthorized"
        raise HTTPException(
            status_code=403,
            detail=f"role '{role_desc}' is not permitted to call {tool_name}",
        )
    return identity


clearance_sessions_start = require_clearance("telec sessions start")
clearance_sessions_list = require_clearance("telec sessions list")
clearance_sessions_run = require_clearance("telec sessions run")
clearance_sessions_send = require_clearance("telec sessions send")
clearance_sessions_keys = require_clearance("telec sessions send")
clearance_sessions_voice = require_clearance("telec sessions send")
clearance_sessions_revive = require_clearance("telec sessions run")
clearance_sessions_tail = require_clearance("telec sessions tail")
clearance_sessions_unsubscribe = require_clearance("telec sessions unsubscribe")
clearance_sessions_result = require_clearance("telec sessions result")
clearance_sessions_file = require_clearance("telec sessions file")
clearance_sessions_widget = require_clearance("telec sessions widget")
clearance_sessions_escalate = require_clearance("telec sessions escalate")
clearance_todos_create = require_clearance("telec todo design")
clearance_todos_prepare = require_clearance("telec todo prepare")
clearance_todos_work = require_clearance("telec todo work")
clearance_todos_integrate = require_clearance("telec todo integrate")
clearance_todos_remove = require_clearance("telec todo remove")
clearance_todos_reactivate = require_clearance("telec todo reactivate")
clearance_todos_update = require_clearance("telec todo update")
clearance_todos_stamp = require_clearance("telec todo stamp")
clearance_todos_artifacts_diff = require_clearance("telec todo artifacts diff")
clearance_todos_artifacts_remove = require_clearance("telec todo artifacts remove")
clearance_todos_artifacts_write = require_clearance("telec todo artifacts write")
clearance_operations_get = require_clearance("telec operations get")
clearance_agents_status = require_clearance("telec agents status")
clearance_agents_availability = require_clearance("telec agents availability")
clearance_computers_list = require_clearance("telec computers list")
clearance_projects_list = require_clearance("telec projects list")
clearance_channels_list = require_clearance("telec channels list")
clearance_channels_publish = require_clearance("telec channels publish")
clearance_events_emit = require_clearance("telec events emit")
clearance_message_send = require_clearance("telec message")

__all__ = [
    "CallerIdentity",
    "clearance_agents_availability",
    "clearance_agents_status",
    "clearance_channels_list",
    "clearance_channels_publish",
    "clearance_computers_list",
    "clearance_events_emit",
    "clearance_message_send",
    "clearance_operations_get",
    "clearance_projects_list",
    "clearance_sessions_agent_restart",
    "clearance_sessions_end",
    "clearance_sessions_escalate",
    "clearance_sessions_file",
    "clearance_sessions_keys",
    "clearance_sessions_list",
    "clearance_sessions_result",
    "clearance_sessions_revive",
    "clearance_sessions_run",
    "clearance_sessions_send",
    "clearance_sessions_start",
    "clearance_sessions_tail",
    "clearance_sessions_unsubscribe",
    "clearance_sessions_voice",
    "clearance_sessions_widget",
    "clearance_todos_artifacts_diff",
    "clearance_todos_artifacts_remove",
    "clearance_todos_artifacts_write",
    "clearance_todos_create",
    "clearance_todos_integrate",
    "clearance_todos_prepare",
    "clearance_todos_reactivate",
    "clearance_todos_remove",
    "clearance_todos_stamp",
    "clearance_todos_update",
    "clearance_todos_work",
    "invalidate_session_cache",
    "invalidate_token_cache",
    "optional_caller_identity",
    "require_clearance",
    "verify_caller",
]
