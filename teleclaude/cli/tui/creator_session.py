"""Creator-session lookup and per-todo row-state resolution.

The Preparation view's creator-session detail row is a navigation affordance
that resolves a todo's creation lineage against the live/closed classification
of TeleClaude sessions. The lookup is fetched once during initialization,
then reconciled from authoritative websocket snapshots and lifecycle events.
``DataRefreshed`` carries the startup snapshot; this module holds the shared
shape and the pure resolution function so both ends agree on it without
importing each other's widgets.
"""

from __future__ import annotations

from typing import Literal, NamedTuple

from teleclaude.types.creation_record import Lineage

CreatorSessionStatus = Literal["live", "closed"]


class CreatorSessionInfo(NamedTuple):
    """Live/closed classification and owning computer for one TeleClaude session id."""

    status: CreatorSessionStatus
    computer: str | None


CreatorSessionLookup = dict[str, CreatorSessionInfo]


class CreatorRowState(NamedTuple):
    """Resolved render state for a todo's creator-session detail row.

    ``status`` is ``None`` when the session id is absent from the lookup —
    hard-deleted from the agent_runtime session ledger — so the row renders
    inert text with no click target.
    """

    session_id: str
    status: CreatorSessionStatus | None
    computer: str | None


def resolve_creator_row_state(lineage: str | None, lookup: CreatorSessionLookup) -> CreatorRowState | None:
    """Resolve a todo's creator-session row state, or None when no row should render.

    Returns None when the creation lineage carries no acting TeleClaude
    session id — the row is not mounted at all in that case.
    """
    acting_session = Lineage.parse(lineage or "").acting_session
    if not acting_session:
        return None
    info = lookup.get(acting_session)
    if info is None:
        return CreatorRowState(session_id=acting_session, status=None, computer=None)
    return CreatorRowState(session_id=acting_session, status=info.status, computer=info.computer)
