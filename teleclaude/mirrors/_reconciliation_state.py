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
SELECT transcript_path, file_size, file_mtime_ns, derivation_version
FROM mirror_sources
WHERE transcript_path IS NOT NULL AND transcript_path <> ''
"""
_SELECT_STALE_SOURCES_SQL = """\
SELECT source_identity, agent, transcript_path
FROM mirror_sources
WHERE derivation_version < :derivation_version
  AND source_identity NOT IN (SELECT source_identity FROM mirror_unreprojectable_sources)
"""


@dataclass(frozen=True)
class MirrorTranscriptState:
    """Per-transcript source state consulted during reconciliation skip checks."""

    file_size: int | None
    file_mtime_ns: str | None
    derivation_version: int


def get_mirror_state_by_transcript(db: str | Path | None = None) -> dict[str, MirrorTranscriptState]:
    """Return transcript-path keyed source state for reconciliation."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text(_SELECT_SOURCE_FILE_STATE_SQL)).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return {}
        raise

    return {
        str(row["transcript_path"]): MirrorTranscriptState(
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
            source_identity=str(row["source_identity"]),
            agent=str(row["agent"] or ""),
            transcript_path=_optional_str(row["transcript_path"]),
        )
        for row in rows
    ]
