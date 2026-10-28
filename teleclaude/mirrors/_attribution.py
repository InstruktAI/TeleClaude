"""Durable session-level mirror attribution and its migration backfill."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude import paths as tc_paths
from teleclaude.core.db._sync import get_session_mirror_facts_by_transcript_sync
from teleclaude.core.roles import is_focused_role

from ._types import JsonValue
from .session_context import session_contexts_from_selected_facts

logger = get_logger(__name__)

_SUBJECT_FIELD = "subject"
_SUBJECT_OWNER_FIELD = "subject_owner"

_BACKFILL_MIRRORS_SQL = (
    "SELECT id, metadata, human_email, visibility, computer, project_path, command, todo, is_worker, title FROM mirrors"
)
_UPSERT_SESSION_ATTRIBUTION_SQL = """\
INSERT INTO mirror_sessions (
    session_id, principal, subject, subject_owner, project, subdir, initiator_session_id, initiator_computer,
    initiated_by_ai, job, started_at, closed_at, created_at, updated_at
) VALUES (
    :session_id, :principal, :subject, :subject_owner, :project, :subdir, :initiator_session_id, :initiator_computer,
    :initiated_by_ai, :job, :started_at, :closed_at, :created_at, :updated_at
)
ON CONFLICT(session_id) DO UPDATE SET
    principal = COALESCE(excluded.principal, mirror_sessions.principal),
    subject = COALESCE(excluded.subject, mirror_sessions.subject),
    subject_owner = COALESCE(excluded.subject_owner, mirror_sessions.subject_owner),
    project = COALESCE(excluded.project, mirror_sessions.project),
    subdir = COALESCE(excluded.subdir, mirror_sessions.subdir),
    initiator_session_id = COALESCE(excluded.initiator_session_id, mirror_sessions.initiator_session_id),
    initiator_computer = COALESCE(excluded.initiator_computer, mirror_sessions.initiator_computer),
    initiated_by_ai = COALESCE(excluded.initiated_by_ai, mirror_sessions.initiated_by_ai),
    job = COALESCE(excluded.job, mirror_sessions.job),
    started_at = COALESCE(excluded.started_at, mirror_sessions.started_at),
    closed_at = COALESCE(excluded.closed_at, mirror_sessions.closed_at),
    updated_at = excluded.updated_at
"""
_SELECT_SESSION_ATTRIBUTION_ID_SQL = "SELECT id FROM mirror_sessions WHERE session_id = :session_id"
_BACKFILL_MIRROR_ATTRIBUTION_SQL = """\
UPDATE mirrors SET
    session = :session,
    position = :position,
    human_email = COALESCE(NULLIF(human_email, ''), :human_email),
    visibility = COALESCE(NULLIF(visibility, ''), :visibility),
    computer = COALESCE(NULLIF(computer, ''), :computer),
    project_path = COALESCE(NULLIF(project_path, ''), :project_path),
    command = COALESCE(NULLIF(command, ''), :command),
    todo = COALESCE(NULLIF(todo, ''), :todo),
    title = COALESCE(NULLIF(title, ''), :title),
    is_worker = :is_worker,
    metadata = :metadata
WHERE id = :mirror_id
"""
_BACKFILL_COMPLETE_EVENT = "mirror.session_attribution.backfill_complete"


class MirrorBackfillValues(TypedDict):
    """Bound values used when migrating one mirror's attribution."""

    session: int
    position: int | None
    human_email: str | None
    visibility: str | None
    computer: str
    project_path: str
    command: str | None
    todo: str | None
    title: str | None
    is_worker: int
    metadata: str
    mirror_id: int


@dataclass(frozen=True)
class MirrorSessionAttribution:
    """Session-level facts shared by every transcript mirror."""

    session_id: str
    principal: str | None
    subject: str | None
    subject_owner: str | None
    project: str | None
    subdir: str | None
    initiator_session_id: str | None
    initiator_computer: str | None
    initiated_by_ai: bool | None
    job: str | None
    started_at: str | None
    closed_at: str | None


def upsert_session_attribution(conn: sqlite3.Connection, attribution: MirrorSessionAttribution, now: str) -> int:
    """Upsert session facts while retaining every fact the caller lacks."""
    conn.execute(  # guard: raw-sql - migration-owned session attribution row.
        _UPSERT_SESSION_ATTRIBUTION_SQL,
        {
            "session_id": attribution.session_id,
            "principal": attribution.principal,
            _SUBJECT_FIELD: attribution.subject,
            _SUBJECT_OWNER_FIELD: attribution.subject_owner,
            "project": attribution.project,
            "subdir": attribution.subdir,
            "initiator_session_id": attribution.initiator_session_id,
            "initiator_computer": attribution.initiator_computer,
            "initiated_by_ai": None if attribution.initiated_by_ai is None else int(attribution.initiated_by_ai),
            "job": attribution.job,
            "started_at": attribution.started_at,
            "closed_at": attribution.closed_at,
            "created_at": attribution.started_at or now,
            "updated_at": now,
        },
    )
    row = conn.execute(  # guard: raw-sql - resolve the id just upserted in this transaction.
        _SELECT_SESSION_ATTRIBUTION_ID_SQL,
        {"session_id": attribution.session_id},
    ).fetchone()
    if row is None:
        raise RuntimeError("Session attribution upsert did not produce a row")
    return int(row[0])


def backfill_session_attributions(conn: sqlite3.Connection, _store_path: str, snapshot_path: Path) -> None:
    """Link retained mirrors to session records and restore facts erased by earlier writes."""
    selected_facts = get_session_mirror_facts_by_transcript_sync(str(tc_paths.MAIN_DB_PATH))
    contexts = session_contexts_from_selected_facts(selected_facts)
    rows = conn.execute(_BACKFILL_MIRRORS_SQL).fetchall()  # guard: raw-sql - migration-owned mirror scan.
    attributed = 0
    unattributed = 0
    facts_restored = 0
    session_ids: set[str] = set()
    for row in rows:
        mirror_id, raw_metadata, human_email, visibility, computer, project_path, command, todo, is_worker, title = row
        metadata = _metadata(raw_metadata)
        mirror_transcript_path = metadata.get("transcript_path")
        context = contexts.get(mirror_transcript_path) if isinstance(mirror_transcript_path, str) else None
        if context is None:
            unattributed += 1
            continue
        session_ids.add(context.session_id)
        attribution = MirrorSessionAttribution(
            session_id=context.session_id,
            principal=context.principal,
            subject=context.subject,
            subject_owner=context.subject_owner,
            project=context.project,
            subdir=context.subdir,
            initiator_session_id=context.initiator_session_id,
            initiator_computer=context.initiator_computer,
            initiated_by_ai=context.initiated_by_ai,
            job=context.job,
            started_at=context.created_at,
            closed_at=context.closed_at,
        )
        attribution_id = upsert_session_attribution(conn, attribution, datetime.now(UTC).isoformat())
        if context.last_input_origin:
            metadata["origin_channel"] = context.last_input_origin
        metadata.update(context.channel_identifiers)
        values: MirrorBackfillValues = {
            "session": attribution_id,
            "position": context.position,
            "human_email": context.human_email,
            "visibility": context.visibility,
            "computer": context.computer,
            "project_path": context.project_path,
            "command": context.command,
            "todo": context.todo,
            "title": context.title,
            "is_worker": int(is_focused_role(context.role) or bool(is_worker)),
            "metadata": json.dumps(metadata, sort_keys=True),
            "mirror_id": mirror_id,
        }
        old_values = (human_email, visibility, computer, project_path, command, todo, is_worker, title)
        new_values = (
            values["human_email"],
            values["visibility"],
            values["computer"],
            values["project_path"],
            values["command"],
            values["todo"],
            values["is_worker"],
            values["title"],
        )
        facts_restored += sum(
            1 for old, new in zip(old_values, new_values, strict=True) if old in (None, "") and new not in (None, "")
        )
        if is_worker is not None and int(is_worker) != values["is_worker"]:
            facts_restored += 1
        conn.execute(_BACKFILL_MIRROR_ATTRIBUTION_SQL, values)  # guard: raw-sql - migrate a single mirror row.
        attributed += 1

    logger.info(
        _BACKFILL_COMPLETE_EVENT,
        mirrors_total=len(rows),
        mirrors_attributed=attributed,
        mirrors_unattributed=unattributed,
        sessions=len(session_ids),
        facts_restored=facts_restored,
        snapshot_path=str(snapshot_path),
    )


def _metadata(value: object) -> dict[str, JsonValue]:
    """Read transcript metadata needed by the migration without changing its shape."""
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, JsonValue], parsed) if isinstance(parsed, dict) else {}
