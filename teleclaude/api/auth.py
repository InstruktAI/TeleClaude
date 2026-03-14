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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

from teleclaude.cli.telec import is_command_allowed
from teleclaude.config.loader import load_global_config
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLES, ROLE_INTEGRATOR, ROLE_ORCHESTRATOR, ROLE_WORKER
from teleclaude.core import db_models
from teleclaude.core.db import db

if TYPE_CHECKING:
    from teleclaude.core.models import Session


_GLOBAL_CONFIG_PATH = Path("~/.teleclaude/teleclaude.yml").expanduser()
_email_role_cache: dict[str, str] = {}
_email_role_cache_mtime_ns: int | None = None
_registered_people_count_cache: int = 0

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


def _load_email_role_map() -> dict[str, str]:
    """Load email->role map from global config with mtime-based cache."""
    global _email_role_cache, _email_role_cache_mtime_ns, _registered_people_count_cache

    try:
        mtime_ns = _GLOBAL_CONFIG_PATH.stat().st_mtime_ns
    except OSError:
        _email_role_cache = {}
        _email_role_cache_mtime_ns = None
        _registered_people_count_cache = 0
        return _email_role_cache

    if _email_role_cache_mtime_ns == mtime_ns:
        return _email_role_cache

    role_map: dict[str, str] = {}
    try:
        global_cfg = load_global_config(_GLOBAL_CONFIG_PATH)
    except Exception:
        return _email_role_cache

    _registered_people_count_cache = 0
    for person in global_cfg.people:
        _registered_people_count_cache += 1
        email = _normalize_email(person.email)
        role = (person.role or "").strip().lower()
        if not email or role not in HUMAN_ROLES:
            continue
        role_map[email] = role

    _email_role_cache = role_map
    _email_role_cache_mtime_ns = mtime_ns
    return _email_role_cache


def _resolve_terminal_role(email_header: str | None) -> str | None:
    email = _normalize_email(email_header)
    if not email:
        return None
    return _load_email_role_map().get(email)


def _requires_terminal_login() -> bool:
    """Return True when global config has multiple registered users."""
    _load_email_role_map()
    return _registered_people_count_cache > 1


def _derive_session_system_role(session: Session) -> str | None:
    """Derive system role from daemon-owned session state.

    Priority:
    1. Explicit `session_metadata.system_role` if present and valid.
    2. Worker heuristic: sessions with a `working_slug` are worker sessions.
    3. Otherwise unknown (treated as non-worker for system-role restrictions).
    """
    if session.session_metadata and session.session_metadata.system_role:
        normalized = session.session_metadata.system_role.strip().lower()
        if normalized in {ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR}:
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
    principal: str | None = None        # "human:<email>" or "system:<id>" (token-auth only)
    principal_role: str | None = None   # role carried with the token (token-auth only)


async def verify_caller(
    request: Request,
    x_session_token: Annotated[str | None, Header()] = None,
    x_caller_session_id: Annotated[str | None, Header()] = None,
    x_telec_email: Annotated[str | None, Header()] = None,
    x_web_user_email: Annotated[str | None, Header()] = None,
    x_tmux_session: Annotated[str | None, Header()] = None,
) -> CallerIdentity:
    """FastAPI dependency: verify caller identity via dual-factor check.

    Factor 1: session_id from $TMPDIR/teleclaude_session_id (file, writable by agent)
    Factor 2: tmux session name from tmux server (unforgeable from within session)

    Both must agree with the daemon's DB records when present.

    Returns:
        CallerIdentity with session_id, system_role, and human_role.

    Raises:
        HTTPException(401): Missing or unknown session_id.
        HTTPException(403): Tmux cross-check mismatch (session_id forgery attempt).
    """
    # Token path: agent sessions present TELEC_SESSION_TOKEN via X-Session-Token header.
    # This takes priority over the legacy dual-factor path so daemon-spawned agents
    # can authenticate even when human_role is absent.
    if x_session_token:
        token_record = _get_cached_token(x_session_token)
        if token_record is None:
            token_record = await db.validate_session_token(x_session_token)
            if token_record is not None:
                _put_cached_token(x_session_token, token_record)
        if not token_record:
            raise HTTPException(status_code=401, detail="invalid or expired session token")
        session = _get_cached_session(token_record.session_id)
        if session is None:
            session = await db.get_session(token_record.session_id)
            if not session:
                raise HTTPException(status_code=401, detail="unknown session")
            _put_cached_session(token_record.session_id, session)
        system_role = _derive_session_system_role(session)
        return CallerIdentity(
            session_id=token_record.session_id,
            system_role=system_role,
            human_role=session.human_role,
            tmux_session_name=session.tmux_session_name,
            principal=token_record.principal,
            principal_role=token_record.role,
        )

    if not x_caller_session_id:
        # Terminal/TUI/web caller without a daemon session.
        # 1. Try email → role resolution (works for any caller context).
        # 2. Single-owner mode (0-1 registered people) → implicit admin.
        # 3. Multi-user mode → login required.
        email_to_use = x_telec_email or x_web_user_email
        terminal_role = _resolve_terminal_role(email_to_use)
        if terminal_role:
            return CallerIdentity(
                session_id="",
                system_role=None,
                human_role=terminal_role,
                tmux_session_name=x_tmux_session,
            )
        if _requires_terminal_login():
            raise HTTPException(status_code=401, detail="login required in multi-user mode")
        return CallerIdentity(
            session_id="",
            system_role=None,
            human_role=HUMAN_ROLE_ADMIN,
            tmux_session_name=x_tmux_session,
        )

    session = _get_cached_session(x_caller_session_id)
    if session is None:
        session = await db.get_session(x_caller_session_id)
        if not session:
            raise HTTPException(status_code=401, detail="unknown session")
        _put_cached_session(x_caller_session_id, session)

    # Cross-check: tmux session name from header must match DB record.
    # Skip when either side is missing (non-tmux callers like TUI, tests).
    if x_tmux_session and session.tmux_session_name:
        if x_tmux_session != session.tmux_session_name:
            raise HTTPException(status_code=403, detail="session identity mismatch")

    system_role = _derive_session_system_role(session)

    # Resolve human_role: prefer DB value, fall back to terminal email or
    # session's own human_email when the session was created without a role
    # (cascading-null prevention for API-dispatched child sessions).
    human_role = session.human_role
    if not human_role:
        fallback_email = x_telec_email or getattr(session, "human_email", None)
        if fallback_email:
            human_role = _resolve_terminal_role(fallback_email)

    return CallerIdentity(
        session_id=x_caller_session_id,
        system_role=system_role,
        human_role=human_role,
        tmux_session_name=session.tmux_session_name,
    )


def _is_tool_denied(tool_name: str, identity: CallerIdentity) -> bool:
    """Check if a tool (mapped from endpoint) is denied for this identity."""
    human_role = identity.human_role
    if human_role is None and identity.principal is not None:
        human_role = identity.principal_role
    return not is_command_allowed(tool_name, identity.system_role, human_role)


def require_clearance(tool_name: str):
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


# Pre-built clearance dependencies for each CLI endpoint

CLEARANCE_SESSIONS_START = require_clearance("telec sessions start")
CLEARANCE_SESSIONS_LIST = require_clearance("telec sessions list")
CLEARANCE_SESSIONS_RUN = require_clearance("telec sessions run")
CLEARANCE_SESSIONS_SEND = require_clearance("telec sessions send")
CLEARANCE_SESSIONS_KEYS = require_clearance("telec sessions send")
CLEARANCE_SESSIONS_VOICE = require_clearance("telec sessions send")
CLEARANCE_SESSIONS_AGENT_RESTART = require_clearance("telec sessions run")
CLEARANCE_SESSIONS_REVIVE = require_clearance("telec sessions run")
CLEARANCE_SESSIONS_TAIL = require_clearance("telec sessions tail")
CLEARANCE_SESSIONS_UNSUBSCRIBE = require_clearance("telec sessions unsubscribe")
CLEARANCE_SESSIONS_RESULT = require_clearance("telec sessions result")
CLEARANCE_SESSIONS_FILE = require_clearance("telec sessions file")
CLEARANCE_SESSIONS_WIDGET = require_clearance("telec sessions widget")
CLEARANCE_SESSIONS_ESCALATE = require_clearance("telec sessions escalate")
CLEARANCE_SESSIONS_END = require_clearance("telec sessions end")
CLEARANCE_TODOS_CREATE = require_clearance("telec todo create")
CLEARANCE_TODOS_PREPARE = require_clearance("telec todo prepare")
CLEARANCE_TODOS_WORK = require_clearance("telec todo work")
CLEARANCE_TODOS_INTEGRATE = require_clearance("telec todo integrate")
CLEARANCE_TODOS_MARK_PHASE = require_clearance("telec todo mark-phase")
CLEARANCE_TODOS_SET_DEPS = require_clearance("telec todo set-deps")
CLEARANCE_OPERATIONS_GET = require_clearance("telec operations get")
CLEARANCE_AGENTS_STATUS = require_clearance("telec agents status")
CLEARANCE_AGENTS_AVAILABILITY = require_clearance("telec agents availability")
CLEARANCE_COMPUTERS_LIST = require_clearance("telec computers list")
CLEARANCE_PROJECTS_LIST = require_clearance("telec projects list")
CLEARANCE_CHANNELS_LIST = require_clearance("telec channels list")
CLEARANCE_CHANNELS_PUBLISH = require_clearance("telec channels publish")
CLEARANCE_EVENTS_EMIT = require_clearance("telec events emit")
