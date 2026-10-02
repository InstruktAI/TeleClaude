"""Session visibility and bounded selection shared by listing surfaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from teleclaude.caller_identity import (
    AllSessionSubjects,
    CliCaller,
    Platform,
    RecordedSubject,
    RoleResolver,
    SessionSubjectReach,
    SystemCliCaller,
)
from teleclaude.config import config
from teleclaude.config_subjects import SubjectRef
from teleclaude.constants import HUMAN_ROLE_CUSTOMER
from teleclaude.core.models import SessionSnapshot
from teleclaude.utils.transcript_discovery import SessionId

CLOSED_SESSION_LISTING_WINDOW = timedelta(days=7)
# 200 UUIDs fit within the daemon's 16 KiB h11 request-head limit with room for other headers.
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

    subject_tokens: frozenset[str] | None
    closed_since: datetime | None
    session_ids: frozenset[str] | None


def build_session_listing_selection(
    caller: CliCaller,
    resolver: RoleResolver,
    *,
    include_closed: bool,
    session_ids: frozenset[str] | None,
    now: datetime | None = None,
) -> SessionListingSelection:
    """Build the local store predicates for one listing request."""
    reach: SessionSubjectReach = resolver.session_subject_reach(caller)
    subject_tokens = (
        None if isinstance(reach, AllSessionSubjects) else frozenset(subject.to_token() for subject in reach.subjects)
    )
    closed_since = None
    if include_closed and session_ids is None:
        closed_since = (now or datetime.now(UTC)) - CLOSED_SESSION_LISTING_WINDOW
    return SessionListingSelection(
        subject_tokens=subject_tokens,
        closed_since=closed_since,
        session_ids=session_ids,
    )


def snapshot_reached_by_subject(
    caller: CliCaller,
    session: SessionSnapshot,
    *,
    resolver: RoleResolver,
) -> bool:
    """Apply the store selection's subject rule to one local snapshot."""
    if isinstance(caller, SystemCliCaller):
        return True
    if session.config_subject is None:
        return resolver.role_for(caller, Platform()) != HUMAN_ROLE_CUSTOMER
    try:
        subject = SubjectRef.from_token(session.config_subject)
    except ValueError:
        return False
    return resolver.role_for(caller, RecordedSubject(subject)) != HUMAN_ROLE_CUSTOMER


def sessions_reached_by(
    caller: CliCaller,
    sessions: Sequence[SessionSnapshot],
    *,
    resolver: RoleResolver,
    caller_session: str | None,
) -> list[SessionSnapshot]:
    """Keep other computers' sessions reached by platform role or direct initiation."""
    system_caller = isinstance(caller, SystemCliCaller)
    platform_reaches = system_caller or resolver.role_for(caller, Platform()) != HUMAN_ROLE_CUSTOMER
    reached: list[SessionSnapshot] = []
    for session in sessions:
        local_session = session.computer in (None, *_LOCAL_COMPUTER_NAMES, config.computer.name)
        if local_session:
            continue
        if caller_session and session.initiator_session_id == caller_session:
            reached.append(session)
        elif platform_reaches:
            reached.append(session)
    return reached
