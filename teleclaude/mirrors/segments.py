"""Retrieval of one native source's segment of a conversation mirror, addressed by the source's native id."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude.identity_reach import Reach

from ._types import JsonValue
from .conversations import render_source
from .store import (
    _SHRINK_REFUSED_AT_FIELD,
    _SQL_AND_SEPARATOR,
    MirrorRecord,
    _apply_access_filter,
    _get_ro_engine,
    _is_missing_table_error,
    _mirror_record_from_row,
)

_TRANSCRIPT_PATH_FIELD = "transcript_path"
_GET_SEGMENT_SQL_TEMPLATE = f"""
    SELECT mirror_sources.id AS id, mirror_sources.archival_text AS archival_text,
        mirror_sources.native_session_id AS native_session_id, mirror_sessions.session_id AS session_id,
        mirrors.session AS session, mirror_sources.position AS position,
        mirror_sources.source_identity AS source_identity, mirrors.computer AS computer,
        mirror_sources.agent AS agent, mirrors.project_path AS project_path, mirrors.title AS title,
        mirror_sources.timestamp_start AS timestamp_start, mirror_sources.timestamp_end AS timestamp_end,
        '' AS conversation_text, mirror_sources.message_count AS message_count, mirrors.metadata AS metadata,
        mirror_sources.created_at AS created_at, mirror_sources.updated_at AS updated_at,
        mirrors.summary AS summary, mirrors.human_email AS human_email, mirrors.visibility AS visibility,
        mirrors.command AS command, mirrors.todo AS todo, mirrors.is_worker AS is_worker,
        mirror_sources.derivation_version AS derivation_version, mirrors.covered_at AS covered_at,
        mirrors.coverage_ready AS coverage_ready, mirror_sources.transcript_path AS source_transcript_path,
        (SELECT mirror_shrink_refusals.{_SHRINK_REFUSED_AT_FIELD} FROM mirror_shrink_refusals
            WHERE mirror_shrink_refusals.source_identity = mirror_sources.source_identity)
            AS {_SHRINK_REFUSED_AT_FIELD}
    FROM mirror_sources
    JOIN mirrors ON mirrors.id = mirror_sources.mirror
    LEFT JOIN mirror_sessions ON mirror_sessions.id = mirrors.session
    WHERE {{where_clause}} ORDER BY mirror_sources.updated_at DESC LIMIT 1
"""
_SOURCE_ID_COLUMN = "id"
_ARCHIVAL_TEXT_COLUMN = "archival_text"
_NATIVE_ID_CLAUSE = "mirror_sources.native_session_id = :native_session_id"
_COMPUTER_CLAUSE = "mirrors.computer = :computer"


def get_source_segment(
    native_session_id: str,
    *,
    reach: Reach,
    db: str | Path | None = None,
    computer: str | None = None,
) -> MirrorRecord | None:
    """Fetch the segment one native source holds of its conversation, within the caller's history reach.

    The record states the conversation's identity, and its text, counts and provenance are the source's own.
    """
    clauses = [_NATIVE_ID_CLAUSE]
    params: dict[str, object] = {"native_session_id": native_session_id}  # guard: loose-dict - SQL bind params vary.
    if computer:
        clauses.append(_COMPUTER_CLAUSE)
        params["computer"] = computer
    _apply_access_filter(clauses, params, reach)
    sql = _GET_SEGMENT_SQL_TEMPLATE.format(where_clause=_SQL_AND_SEPARATOR.join(clauses))
    try:
        with _get_ro_engine(db).connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
            if row is None:
                return None
            segment_text = render_source(conn, row[_SOURCE_ID_COLUMN], row[_ARCHIVAL_TEXT_COLUMN])
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return None
        raise
    record = _mirror_record_from_row(row)
    source_path = row["source_transcript_path"]
    metadata: dict[str, JsonValue] = dict(record.metadata)
    if isinstance(source_path, str) and source_path:
        metadata[_TRANSCRIPT_PATH_FIELD] = source_path
    return replace(record, conversation_text=segment_text, metadata=metadata)
