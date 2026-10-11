"""Pure agent-status projections for local and mixed-version read surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from teleclaude.core.session_status import (
    AgentStatusValue,
    SessionLifecycleStatus,
    is_session_terminal,
)

if TYPE_CHECKING:
    from teleclaude.core.models import Session


def project_peer_agent_status(status: AgentStatusValue) -> AgentStatusValue:
    """Project a new status onto the vocabulary accepted by older fleet nodes."""
    return AgentStatusValue.ACTIVE if status is AgentStatusValue.BLOCKED else status


def read_session_agent_status(session: Session) -> AgentStatusValue:
    """Read the stored status, with a terminal lifecycle authoritative as idle."""
    if is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at):
        return AgentStatusValue.IDLE
    return session.agent_status


def project_readiness_fields(
    session: Session,
    now: datetime,
) -> tuple[int | None, str | None, str | None]:
    """Project stored startup status onto the legacy readiness fields."""
    initializing_for_seconds = None
    if session.lifecycle_status == SessionLifecycleStatus.INITIALIZING and session.created_at is not None:
        initializing_for_seconds = int((now - session.created_at).total_seconds())
    return initializing_for_seconds, None, None
