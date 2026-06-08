"""Todo scaffolding helpers and session-touched file resolution."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - narrow sync lookup must tolerate pre-migration local DBs
from sqlalchemy.exc import OperationalError
from sqlmodel import Session as SqlSession

from teleclaude.constants import WORKTREE_DIR
from teleclaude.core import db_models
from teleclaude.core.agents import AgentName, get_default_agent
from teleclaude.core.codex_transcript import discover_codex_transcript_path, discover_current_codex_transcript_path
from teleclaude.core.next_machine._types import default_state
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.git import GitCommandError, Repo
from teleclaude.hooks.receiver._session import _create_sync_engine
from teleclaude.session_identity import get_session_id as _get_session_id
from teleclaude.session_scoping import resolve_scoped_paths
from teleclaude.slug import validate_slug
from teleclaude.types.todo_kind import ALL_DUMP_KINDS, TODO_KIND_DEFAULT


class TranscriptUnavailable(ValueError):
    """Raised when a session has no resolvable transcript to scope changes from.

    Subclass of ValueError so legacy callers catching ValueError still work, while
    allowing precise routing (e.g. scoped-gate fallback to git status) via an
    explicit except clause instead of string-matching the formatted message.
    """


class NoSessionTouchedFiles(ValueError):
    """Raised when session scoping succeeds but owns no transferable paths."""


_scaffold_logger = get_logger(__name__)


def remove_todo(project_root: Path, slug: str) -> None:
    """Remove a todo and all its references. Best-effort: removes whatever exists.

    Removes worktree and local branch for the given slug. DB cleanup
    (roadmap, icebox, state, artifacts) is handled by the /todos/remove API route.

    Args:
        project_root: Project root directory
        slug: Todo slug to remove

    Raises:
        ValueError: If slug format is invalid
    """
    validate_slug(slug)
    slug = slug.strip()

    worktree_path = project_root / WORKTREE_DIR / slug
    repo = Repo(str(project_root))
    if worktree_path.exists():
        try:
            repo.git.worktree("remove", "--force", str(worktree_path))
        except GitCommandError:
            pass

    try:
        repo.git.branch("-D", slug)
    except GitCommandError:
        pass


def create_draft_skeleton(
    project_root: str,
    slug: str,
    *,
    content: str | None = None,
    after: list[str] | None = None,
    kind: str = TODO_KIND_DEFAULT,
) -> str:
    """Create a draft todo skeleton with no input artifact."""
    if not content or not content.strip():
        raise ValueError("content must not be empty")
    validate_slug(slug)
    slug = slug.strip()
    if kind not in ALL_DUMP_KINDS:
        raise ValueError(f"Unknown todo kind: {kind!r}")

    db = get_todos_db_sync(project_root)
    conn = db._sync_conn()
    try:
        existing = conn.execute(
            "SELECT 1 FROM roadmap WHERE slug = ? AND status != 'delivered'",  # guard: raw-sql
            (slug,),
        ).fetchone()
        if existing:
            raise ValueError(f"Todo '{slug}' already exists")

        now = datetime.now(UTC).isoformat()
        row_id = str(_uuid.uuid4())
        conn.execute(
            "INSERT INTO roadmap "  # guard: raw-sql
            "(id, slug, status, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?)",
            (row_id, slug, now, now),
        )
        for dep in after or []:
            conn.execute(
                "INSERT INTO roadmap_deps (slug, depends_on) VALUES (?, ?)",  # guard: raw-sql
                (slug, dep),
            )
        conn.commit()
    finally:
        conn.close()

    state = default_state()
    state["kind"] = kind
    state["lifecycle_phase"] = "draft"
    db.write_state_sync(slug, state)
    return f"Todo created: {slug}"


def _load_session_transcript_metadata(session_id: str) -> tuple[str | None, str | None, str | None]:
    """Load the minimal session metadata needed to discover transcript files.

    Uses raw SQL projected to the three columns the transcript discovery needs
    so the lookup keeps working against local session DBs that have not yet
    applied newer schema migrations.
    """

    try:
        with SqlSession(_create_sync_engine()) as db_session:
            row = db_session.exec(  # type: ignore[call-overload]
                text(
                    "SELECT active_agent, native_log_file, native_session_id "  # guard: raw-sql
                    "FROM sessions WHERE session_id = :session_id"
                ).bindparams(session_id=session_id)
            ).first()
            try:
                active_agent_raw, native_log_file_raw, native_session_id_raw = row
            except (TypeError, ValueError):
                fallback_row = db_session.get(db_models.Session, session_id)
                if not fallback_row:
                    raise NoSessionTouchedFiles(f"Session {session_id} not found in database") from None
                active_agent_raw = getattr(fallback_row, "active_agent", None)
                native_log_file_raw = getattr(fallback_row, "native_log_file", None)
                native_session_id_raw = getattr(fallback_row, "native_session_id", None)
    except OperationalError as exc:
        # An uninitialized session DB (no sessions table — fresh env, CI, or a
        # test temp home) carries no transcript signal. Treat it like the
        # integrator/fresh-shell case so the checkpoint scope falls back to
        # pre-staged instead of crashing.
        if "no such table" in str(exc).lower():
            raise NoSessionTouchedFiles(f"session DB unavailable for {session_id}") from exc
        raise

    return (
        str(active_agent_raw) if active_agent_raw else None,
        str(native_log_file_raw) if native_log_file_raw else None,
        str(native_session_id_raw) if native_session_id_raw else None,
    )


def collect_session_touched_files(project_path: str) -> set[str]:
    """Extract files touched by the current agent session from its transcript.

    Uses the same transcript parsing as the checkpoint system to determine
    which files this session actually mutated. Codex sessions aggregate the
    parent transcript plus any descendant subagent transcripts so attribution
    matches the effective work owned by the parent session.

    Raises:
        ValueError: If session ID is missing, transcript is unavailable,
            or no touched files can be determined.
    """
    session_id = _get_session_id()
    if not session_id:
        raise ValueError("session-touched-files lookup requires an active agent session")

    active_agent_raw, native_log_file, native_session_id = _load_session_transcript_metadata(session_id)
    try:
        agent_name = AgentName.from_str(str(active_agent_raw) if active_agent_raw else get_default_agent())
    except ValueError:
        agent_name = AgentName.CLAUDE

    transcript_path = native_log_file
    if agent_name == AgentName.CODEX:
        current_transcript_path = discover_current_codex_transcript_path()
        if current_transcript_path:
            transcript_path = current_transcript_path
        elif not transcript_path and native_session_id:
            transcript_path = discover_codex_transcript_path(native_session_id)

    if not transcript_path and agent_name != AgentName.CODEX:
        raise TranscriptUnavailable(f"No transcript found for session {session_id}")
    if not transcript_path and not native_session_id:
        raise TranscriptUnavailable(f"No transcript found for session {session_id}")

    scoped_paths = resolve_scoped_paths(
        session_id=session_id,
        workspace_root=project_path,
        agent_name=agent_name.value,
        scope_mode="session_dirty",
        transcript_path=transcript_path,
        native_session_id=native_session_id,
    )

    if scoped_paths.paths:
        touched_files = set(scoped_paths.paths)
        _scaffold_logger.debug("Session %s touched %d files: %s", session_id, len(touched_files), sorted(touched_files))
        return touched_files

    raise NoSessionTouchedFiles(
        f"Could not determine session-touched files from transcript.\n"
        f"Session: {session_id}, attempted transcript: {transcript_path or '<none>'}"
    )
