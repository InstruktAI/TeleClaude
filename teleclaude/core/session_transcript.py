"""The native transcript a session is bound to, and the runtime that writes it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.core.agents import AgentName

if TYPE_CHECKING:
    from teleclaude.core.models import Session

logger = get_logger(__name__)

_INVALID_ACTIVE_AGENT_EVENT = "session_transcript_invalid_active_agent"


@dataclass(frozen=True)
class SessionTranscript:
    """A session's bound native transcript file and the runtime whose format it is in."""

    path: str
    agent: AgentName


def session_transcript(session: Session) -> SessionTranscript | None:
    """Return the session's bound transcript, or ``None`` while it has none to read.

    A session whose recorded runtime is not a known agent is logged: its
    transcript exists but no reader can interpret it.
    """
    if not session.native_log_file or not session.active_agent:
        return None
    try:
        agent = AgentName.from_str(session.active_agent)
    except ValueError:
        logger.warning(_INVALID_ACTIVE_AGENT_EVENT, session_id=session.session_id, active_agent=session.active_agent)
        return None
    return SessionTranscript(session.native_log_file, agent)
