"""Daemon-side role enforcement for telec API endpoints.

Provides FastAPI dependencies for dual-factor caller identity verification
and role-based clearance checks. Replaces legacy wrapper-side
tool filtering with tamper-resistant server-side enforcement.

Identity verification flow:
1. Missing X-Caller-Session-Id → 401
2. Unknown session_id in DB → 401
3. X-Tmux-Session present AND session has tmux_session_name → cross-check → 403 on mismatch
4. Insufficient clearance → 403
5. All clear → proceed

The system_role is derived from daemon-owned session state in the database.
The human_role comes from the DB session record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, Request

from teleclaude.constants import ROLE_ORCHESTRATOR, ROLE_WORKER
from teleclaude.core.db import db
from teleclaude.core.tool_access import get_excluded_tools

if TYPE_CHECKING:
    from teleclaude.core.models import Session


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
    x_caller_session_id: str | None = Header(None),
    x_tmux_session: str | None = Header(None),
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
        raise HTTPException(status_code=401, detail="session identity required")

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

    Maps CLI endpoint names to teleclaude tool names and checks role clearance.

    Args:
        tool_name: Tool name (e.g. "teleclaude__start_session")

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

CLEARANCE_SESSIONS_START = require_clearance("teleclaude__start_session")
CLEARANCE_SESSIONS_LIST = require_clearance("teleclaude__list_sessions")
CLEARANCE_SESSIONS_RUN = require_clearance("teleclaude__run_agent_command")
CLEARANCE_SESSIONS_SEND = require_clearance("teleclaude__send_message")
CLEARANCE_SESSIONS_KEYS = require_clearance("teleclaude__send_message")
CLEARANCE_SESSIONS_VOICE = require_clearance("teleclaude__send_message")
CLEARANCE_SESSIONS_AGENT_RESTART = require_clearance("teleclaude__run_agent_command")
CLEARANCE_SESSIONS_REVIVE = require_clearance("teleclaude__run_agent_command")
CLEARANCE_SESSIONS_TAIL = require_clearance("teleclaude__get_session_data")
CLEARANCE_SESSIONS_UNSUBSCRIBE = require_clearance("teleclaude__stop_notifications")
CLEARANCE_SESSIONS_RESULT = require_clearance("teleclaude__send_result")
CLEARANCE_SESSIONS_FILE = require_clearance("teleclaude__send_file")
CLEARANCE_SESSIONS_WIDGET = require_clearance("teleclaude__render_widget")
CLEARANCE_SESSIONS_ESCALATE = require_clearance("teleclaude__escalate")
CLEARANCE_SESSIONS_END = require_clearance("teleclaude__end_session")
CLEARANCE_TODOS_PREPARE = require_clearance("teleclaude__next_prepare")
CLEARANCE_TODOS_WORK = require_clearance("teleclaude__next_work")
CLEARANCE_TODOS_MAINTAIN = require_clearance("teleclaude__next_maintain")
CLEARANCE_TODOS_MARK_PHASE = require_clearance("teleclaude__mark_phase")
CLEARANCE_TODOS_SET_DEPS = require_clearance("teleclaude__set_dependencies")
CLEARANCE_DEPLOY = require_clearance("teleclaude__deploy")
CLEARANCE_AGENTS_STATUS = require_clearance("teleclaude__mark_agent_status")
CLEARANCE_AGENTS_AVAILABILITY = require_clearance("teleclaude__agents_availability")
CLEARANCE_COMPUTERS_LIST = require_clearance("teleclaude__list_computers")
CLEARANCE_PROJECTS_LIST = require_clearance("teleclaude__list_projects")
CLEARANCE_CHANNELS_LIST = require_clearance("teleclaude__channels_list")
CLEARANCE_CHANNELS_PUBLISH = require_clearance("teleclaude__publish")
