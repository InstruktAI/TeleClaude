"""The facts about a calling session that the lifecycle acts are judged against.

They are read from the session's record, which the platform wrote when it created the session; the
act command takes nothing about the caller from what the caller typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from teleclaude.caller_identity import HUMAN_PRINCIPAL_PREFIX
from teleclaude.core.db import db
from teleclaude.core.session_utils import session_in_claiming_group

NO_PRINCIPAL_EMAIL: Final = ""


@dataclass(frozen=True)
class CallerFacts:
    """A session's identity facts: its launch role and job, who started it, and the person it runs for."""

    session_id: str
    role: str | None
    job: str | None
    initiator_session_id: str | None
    principal_email: str

    def is_persons_own_session(self, person_email: str) -> bool:
        """Whether this is a session the person opened themselves, rather than one that carries their lineage.

        All three hold: its principal is the person, no other session started it, and no dispatcher, job or
        procedure activation launched it under a role.
        """
        return (
            bool(person_email)
            and self.principal_email == person_email
            and not self.initiator_session_id
            and not self.role
            and not self.job
        )


async def load_caller(session_id: str) -> CallerFacts | None:
    """Read a session's identity facts from its record; None when the session is unknown."""
    session = await db.get_session(session_id)
    if session is None:
        return None
    principal = session.principal or ""
    email = principal.removeprefix(HUMAN_PRINCIPAL_PREFIX) if principal.startswith(HUMAN_PRINCIPAL_PREFIX) else ""
    return CallerFacts(
        session_id=session_id,
        role=session.role,
        job=session.job,
        initiator_session_id=session.initiator_session_id,
        principal_email=email or NO_PRINCIPAL_EMAIL,
    )


async def in_claiming_group(caller_session_id: str, holder_session_id: str) -> bool:
    """Whether the caller is the holder or a session dispatched, transitively, from it."""
    return await session_in_claiming_group(caller_session_id, holder_session_id)


async def child_sessions_of(holder_session_id: str) -> tuple[str, ...]:
    """The open sessions the holder started directly."""
    children = await db.list_sessions(all_open=True, initiator_session_id=holder_session_id)
    return tuple(child.session_id for child in children)


async def group_sessions_of(holder_session_id: str) -> tuple[str, ...]:
    """Every open session started from the holder, transitively; the holder itself is not among them."""
    found: list[str] = []
    frontier = [holder_session_id]
    while frontier:
        started = await child_sessions_of(frontier.pop())
        for session_id in started:
            if session_id not in found and session_id != holder_session_id:
                found.append(session_id)
                frontier.append(session_id)
    return tuple(found)
