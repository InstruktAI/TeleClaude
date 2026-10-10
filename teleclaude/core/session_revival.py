"""Session revival: whether a closed session can resume its agent, and bringing it back."""

from __future__ import annotations

from typing import Final

from teleclaude.core.command_registry import get_command_service
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.types.commands import ReviveAgentCommand

_RESTART_OK_FIELD: Final = "ok"


def session_is_resumable(session: Session) -> bool:
    """Whether the session recorded an agent and its native session id, the transcript a revival resumes."""
    return bool(session.active_agent and session.native_session_id)


async def revive_session(session_id: str) -> bool:
    """Revive a closed session through the restart flow; whether its agent was relaunched.

    A session that cannot resume is refused here so the restart flow never
    reports a failure into the session.
    """
    session = await db.get_session(session_id)
    if session is None or not session_is_resumable(session):
        return False
    result = await get_command_service().restart_agent(ReviveAgentCommand(session_id=session_id))
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result[_RESTART_OK_FIELD])
