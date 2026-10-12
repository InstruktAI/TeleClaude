"""Give retained history a TeleClaude identity: restore pruned sessions and archive what no session claims.

Session records belong to agent runtime. This module decides which mirrored history lacks one and supplies
only the facts the mirror recorded; the adopter it is given creates the retained, non-running record.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from instrukt_ai_logging import get_logger
from sqlalchemy import Connection, text
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from teleclaude.config.machine import config
from teleclaude.core.agents import AgentName
from teleclaude.core.db._session_retention import ArchiveSessionRecord
from teleclaude.core.db._sync import existing_session_ids_sync
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.utils.transcript_discovery import build_source_identity, extract_project, extract_session_id

from ._attribution import MirrorSessionAttribution
from .conversations import attribute_mirror
from .store import _get_ro_engine, _is_missing_table_error, _optional_str

logger = get_logger(__name__)

ARCHIVE_ADOPTED_EVENT = "mirror.archive_adopted"
ARCHIVE_ADOPTION_FAILED_EVENT = "mirror.archive_adoption_failed"

type ArchiveAdopter = Callable[[ArchiveSessionRecord], str]
"""Creates the retained record for history and returns its TeleClaude session id; blocks until it is stored."""

_SELECT_ATTRIBUTIONS_SQL = """\
SELECT mirror_sessions.session_id, mirror_sessions.principal, mirror_sessions.subject,
    mirror_sessions.subject_owner, mirror_sessions.subdir, mirror_sessions.started_at, mirror_sessions.closed_at,
    mirrors.id AS mirror_id, mirrors.computer, mirrors.project_path, mirrors.title, mirrors.human_email
FROM mirror_sessions JOIN mirrors ON mirrors.session = mirror_sessions.id
"""
_SELECT_UNATTRIBUTED_SQL = """\
SELECT id AS mirror_id, computer, project_path, title, timestamp_start, timestamp_end FROM mirrors
WHERE session IS NULL
"""
_SELECT_SOURCES_SQL = """\
SELECT source_identity, native_session_id, agent, transcript_path FROM mirror_sources
WHERE mirror = :mirror ORDER BY position, id
"""


_ADOPTION_TIMEOUT_S = 30.0


class ArchiveRecordStore(Protocol):
    """Agent runtime's published command for retaining a non-running session record."""

    def adopt_archive_session(self, record: ArchiveSessionRecord) -> Awaitable[str]: ...


def threadsafe_archive_adopter(store: ArchiveRecordStore, loop: asyncio.AbstractEventLoop) -> ArchiveAdopter:
    """An adopter for the mirror worker's thread that runs the record command on the daemon's event loop."""

    def adopt(record: ArchiveSessionRecord) -> str:
        future = asyncio.run_coroutine_threadsafe(_await(store.adopt_archive_session(record)), loop)
        return future.result(timeout=_ADOPTION_TIMEOUT_S)

    return adopt


async def _await(awaitable: Awaitable[str]) -> str:
    return await awaitable


@dataclass(frozen=True)
class ArchiveAdoptionResult:
    """What one adoption pass retained."""

    restored: int
    attributed: int
    failed: int


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def adopt_unclaimed_transcript(path: Path, agent: AgentName, adopter: ArchiveAdopter) -> str:
    """Retain a discovered transcript no session claims as an archive session; its TeleClaude id.

    The transcript's own facts are all the record carries: its native identity, runtime, working project and the
    time it was last written. No person or authority is inferred.
    """
    observed = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return adopter(
        ArchiveSessionRecord(
            source_identity=build_source_identity(path, agent),
            computer_name=config.computer.name,
            native_session_id=str(extract_session_id(path, agent)),
            native_log_file=str(path),
            active_agent=agent.value,
            project_path=extract_project(path, agent) or None,
            started_at=observed,
            closed_at=observed,
        )
    )


def _sources(conn: Connection, mirror_id: int) -> list[dict[str, str | None]]:
    rows = conn.execute(text(_SELECT_SOURCES_SQL), {"mirror": mirror_id}).mappings().all()
    return [
        {
            "source_identity": str(row["source_identity"]),
            "native_session_id": _optional_str(row["native_session_id"]),
            "agent": str(row["agent"]),
            "transcript_path": _optional_str(row["transcript_path"]),
        }
        for row in rows
    ]


def _record(
    session_id: str | None,
    sources: list[dict[str, str | None]],
    *,
    computer: str | None,
    project_path: str | None,
    title: str | None,
    principal: str | None = None,
    human_email: str | None = None,
    subject: str | None = None,
    subject_owner: str | None = None,
    subdir: str | None = None,
    started_at: datetime | None = None,
    closed_at: datetime | None = None,
) -> ArchiveSessionRecord:
    """The archive record the mirror's recorded facts describe; the newest source is the record's current transcript."""
    newest = sources[-1]
    return ArchiveSessionRecord(
        source_identity=str(newest["source_identity"]),
        computer_name=computer or config.computer.name,
        session_id=session_id,
        native_session_id=newest["native_session_id"],
        native_log_file=newest["transcript_path"],
        transcript_files=tuple(str(source["transcript_path"]) for source in sources[:-1] if source["transcript_path"]),
        active_agent=newest["agent"],
        project_path=project_path,
        subdir=subdir,
        title=title,
        principal=principal,
        human_email=human_email,
        config_subject=subject,
        subject_owner=subject_owner,
        started_at=started_at,
        closed_at=closed_at,
    )


def adopt_retained_history(adopter: ArchiveAdopter, db: str | Path | None = None) -> ArchiveAdoptionResult:
    """Restore the identity of every pruned session and archive every unattributed mirror, once each.

    A mirror attributed to a session whose record was pruned regains that session id; a mirror no session
    ever claimed receives a new archive session and is attributed to it. Both are idempotent.
    """
    restored = attributed = failed = 0
    try:
        with _get_ro_engine(db).connect() as conn:
            attributions = conn.execute(text(_SELECT_ATTRIBUTIONS_SQL)).mappings().all()
            unattributed = conn.execute(text(_SELECT_UNATTRIBUTED_SQL)).mappings().all()
            attribution_sources = {int(row["mirror_id"]): _sources(conn, int(row["mirror_id"])) for row in attributions}
            unattributed_sources = {
                int(row["mirror_id"]): _sources(conn, int(row["mirror_id"])) for row in unattributed
            }
    except SqlAlchemyOperationalError as exc:
        if _is_missing_table_error(exc):
            return ArchiveAdoptionResult(0, 0, 0)
        raise
    present = existing_session_ids_sync(str(MAIN_DB_PATH), [str(row["session_id"]) for row in attributions])
    for row in attributions:
        session_id = str(row["session_id"])
        sources = attribution_sources[int(row["mirror_id"])]
        if session_id in present or not sources:
            continue
        try:
            adopter(
                _record(
                    session_id,
                    sources,
                    computer=_optional_str(row["computer"]),
                    project_path=_optional_str(row["project_path"]),
                    title=_optional_str(row["title"]),
                    principal=_optional_str(row["principal"]),
                    human_email=_optional_str(row["human_email"]),
                    subject=_optional_str(row["subject"]),
                    subject_owner=_optional_str(row["subject_owner"]),
                    subdir=_optional_str(row["subdir"]),
                    started_at=_parse_time(row["started_at"]),
                    closed_at=_parse_time(row["closed_at"]),
                )
            )
            restored += 1
            logger.info(ARCHIVE_ADOPTED_EVENT, session_id=session_id, restored=True)
        except Exception as exc:
            failed += 1
            logger.error(ARCHIVE_ADOPTION_FAILED_EVENT, session_id=session_id, error=str(exc), exc_info=True)
    for row in unattributed:
        mirror_id = int(row["mirror_id"])
        sources = unattributed_sources[mirror_id]
        if not sources:
            continue
        try:
            session_id = adopter(
                _record(
                    None,
                    sources,
                    computer=_optional_str(row["computer"]),
                    project_path=_optional_str(row["project_path"]),
                    title=_optional_str(row["title"]),
                    started_at=_parse_time(row["timestamp_start"]),
                    closed_at=_parse_time(row["timestamp_end"]),
                )
            )
            attribute_mirror(
                mirror_id,
                MirrorSessionAttribution(
                    session_id=session_id,
                    principal=None,
                    subject=None,
                    subject_owner=None,
                    project=None,
                    subdir=None,
                    initiator_session_id=None,
                    initiator_computer=None,
                    initiated_by_ai=None,
                    job=None,
                    started_at=None,
                    closed_at=None,
                ),
                db=db,
            )
            attributed += 1
            logger.info(ARCHIVE_ADOPTED_EVENT, session_id=session_id, restored=False)
        except Exception as exc:
            failed += 1
            logger.error(ARCHIVE_ADOPTION_FAILED_EVENT, mirror_id=mirror_id, error=str(exc), exc_info=True)
    return ArchiveAdoptionResult(restored=restored, attributed=attributed, failed=failed)
