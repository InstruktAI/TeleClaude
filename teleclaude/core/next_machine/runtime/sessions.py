"""Live session lookup helpers shared across next-machine state machines."""

from __future__ import annotations

from teleclaude.constants import WORKTREE_DIR, SlashCommand
from teleclaude.core.db import Db
from teleclaude.core.session_status import compute_agent_status

TitlePrefixes = str | tuple[str, ...]
PREPARE_LIFECYCLE_COMMANDS: tuple[str, ...] = (
    SlashCommand.NEXT_PREPARE.value,
    SlashCommand.NEXT_PREPARE_INTAKE.value,
    SlashCommand.NEXT_PREPARE_ARCHITECTURE.value,
    SlashCommand.NEXT_PREPARE_PLAN.value,
    SlashCommand.NEXT_REVIEW_ARCHITECTURE.value,
    SlashCommand.NEXT_REVIEW_PLAN.value,
    SlashCommand.NEXT_DRIFT_ANALYZE.value,
)


def _normalize_prefixes(title_prefixes: TitlePrefixes) -> tuple[str, ...]:
    """Return a uniform tuple of accepted title prefixes."""
    if isinstance(title_prefixes, str):
        return (title_prefixes,)
    return title_prefixes


def _matches_title_prefix(title: str | None, title_prefixes: TitlePrefixes) -> bool:
    """Return whether a session title matches any accepted command prefix."""
    normalized_title = (title or "").lstrip()
    return any(normalized_title.startswith(prefix) for prefix in _normalize_prefixes(title_prefixes))


def _expected_subdir(slug: str, subdir_override: str | None) -> str | None:
    """Resolve the canonical subdir used to scope live-session ownership.

    ``subdir_override=""`` and ``subdir_override=None`` both mean "session has
    no subdir". The API stores ``subfolder or None``, so an empty override must
    normalize to ``None`` to match. A non-empty override is returned as-is. A
    missing override defaults to the per-slug worktree path.
    """
    if subdir_override is not None:
        return subdir_override or None
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


_TITLE_SLUG_BOUNDARIES = (" ", "\t", "\n")


def _matches_command_slug_title(title: str | None, slug: str, command_values: TitlePrefixes) -> bool:
    """Return True when a root title matches ``/<command> <slug>`` with a slug boundary."""
    normalized_title = (title or "").lstrip()
    for command_value in _normalize_prefixes(command_values):
        expected_title = f"/{command_value} {slug}"
        if normalized_title == expected_title:
            return True
        if (
            normalized_title.startswith(expected_title)
            and normalized_title[len(expected_title) : len(expected_title) + 1] in _TITLE_SLUG_BOUNDARIES
        ):
            return True
    return False


async def find_live_prepare_worker_for_slug(db: Db, slug: str, command_value: str) -> str | None:
    """Return the newest live prepare worker id for an exact slug+command match.

    Prepare workers run on repo root (subdir=None). A bare ``startswith`` match
    is unsafe here because a colliding slug (``my-slug-extra``) would match a
    lookup for ``my-slug``. This helper requires the session title to equal
    ``/cmd slug`` or to be followed by whitespace, so longer slugs that begin
    with the target slug as a prefix cannot match.
    """
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir is not None:
            continue
        if _matches_command_slug_title(session.title, slug, command_value):
            return session.session_id
    return None


async def find_live_root_next_prepare_session_for_slug(db: Db, slug: str) -> str | None:
    """Return the newest live root ``/next-prepare`` session for ``slug``."""
    return await find_live_prepare_worker_for_slug(db, slug, SlashCommand.NEXT_PREPARE.value)


async def find_live_root_prepare_lifecycle_sessions_for_slug(db: Db, slug: str) -> list[str]:
    """Return live root prepare-lifecycle session ids for ``slug`` with exact slug-boundary matching."""
    sessions = await db.list_sessions(include_closed=False)
    return [
        session.session_id
        for session in sessions
        if session.subdir is None and _matches_command_slug_title(session.title, slug, PREPARE_LIFECYCLE_COMMANDS)
    ]
