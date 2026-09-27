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
    _optional_str,
    _parse_metadata,
)


@dataclass(frozen=True)
class MirrorTranscriptState:
    """Per-transcript mirror state consulted during reconciliation skip checks."""

    updated_at: str
    derivation_version: int


def get_mirror_state_by_transcript(db: str | Path | None = None) -> dict[str, MirrorTranscriptState]:
    """Return transcript-path keyed mirror state for reconciliation."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = conn.execute(text("SELECT metadata, updated_at, derivation_version FROM mirrors")).mappings().all()
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return {}
        raise

    state: dict[str, MirrorTranscriptState] = {}
    for row in rows:
        metadata = _parse_metadata(row.get("metadata"))
        transcript_path = metadata.get("transcript_path")
        updated_at = _optional_str(row.get("updated_at"))
        if not isinstance(transcript_path, str) or not transcript_path or updated_at is None:
            continue
        state[transcript_path] = MirrorTranscriptState(
            updated_at=updated_at,
            derivation_version=_int_value(row.get("derivation_version")),
        )
    return state


def get_stale_mirrors(derivation_version: int, *, db: str | Path | None = None) -> list[OrphanMirror]:
    """Return mirrors whose derivation_version is older than the given version."""
    try:
        with _get_ro_engine(db).connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """\
                        SELECT source_identity, agent, metadata
                        FROM mirrors
                        WHERE derivation_version < :derivation_version
                          AND source_identity NOT IN (
                              SELECT source_identity FROM mirror_unreprojectable_sources
                          )
                        """
                    ),
                    {"derivation_version": derivation_version},
                )
                .mappings()
                .all()
            )
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return []
        raise

    stale: list[OrphanMirror] = []
    for row in rows:
        source_identity = _optional_str(row.get("source_identity"))
        if source_identity is None:
            continue
        metadata = _parse_metadata(row.get("metadata"))
        transcript_path = metadata.get("transcript_path")
        stale.append(
            OrphanMirror(
                source_identity=source_identity,
                agent=str(row.get("agent") or ""),
                transcript_path=transcript_path if isinstance(transcript_path, str) and transcript_path else None,
            )
        )
    return stale
