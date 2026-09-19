"""Session-provenance lookup and per-todo row-state resolution.

The Preparation view's provenance rows are navigation affordances that resolve
stored TeleClaude session ids against the live/closed classification of those
sessions. The lookup is fetched once during initialization, then reconciled
from authoritative websocket snapshots and lifecycle events.
``DataRefreshed`` carries the startup snapshot; this module holds the shared
shape and the pure resolution function so both ends agree on it without
importing each other's widgets.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from teleclaude.types.creation_record import Lineage

SessionStatus = Literal["live", "closed"]
MISSING_SESSION_STATUS = "missing"


class SessionInfo(NamedTuple):
    """Live/closed classification and owning computer for one TeleClaude session id."""

    status: SessionStatus
    computer: str | None


SessionLookup = dict[str, SessionInfo]


class SessionRowState(NamedTuple):
    """Resolved render state for one todo session-provenance detail row.

    ``status`` is ``None`` when the session id is absent from the lookup —
    hard-deleted from the agent_runtime session ledger — so the row renders
    inert text with no click target.
    """

    session_id: str
    status: SessionStatus | None
    computer: str | None


def resolve_session_row_state(session_id: str | None, lookup: SessionLookup) -> SessionRowState | None:
    """Resolve one stored TeleClaude session id for provenance rendering."""
    if not session_id:
        return None
    info = lookup.get(session_id)
    if info is None:
        return SessionRowState(session_id=session_id, status=None, computer=None)
    return SessionRowState(session_id=session_id, status=info.status, computer=info.computer)


def resolve_creator_row_state(lineage: str | None, lookup: SessionLookup) -> SessionRowState | None:
    """Resolve a todo's creator-session row state, or None when no row should render.

    Returns None when the creation lineage carries no acting TeleClaude
    session id — the row is not mounted at all in that case.
    """
    acting_session = Lineage.parse(lineage or "").acting_session
    if not acting_session:
        return None
    return resolve_session_row_state(acting_session, lookup)
