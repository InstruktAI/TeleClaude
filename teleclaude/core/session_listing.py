"""Session visibility and bounded selection shared by listing surfaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from teleclaude.caller_identity import CliCaller
from teleclaude.config import config
from teleclaude.core.models import SessionSnapshot
from teleclaude.identity_reach import Reach, resolve_reach
from teleclaude.utils.transcript_discovery import SessionId

CLOSED_SESSION_LISTING_WINDOW = timedelta(days=7)
# Keep an ID batch below the daemon request-head limit with room for other headers.
SESSION_LISTING_MAX_IDS = 200
SESSION_IDS_FIELD = "ids"
SESSION_LISTING_ID_LIMIT_DETAIL = f"Session listing accepts at most {SESSION_LISTING_MAX_IDS} session IDs"
SESSION_LISTING_INVALID_ID_DETAIL = "Session listing IDs must be canonical session UUIDs"
SESSION_LISTING_INVALID_ID_SHAPE_DETAIL = "Session listing IDs must be a list of canonical session UUIDs"

_LOCAL_COMPUTER_NAMES = ("", "local")


def normalize_session_ids(raw_ids: object) -> frozenset[str] | None:
    """Validate repeated listing IDs or their relayed JSON representation."""
    if raw_ids is None:
        return None
    if not isinstance(raw_ids, list):
        raise ValueError(SESSION_LISTING_INVALID_ID_SHAPE_DETAIL)
    if len(raw_ids) > SESSION_LISTING_MAX_IDS:
        raise ValueError(SESSION_LISTING_ID_LIMIT_DETAIL)
    if any(not isinstance(value, str) for value in raw_ids):
        raise ValueError(SESSION_LISTING_INVALID_ID_DETAIL)
    try:
        return frozenset(str(SessionId(value)) for value in raw_ids)
    except ValueError as exc:
        raise ValueError(SESSION_LISTING_INVALID_ID_DETAIL) from exc


@dataclass(frozen=True)
class SessionListingSelection:
    """Store predicates resolved once from a caller's listing request."""

    reach: Reach
    closed_since: datetime | None
    session_ids: frozenset[str] | None


def build_session_listing_selection(
    caller: CliCaller,
    *,
    include_closed: bool,
    session_ids: frozenset[str] | None,
) -> SessionListingSelection:
    """Build the local store predicates for one listing request."""
    reach = resolve_reach(caller)
    closed_since = None
    if include_closed and session_ids is None:
        closed_since = datetime.now(UTC) - CLOSED_SESSION_LISTING_WINDOW
    return SessionListingSelection(
        reach=reach,
        closed_since=closed_since,
        session_ids=session_ids,
    )


def snapshot_reached_by_reach(
    reach: Reach,
    session: SessionSnapshot,
) -> bool:
    """Apply identity reach to a relayed or cached session snapshot."""
    return reach.admits(session.config_subject, session.subject_owner, session.principal)


def sessions_reached_by(
    reach: Reach,
    sessions: Sequence[SessionSnapshot],
) -> list[SessionSnapshot]:
    """Keep other-computer sessions whose recorded facts fall within reach."""
    reached: list[SessionSnapshot] = []
    for session in sessions:
        local_session = session.computer in (None, *_LOCAL_COMPUTER_NAMES, config.computer.name)
        if local_session:
            continue
        if snapshot_reached_by_reach(reach, session):
            reached.append(session)
    return reached
