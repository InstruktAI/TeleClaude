"""Live session lookup helpers shared across next-machine state machines."""

from __future__ import annotations

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.db import Db
from teleclaude.core.session_status import compute_agent_status

TitlePrefixes = str | tuple[str, ...]


def _normalize_prefixes(title_prefixes: TitlePrefixes) -> tuple[str, ...]:
    """Return a uniform tuple of accepted title prefixes."""
    if isinstance(title_prefixes, str):
        return (title_prefixes,)
    return title_prefixes


def _matches_title_prefix(title: str | None, title_prefixes: TitlePrefixes) -> bool:
    """Return whether a session title matches any accepted command prefix."""
    normalized_title = (title or "").lstrip()
    return any(normalized_title.startswith(prefix) for prefix in _normalize_prefixes(title_prefixes))


def _expected_subdir(slug: str, subdir_override: str | None) -> str:
    """Resolve the canonical subdir used to scope live-session ownership."""
    if subdir_override is not None:
        return subdir_override
    return f"{WORKTREE_DIR}/{slug}"


async def find_live_session_for_slug(
    db: Db,
    slug: str,
    title_prefixes: TitlePrefixes,
    subdir_override: str | None = None,
) -> str | None:
    """Return the newest live session id for a slug and command-family prefix."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        if _matches_title_prefix(session.title, title_prefixes):
            return session.session_id
    return None


async def find_live_session_with_status_for_slug(
    db: Db,
    slug: str,
    title_prefixes: TitlePrefixes,
    subdir_override: str | None = None,
) -> tuple[str | None, str]:
    """Return the newest live session id plus computed agent status for a slug."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        if not _matches_title_prefix(session.title, title_prefixes):
            continue
        return (
            session.session_id,
            compute_agent_status(
                last_activity=session.last_activity,
                last_input_at=session.last_message_sent_at,
                last_agent_stop_at=session.last_agent_stop_at,
            ),
        )
    return None, "unknown"


async def find_all_live_sessions_for_slug(
    db: Db,
    slug: str,
    subdir_override: str | None = None,
) -> list[str]:
    """Return all live session ids for a slug, regardless of command family."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    return [session.session_id for session in sessions if session.subdir == expected_subdir]
