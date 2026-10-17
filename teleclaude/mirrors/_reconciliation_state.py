"""Read model for transcript reconciliation and stale mirror handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from .store import (
    OrphanMirror,
    _get_ro_engine,
    _int_value,
    _is_missing_table_error,
    _optional_int,
    _optional_str,
)

_SELECT_SOURCE_FILE_STATE_SQL = """\
SELECT mirror_sessions.session_id AS session_id, mirror_sources.source_identity AS source_identity,
    mirror_sources.transcript_path AS transcript_path, mirror_sources.file_size AS file_size,
    mirror_sources.file_mtime_ns AS file_mtime_ns, mirror_sources.derivation_version AS derivation_version
FROM mirror_sources
JOIN mirrors ON mirrors.id = mirror_sources.mirror
JOIN mirror_sessions ON mirror_sessions.id = mirrors.session
WHERE mirror_sources.transcript_path IS NOT NULL AND mirror_sources.transcript_path <> ''
"""
_SELECT_STALE_SOURCES_SQL = """\
SELECT id AS source_id, source_identity, agent, transcript_path
FROM mirror_sources
WHERE derivation_version < :derivation_version
  AND id NOT IN (SELECT source FROM mirror_unreprojectable_sources)
"""


@dataclass(frozen=True)
class MirrorTranscriptState:
    """Session-owned source observation consulted during reconciliation skip checks."""

    session_id: str
    source_identity: str
    transcript_path: str
    file_size: int | None
    file_mtime_ns: str | None
    derivation_version: int


@dataclass(frozen=True)
class MirrorSessionSourceKey:
    """A transcript source observation owned by exactly one TeleClaude session."""

    session_id: str
    source_identity: str


def get_mirror_state_by_session_source(
    db: str | Path | None = None,
) -> dict[MirrorSessionSourceKey, MirrorTranscriptState]:
    """Return source state keyed by its owning TeleClaude session and source identity."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(_SELECT_SOURCE_FILE_STATE_SQL)).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return {}
        raise

    return {
        MirrorSessionSourceKey(str(row["session_id"]), str(row["source_identity"])): MirrorTranscriptState(
            session_id=str(row["session_id"]),
            source_identity=str(row["source_identity"]),
            transcript_path=str(row["transcript_path"]),
            file_size=_optional_int(row["file_size"]),
            file_mtime_ns=_optional_str(row["file_mtime_ns"]),
            derivation_version=_int_value(row["derivation_version"]),
        )
        for row in rows
    }


def get_stale_mirrors(derivation_version: int, *, db: str | Path | None = None) -> list[OrphanMirror]:
    """Return sources whose derivation_version is older than the given version."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = (
                conn.execute(text(_SELECT_STALE_SOURCES_SQL), {"derivation_version": derivation_version})
                .mappings()
                .all()
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise

    return [
        OrphanMirror(
            source_id=_int_value(row["source_id"]),
            source_identity=str(row["source_identity"]),
            agent=str(row["agent"] or ""),
            transcript_path=_optional_str(row["transcript_path"]),
        )
        for row in rows
    ]
