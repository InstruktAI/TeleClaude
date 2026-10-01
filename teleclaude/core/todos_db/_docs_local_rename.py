"""Forward-migrate pre-layout todo artifacts and state to the current docs layout.

Local documentation moved from `docs/project` to `docs/local`, local agent
artifacts from `agents/project` to `agents/local`, and snippet identities are
qualified by their owning home (`projects/<slug>/…`, `people/<slug>/…`,
`companies/<slug>/…`). Current artifact bodies of live todos cite the retired
forms, so a worker reading them would be sent to paths and ids that no longer
resolve. The migration only rewrites content written before the layout change;
later-authored content may quote retired forms as evidence and must remain as
written across every database bootstrap. It records each converted artifact as
a new version, exactly as an artifact write does, and carries every converted
artifact's new digest through that todo's state. Version history and delivered
or removed records are left as written.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.constants import TodoStatus
from teleclaude.docs_layout import rewrite_layout_text
from teleclaude.snippet_validation import read_declared_project_slug

logger = get_logger(__name__)

_UTF8: Final = "utf-8"
_PROJECT_STATE_DIRNAME: Final = ".teleclaude"
_DOCS_LOCAL_LAYOUT_CHANGE_AT: Final = datetime(
    2026, 10, 1, 1, 35, 17, tzinfo=UTC
)  # 3b2cb35d592d59fb7b3314e4f95b2fef360a08a6
_LEGACY_IMPORT_WRITER: Final = "legacy-import"
_SETTLED_STATUSES: Final = (TodoStatus.DELIVERED.value, TodoStatus.REMOVED.value)
_LIVE_TODO_FILTER: Final = "id IN (SELECT id FROM todo WHERE status NOT IN (?, ?))"
_SELECT_ARTIFACTS_SQL: Final = (
    "SELECT id, slug, name, content, digest, updated_by, updated_at FROM todo_artifacts WHERE " + _LIVE_TODO_FILTER
)
_SELECT_ARTIFACT_BY_ID_SQL: Final = (
    "SELECT id, slug, name, content, digest, updated_by, updated_at "
    "FROM todo_artifacts WHERE id = ? AND name = ? AND " + _LIVE_TODO_FILTER
)
_UPDATE_ARTIFACT_SQL: Final = (
    "UPDATE todo_artifacts SET content = ?, digest = ?, updated_at = ? WHERE id = ? AND name = ?"
)
_INSERT_VERSION_SQL: Final = (
    "INSERT INTO todo_artifact_versions (id, slug, name, content, digest, updated_by, created_at) "
    "VALUES (?, ?, ?, ?, ?, NULL, ?)"
)
_SELECT_STATES_SQL: Final = "SELECT id, state, updated_at FROM todo_state WHERE " + _LIVE_TODO_FILTER
_SELECT_STATE_BY_ID_SQL: Final = "SELECT id, state, updated_at FROM todo_state WHERE id = ? AND " + _LIVE_TODO_FILTER
_UPDATE_STATE_SQL: Final = "UPDATE todo_state SET state = ? WHERE id = ?"
_BEGIN_IMMEDIATE_SQL: Final = "BEGIN IMMEDIATE"
_TABLE_EXISTS_SQL: Final = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_REQUIRED_TABLES: Final = ("todo", "todo_artifacts", "todo_artifact_versions", "todo_state")
_MIGRATION_COMPLETE_EVENT: Final = "todo docs/local rename migration complete"
_UNDECLARED_SLUG_EVENT: Final = "todo docs/local rename: owning project declares no slug; unqualified ids kept"


def _owning_project_slug(db_path: str) -> str | None:
    """Declared slug of the project owning ``<root>/.teleclaude/todos.db``, or ``None``."""
    state_dir = Path(db_path).expanduser().resolve().parent
    if state_dir.name != _PROJECT_STATE_DIRNAME:
        return None
    try:
        return read_declared_project_slug(state_dir.parent)
    except ValueError:
        logger.info(_UNDECLARED_SLUG_EVENT, project_root=str(state_dir.parent))
        return None


def _rename_text(text: str, own_slug: str | None) -> str:
    return rewrite_layout_text(text, own_slug=own_slug, registered_slugs=(), markdown=True)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode(_UTF8)).hexdigest()


def _is_before_layout_change(timestamp: str | None) -> bool:
    if timestamp is None:
        return True
    instant = datetime.fromisoformat(timestamp)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC) < _DOCS_LOCAL_LAYOUT_CHANGE_AT


def _artifact_is_migration_input(updated_by: str | None, updated_at: str | None) -> bool:
    return updated_by == _LEGACY_IMPORT_WRITER or _is_before_layout_change(updated_at)


def _state_is_migration_input(updated_at: str | None) -> bool:
    return updated_at is not None and _is_before_layout_change(updated_at)


def _has_required_tables(conn: sqlite3.Connection) -> bool:
    return all(conn.execute(_TABLE_EXISTS_SQL, (table,)).fetchone() for table in _REQUIRED_TABLES)


def _rewrite_artifacts(
    conn: sqlite3.Connection,
    own_slug: str | None,
    candidates: set[tuple[str, str]],
) -> dict[str, dict[str, str]]:
    """Rewrite eligible current artifacts; return old-to-new digests per todo id."""
    now = datetime.now(UTC).isoformat()
    digest_moves: dict[str, dict[str, str]] = {}
    for todo_id, name in candidates:
        row = conn.execute(
            _SELECT_ARTIFACT_BY_ID_SQL,
            (todo_id, name, *_SETTLED_STATUSES),
        ).fetchone()  # guard: raw-sql
        if row is None:
            continue
        todo_id, slug, name, content, old_digest, updated_by, updated_at = row
        if not _artifact_is_migration_input(updated_by, updated_at):
            continue
        renamed = _rename_text(content, own_slug)
        if renamed == content:
            continue
        new_digest = _sha256(renamed)
        conn.execute(_UPDATE_ARTIFACT_SQL, (renamed, new_digest, now, todo_id, name))  # guard: raw-sql
        conn.execute(_INSERT_VERSION_SQL, (todo_id, slug, name, renamed, new_digest, now))  # guard: raw-sql
        digest_moves.setdefault(todo_id, {})[old_digest] = new_digest
    return digest_moves


def _rewrite_states(
    conn: sqlite3.Connection,
    digest_moves: dict[str, dict[str, str]],
    candidates: set[str],
    own_slug: str | None,
) -> int:
    rewritten = 0
    for todo_id in candidates | digest_moves.keys():
        row = conn.execute(
            _SELECT_STATE_BY_ID_SQL,
            (todo_id, *_SETTLED_STATUSES),
        ).fetchone()  # guard: raw-sql
        if row is None:
            continue
        todo_id, state, updated_at = row
        renamed = _rename_text(state, own_slug) if _state_is_migration_input(updated_at) else state
        for old_digest, new_digest in digest_moves.get(todo_id, {}).items():
            renamed = renamed.replace(old_digest, new_digest)
        if renamed != state:
            conn.execute(_UPDATE_STATE_SQL, (renamed, todo_id))  # guard: raw-sql
            rewritten += 1
    return rewritten


def migrate_docs_local_rename(conn: sqlite3.Connection, db_path: str) -> None:
    """Carry pre-layout content forward without rewriting later-authored records."""
    if not _has_required_tables(conn):
        return
    own_slug = _owning_project_slug(db_path)
    artifact_candidates = {
        (todo_id, name)
        for todo_id, _, name, content, _, updated_by, updated_at in conn.execute(
            _SELECT_ARTIFACTS_SQL, _SETTLED_STATUSES
        ).fetchall()  # guard: raw-sql
        if _artifact_is_migration_input(updated_by, updated_at) and _rename_text(content, own_slug) != content
    }
    state_candidates = {
        todo_id
        for todo_id, state, updated_at in conn.execute(
            _SELECT_STATES_SQL, _SETTLED_STATUSES
        ).fetchall()  # guard: raw-sql
        if _state_is_migration_input(updated_at) and _rename_text(state, own_slug) != state
    }
    if not artifact_candidates and not state_candidates:
        conn.commit()
        return

    conn.execute(_BEGIN_IMMEDIATE_SQL)
    try:
        digest_moves = _rewrite_artifacts(conn, own_slug, artifact_candidates)
        rewritten_states = _rewrite_states(conn, digest_moves, state_candidates, own_slug)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    rewritten_artifacts = sum(len(moves) for moves in digest_moves.values())
    if rewritten_artifacts or rewritten_states:
        logger.info(
            _MIGRATION_COMPLETE_EVENT,
            artifacts=rewritten_artifacts,
            states=rewritten_states,
        )
