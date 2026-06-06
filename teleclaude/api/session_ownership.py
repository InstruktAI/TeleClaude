"""Resolve whether a session id is owned locally or by a cached peer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from teleclaude.core.models import Session, SessionSnapshot


class SessionLookup(Protocol):
    async def get_session(self, session_id: str) -> Session | None:
        """Return a local session row by id."""
        ...


class SessionSnapshotCache(Protocol):
    def get_sessions(self, computer: str | None = None) -> list[SessionSnapshot]:
        """Return cached session snapshots."""
        ...


@dataclass(frozen=True)
class LocalOwnership:
    """Session ownership resolved to this daemon's local database."""

    session: Session


@dataclass(frozen=True)
class RemoteOwnership:
    """Session ownership resolved to a peer-owned cached snapshot."""

    computer: str
    snapshot: SessionSnapshot

    def __post_init__(self) -> None:
        if not self.computer.strip():
            raise ValueError(f"Cached session {self.snapshot.session_id} is missing owning computer")


type SessionOwnership = LocalOwnership | RemoteOwnership


async def resolve_session_ownership(
    session_id: str,
    *,
    db: SessionLookup,
    cache: SessionSnapshotCache | None,
) -> SessionOwnership | None:
    """Resolve a session id to the daemon that owns it."""
    local_session = await db.get_session(session_id)
    if local_session is not None:
        return LocalOwnership(local_session)

    if cache is None:
        return None

    for snapshot in cache.get_sessions():
        if snapshot.session_id != session_id:
            continue
        computer = snapshot.computer
        if computer is None:
            raise ValueError(f"Cached session {session_id} is missing owning computer")
        return RemoteOwnership(computer=computer, snapshot=snapshot)

    return None
