"""Resolve prior-reviewer agents for a reviewer run-session request's target.

Split out of ``sessions_actions_routes.py`` to keep that module under the
repository's module-size guardrail, alongside its sibling ``run_session_*``
helper modules.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.dates import ensure_utc, parse_iso_datetime
from teleclaude.core.db import db
from teleclaude.core.todos_db import get_todos_db

__all__ = ["resolve_excluded_reviewer_agents"]


async def resolve_excluded_reviewer_agents(
    project_path: str,
    slug: str,
    command: str,
) -> frozenset[str]:
    """Return the agents that already reviewed one slug's exact review-command subject.

    Scoped to sessions created no earlier than the todo record's own creation,
    so a reused slug never inherits a delivered todo's prior reviewers. Agent
    selection stays with the dispatch resolver; this only names who already
    reviewed the target.
    """
    todos_db = await get_todos_db(project_path)
    created_at = await todos_db.get_created_at(slug)
    not_before = parse_iso_datetime(created_at) if created_at else None
    # A resolve failure here is a real environment/path defect, not an absence
    # of prior reviewers — surface it rather than silently admitting every
    # candidate, which would defeat the resolver's hard-exclusion guarantee.
    project_root = Path(project_path).resolve()
    sessions = await db.list_sessions(include_closed=True)
    excluded: set[str] = set()
    for session in sessions:
        if session.working_slug != slug or session.command != command:
            continue
        if not session.project_path:
            continue
        try:
            if Path(session.project_path).resolve() != project_root:
                continue
        except OSError:
            continue
        if not_before is not None and session.created_at is not None and ensure_utc(session.created_at) < not_before:
            continue
        if session.active_agent:
            excluded.add(session.active_agent)
    return frozenset(excluded)
