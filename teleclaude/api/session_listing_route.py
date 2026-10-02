"""Request parsing and local/cache composition for the sessions route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Query

from teleclaude.api.auth import CallerIdentity, caller_for_role_resolution
from teleclaude.caller_identity import RoleResolver
from teleclaude.core import command_handlers
from teleclaude.core.models import SessionSnapshot
from teleclaude.core.session_listing import build_session_listing_selection, normalize_session_ids, sessions_reached_by

if TYPE_CHECKING:
    from teleclaude.core.cache import DaemonCache


@dataclass(frozen=True)
class ListSessionsQuery:
    """Normalized query parameters for session listing."""

    computer: str | None = None
    include_closed: bool = False
    all_sessions: bool = False
    job: str | None = None
    session_ids: frozenset[str] | None = None


def parse_list_sessions_query(
    computer: str | None = None,
    include_closed: bool = Query(False, alias="closed"),
    all_sessions: bool = Query(False, alias="all"),
    job: str | None = Query(None, alias="job"),
    session_ids: list[str] | None = Query(None, alias="id"),
) -> ListSessionsQuery:
    """Validate and normalize the public listing query parameters."""
    try:
        parsed_session_ids = normalize_session_ids(session_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ListSessionsQuery(
        computer=computer,
        include_closed=include_closed,
        all_sessions=all_sessions,
        job=job,
        session_ids=parsed_session_ids,
    )


async def build_local_session_listing(
    query: ListSessionsQuery,
    identity: CallerIdentity,
    *,
    caller_session_id: str | None,
    cache: DaemonCache | None,
) -> tuple[list[SessionSnapshot], frozenset[str]]:
    """Select local rows and merge only eligible other-computer cache rows."""
    caller = caller_for_role_resolution(identity)
    resolver = RoleResolver()
    selection = build_session_listing_selection(
        caller,
        resolver,
        include_closed=query.include_closed,
        session_ids=query.session_ids,
    )
    local_sessions = await command_handlers.list_sessions(selection=selection)
    if cache is None or query.computer:
        merged = list(local_sessions)
    else:
        remote_cached_sessions = cache.get_sessions()
        if query.session_ids is not None:
            remote_cached_sessions = [
                session for session in remote_cached_sessions if session.session_id in query.session_ids
            ]
        reached_remote_sessions = sessions_reached_by(
            caller,
            remote_cached_sessions,
            resolver=resolver,
            caller_session=caller_session_id,
        )
        by_id = {session.session_id: session for session in local_sessions}
        for session in reached_remote_sessions:
            by_id.setdefault(session.session_id, session)
        merged = list(by_id.values())

    if caller_session_id and not query.all_sessions and query.session_ids is None:
        merged = [session for session in merged if session.initiator_session_id == caller_session_id]
    if query.job:
        merged = [session for session in merged if session.job == query.job]
    return merged, frozenset(session.session_id for session in local_sessions)
