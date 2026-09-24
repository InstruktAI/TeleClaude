"""Forward migration of stored todo artifacts and state to the `sdlc` domain and unprefixed commands.

The `software-development` documentation domain is now `sdlc`, and global
commands no longer carry a `next-` prefix. Current artifact bodies and todo
state name snippet ids, snippet paths, and commands under the old names, so a
worker reading them after the rename would be sent to ids that no longer
resolve. This one-way migration rewrites the current artifact bodies — recording
each rewrite as a new version, exactly as an artifact write does — and then
carries every rewritten artifact's new digest through the todo's state, so
approvals, upstream digests, and plan digests keep pointing at the artifact they
recorded. Version history is left as written. The old names exist only as this
module's input. Idempotent: a rewritten row no longer matches any rule.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)

_OLD_DOMAIN = "software-development"
_OLD_DOMAIN_MODULE = "software_development"
_NEW_DOMAIN = "sdlc"
_OLD_LIFECYCLE_DESIGN_PATH = "software-development/design/sdlc/"
_NEW_LIFECYCLE_DESIGN_PATH = "sdlc/design/lifecycle/"
_RENAMED_COMMANDS = (
    "review-architecture",
    "prepare-architecture",
    "prepare-diagnose",
    "prepare-intake",
    "review-commits",
    "drift-analyze",
    "review-build",
    "prepare-plan",
    "prepare-task",
    "create-html",
    "review-plan",
    "coordinate",
    "create-art",
    "review-prd",
    "integrate",
    "finalize",
    "research",
    "run-task",
    "prepare",
    "run-job",
    "assist",
    "create",
    "defer",
    "build",
    "work",
)
_COMMAND_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])next-(" + "|".join(re.escape(name) for name in _RENAMED_COMMANDS) + r")(?![A-Za-z0-9_-])"
)
_COMMAND_REPLACEMENT = r"\1"
_TEXT_RULES: tuple[tuple[str, str], ...] = (
    (_OLD_LIFECYCLE_DESIGN_PATH, _NEW_LIFECYCLE_DESIGN_PATH),
    (_OLD_DOMAIN, _NEW_DOMAIN),
    (_OLD_DOMAIN_MODULE, _NEW_DOMAIN),
)

_CANDIDATE_FILTER = "WHERE instr({column}, ?) > 0 OR instr({column}, ?) > 0 OR instr({column}, ?) > 0"
_CANDIDATE_MARKERS = (_OLD_DOMAIN, _OLD_DOMAIN_MODULE, "next-")
_SELECT_ARTIFACTS_SQL = "SELECT id, slug, name, content, digest FROM todo_artifacts " + _CANDIDATE_FILTER.format(
    column="content"
)
_UPDATE_ARTIFACT_SQL = "UPDATE todo_artifacts SET content = ?, digest = ?, updated_at = ? WHERE id = ? AND name = ?"
_INSERT_VERSION_SQL = (
    "INSERT INTO todo_artifact_versions (id, slug, name, content, digest, updated_by, created_at) "
    "VALUES (?, ?, ?, ?, ?, NULL, ?)"
)
_SELECT_STATES_SQL = "SELECT id, state FROM todo_state " + _CANDIDATE_FILTER.format(column="state")
_SELECT_STATE_BY_ID_SQL = "SELECT state FROM todo_state WHERE id = ?"
_UPDATE_STATE_SQL = "UPDATE todo_state SET state = ? WHERE id = ?"
_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
_REQUIRED_TABLES = ("todo_artifacts", "todo_artifact_versions", "todo_state")


def _rename_text(text: str) -> str:
    renamed = text
    for old, new in _TEXT_RULES:
        renamed = renamed.replace(old, new)
    return _COMMAND_PATTERN.sub(_COMMAND_REPLACEMENT, renamed)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _has_required_tables(conn: sqlite3.Connection) -> bool:
    return all(conn.execute(_TABLE_EXISTS_SQL, (table,)).fetchone() for table in _REQUIRED_TABLES)


def _rewrite_artifacts(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Rewrite current artifact bodies; return old->new digests per todo id."""
    now = datetime.now(UTC).isoformat()
    digest_moves: dict[str, dict[str, str]] = {}
    for todo_id, slug, name, content, old_digest in conn.execute(
        _SELECT_ARTIFACTS_SQL, _CANDIDATE_MARKERS
    ).fetchall():  # guard: raw-sql
        renamed = _rename_text(content)
        if renamed == content:
            continue
        new_digest = _sha256(renamed)
        conn.execute(_UPDATE_ARTIFACT_SQL, (renamed, new_digest, now, todo_id, name))  # guard: raw-sql
        conn.execute(_INSERT_VERSION_SQL, (todo_id, slug, name, renamed, new_digest, now))  # guard: raw-sql
        digest_moves.setdefault(todo_id, {})[old_digest] = new_digest
    return digest_moves


def _rewrite_states(conn: sqlite3.Connection, digest_moves: dict[str, dict[str, str]]) -> int:
    candidates = dict(conn.execute(_SELECT_STATES_SQL, _CANDIDATE_MARKERS).fetchall())  # guard: raw-sql
    for todo_id in digest_moves.keys() - candidates.keys():
        row = conn.execute(_SELECT_STATE_BY_ID_SQL, (todo_id,)).fetchone()  # guard: raw-sql
        if row is not None:
            candidates[todo_id] = row[0]
    rewritten = 0
    for todo_id, state in candidates.items():
        renamed = _rename_text(state)
        for old_digest, new_digest in digest_moves.get(todo_id, {}).items():
            renamed = renamed.replace(old_digest, new_digest)
        if renamed != state:
            conn.execute(_UPDATE_STATE_SQL, (renamed, todo_id))  # guard: raw-sql
            rewritten += 1
    return rewritten


def migrate_sdlc_rename(conn: sqlite3.Connection) -> None:
    """Carry current artifacts and todo state forward to the renamed domain and commands."""
    if not _has_required_tables(conn):
        return
    digest_moves = _rewrite_artifacts(conn)
    rewritten_states = _rewrite_states(conn, digest_moves)
    conn.commit()
    rewritten_artifacts = sum(len(moves) for moves in digest_moves.values())
    if rewritten_artifacts or rewritten_states:
        logger.info(
            "todo sdlc rename migration complete",
            artifacts=rewritten_artifacts,
            states=rewritten_states,
        )
