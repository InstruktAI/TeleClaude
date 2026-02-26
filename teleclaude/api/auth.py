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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

from teleclaude.config.loader import load_global_config
from teleclaude.constants import HUMAN_ROLE_ADMIN, HUMAN_ROLES, ROLE_ORCHESTRATOR, ROLE_WORKER
from teleclaude.core.db import db
from teleclaude.core.tool_access import get_excluded_tools

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def _default_unidentified_human_role() -> str:
    configured = (os.getenv("TELECLAUDE_UNIDENTIFIED_HUMAN_ROLE", HUMAN_ROLE_ADMIN) or "").strip()
    return configured or HUMAN_ROLE_ADMIN


DEFAULT_UNIDENTIFIED_HUMAN_ROLE = _default_unidentified_human_role()

_GLOBAL_CONFIG_PATH = Path("~/.teleclaude/teleclaude.yml").expanduser()
_email_role_cache: dict[str, str] = {}
_email_role_cache_mtime_ns: int | None = None


def _normalize_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _load_email_role_map() -> dict[str, str]:
    """Load email->role map from global config with mtime-based cache."""
    global _email_role_cache, _email_role_cache_mtime_ns

    try:
        mtime_ns = _GLOBAL_CONFIG_PATH.stat().st_mtime_ns
    except OSError:
        _email_role_cache = {}
        _email_role_cache_mtime_ns = None
        return _email_role_cache

    if _email_role_cache_mtime_ns == mtime_ns:
        return _email_role_cache

    role_map: dict[str, str] = {}
    try:
        global_cfg = load_global_config(_GLOBAL_CONFIG_PATH)
    except Exception:
        return _email_role_cache

    for person in global_cfg.people:
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


def _derive_session_system_role(session: "Session") -> str | None:
    """Derive system role from daemon-owned session state.

    Priority:
    1. Explicit `session_metadata.system_role` if present and valid.
    2. Worker heuristic: sessions with a `working_slug` are worker sessions.
    3. Otherwise unknown (treated as non-worker for system-role restrictions).
    """
    metadata = session.session_metadata
    if isinstance(metadata, dict):
        raw_role = metadata.get("system_role")
        if isinstance(raw_role, str):
            normalized = raw_role.strip().lower()
            if normalized in {ROLE_WORKER, ROLE_ORCHESTRATOR}:
                return normalized

    return ROLE_WORKER if session.working_slug else None


@dataclass(frozen=True)
class CallerIdentity:
    """Verified caller identity for role clearance checks."""

    session_id: str
    system_role: str | None  # e.g. "worker" or None (orchestrator/admin)
    human_role: str | None  # e.g. "admin", "member", etc.
    tmux_session_name: str | None  # for diagnostic use only


async def verify_caller(
    request: Request,
    x_caller_session_id: Annotated[str | None, Header()] = None,
    x_telec_email: Annotated[str | None, Header()] = None,
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
    if not x_caller_session_id:
        # Terminal/TUI mode without daemon session marker:
        # - tmux contexts get the default unidentified role
        # - non-tmux contexts may use telec login email mapping
        # - otherwise reject as unauthorized
        if x_tmux_session:
            return CallerIdentity(
                session_id="",
                system_role=None,
                human_role=DEFAULT_UNIDENTIFIED_HUMAN_ROLE,
                tmux_session_name=x_tmux_session,
            )
        terminal_role = _resolve_terminal_role(x_telec_email)
        if terminal_role:
            return CallerIdentity(
                session_id="",
                system_role=None,
                human_role=terminal_role,
                tmux_session_name=None,
            )
        raise HTTPException(status_code=401, detail="missing session")

    session = await db.get_session(x_caller_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="unknown session")

    # Cross-check: tmux session name from header must match DB record.
    # Skip when either side is missing (non-tmux callers like TUI, tests).
    if x_tmux_session and session.tmux_session_name:
        if x_tmux_session != session.tmux_session_name:
            raise HTTPException(status_code=403, detail="session identity mismatch")

    system_role = _derive_session_system_role(session)

    return CallerIdentity(
        session_id=x_caller_session_id,
        system_role=system_role,
        human_role=session.human_role,
        tmux_session_name=session.tmux_session_name,
    )


def _is_tool_denied(tool_name: str, identity: CallerIdentity) -> bool:
    """Check if a tool (mapped from endpoint) is denied for this identity."""
    excluded = get_excluded_tools(identity.system_role, identity.human_role)
    return tool_name in excluded


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
CLEARANCE_TODOS_PREPARE = require_clearance("telec todo prepare")
CLEARANCE_TODOS_WORK = require_clearance("telec todo work")
CLEARANCE_TODOS_MAINTAIN = require_clearance("telec todo maintain")
CLEARANCE_TODOS_MARK_PHASE = require_clearance("telec todo mark-phase")
CLEARANCE_TODOS_SET_DEPS = require_clearance("telec todo set-deps")
CLEARANCE_DEPLOY = require_clearance("telec deploy")
CLEARANCE_AGENTS_STATUS = require_clearance("telec agents status")
CLEARANCE_AGENTS_AVAILABILITY = require_clearance("telec agents availability")
CLEARANCE_COMPUTERS_LIST = require_clearance("telec computers list")
CLEARANCE_PROJECTS_LIST = require_clearance("telec projects list")
CLEARANCE_CHANNELS_LIST = require_clearance("telec channels list")
CLEARANCE_CHANNELS_PUBLISH = require_clearance("telec channels publish")
