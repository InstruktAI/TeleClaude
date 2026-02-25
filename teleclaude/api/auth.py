"""Daemon-side role enforcement for telec API endpoints.

Provides FastAPI dependencies for dual-factor caller identity verification
and role-based clearance checks. Replaces the MCP wrapper's file-based
tool filtering with tamper-resistant server-side enforcement.

Identity verification flow:
1. Missing X-Caller-Session-Id → 401
2. Unknown session_id in DB → 401
3. X-Tmux-Session present AND session has tmux_session_name → cross-check → 403 on mismatch
4. Insufficient clearance → 403
5. All clear → proceed

The system_role (worker) is read from the per-session role marker file written
by the MCP wrapper. The human_role comes from the DB session record.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from teleclaude.core.db import db
from teleclaude.mcp.role_tools import get_excluded_tools

_SESSION_TMPDIR_BASE_OVERRIDE = "TELECLAUDE_SESSION_TMPDIR_BASE"


def _get_session_tmp_basedir() -> Path:
    override = os.environ.get(_SESSION_TMPDIR_BASE_OVERRIDE)
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~/.teleclaude/tmp/sessions"))


def _safe_path_component(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _read_session_system_role(session_id: str) -> str | None:
    """Read system role from per-session role marker file.

    The MCP wrapper writes the role to ~/.teleclaude/tmp/sessions/{id}/teleclaude_role.
    Returns None when no role marker exists (non-worker session or unknown).
    """
    safe_id = _safe_path_component(session_id)
    base_dir = _get_session_tmp_basedir()
    marker = base_dir / safe_id / "teleclaude_role"
    try:
        value = marker.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


@dataclass(frozen=True)
class CallerIdentity:
    """Verified caller identity for role clearance checks."""

    session_id: str
    system_role: str | None  # e.g. "worker" or None (orchestrator/admin)
    human_role: str | None  # e.g. "admin", "member", etc.
    tmux_session_name: str | None  # for diagnostic use only


async def verify_caller(
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

    system_role = _read_session_system_role(x_caller_session_id)

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

    Maps CLI endpoint names to MCP tool names and uses the existing permission
    matrix from role_tools.py to check clearance.

    Args:
        tool_name: MCP tool name (e.g. "teleclaude__start_session")

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
# Maps endpoint → MCP tool name for permission matrix lookup

CLEARANCE_SESSIONS_START = require_clearance("teleclaude__start_session")
CLEARANCE_SESSIONS_RUN = require_clearance("teleclaude__run_agent_command")
CLEARANCE_SESSIONS_SEND = require_clearance("teleclaude__send_message")
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
