"""Memory store for saving and retrieving observations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.config.subject_resolution import SubjectResolutionError, resolve_config_subject
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import create_sync_db_engine as create_engine
from teleclaude.events.envelope import EventHomeMarker
from teleclaude.events.home_owner import EventHomeOwnerMarker
from teleclaude.memory._row_conversion import row_to_memory_observation, row_to_memory_summary
from teleclaude.memory.types import CURRENT_MEMORY_PREDICATE, ObservationInput, ObservationResult
from teleclaude.services.project_catalog.ownership import (
    ProjectOwnership,
    ProjectOwnershipIndex,
    load_project_ownership_index,
)

logger = get_logger(__name__)

DEFAULT_PROJECT = "teleclaude"
_MEMORY_SUBJECT_RESOLUTION_FAILED = "memory_subject_resolution_failed"
_MEMORY_SUBJECT_BACKFILL_SETTING = "memory_observation_subject_backfill_complete"
_MEMORY_SUBJECT_BACKFILL_COMPLETE = "true"
_MEMORY_SUBJECT_BACKFILL_FAILED = "memory_observation_subject_backfill_failed"
_MEMORY_SUBJECT_BACKFILL_FINISHED = "memory_observation_subject_backfill_finished"
_MEMORY_SUBJECT_BACKFILL_ROWS_SQL = "SELECT id, project, identity_key FROM memory_observations WHERE subject IS NULL"
_MEMORY_SUBJECT_BACKFILL_UPDATE_SQL = (
    "UPDATE memory_observations SET subject = :subject, subject_owner = :subject_owner, "
    "principal = :principal WHERE id = :id AND subject IS NULL"
)


def resolve_observation_project_scope(
    project: str,
    ownership_index: ProjectOwnershipIndex | None = None,
) -> tuple[str, str]:
    """Resolve the recorded subject and owner for a named memory project."""
    index = ownership_index or load_project_ownership_index()
    ownership = index.for_slug(project)
    if ownership is not None:
        return _project_scope_tokens(ownership)

    project_path = Path(project)
    if not (project_path.is_absolute() or project_path.exists()):
        return EventHomeMarker.UNKNOWN.value, EventHomeOwnerMarker.UNRESOLVED.value
    try:
        subject = resolve_config_subject(project_path)
    except SubjectResolutionError as exc:
        logger.warning(_MEMORY_SUBJECT_RESOLUTION_FAILED, path=str(exc.declaration_path), error=str(exc))
        return EventHomeMarker.UNKNOWN.value, EventHomeOwnerMarker.UNRESOLVED.value
    if subject is None:
        return EventHomeMarker.NONE.value, EventHomeOwnerMarker.NONE.value
    if subject.kind is ConfigSubjectKind.PROJECT:
        project_ownership = index.for_path(project_path)
        if project_ownership is None:
            return subject.to_token(), EventHomeOwnerMarker.UNRESOLVED.value
        return _project_scope_tokens(project_ownership)
    return subject.to_token(), EventHomeOwnerMarker.NONE.value


def _project_scope_tokens(ownership: ProjectOwnership) -> tuple[str, str]:
    """Encode one known project and its declared owner for memory storage."""
    subject = SubjectRef(ConfigSubjectKind.PROJECT, ownership.project_slug).to_token()
    owner_identity = ownership.owner_identity()
    if owner_identity is None:
        owner = EventHomeOwnerMarker.OWNERLESS.value
    else:
        owner_kind, owner_slug = owner_identity
        owner = SubjectRef(ConfigSubjectKind(owner_kind.value), owner_slug).to_token()
    return subject, owner


def _observation_visibility(inp: ObservationInput) -> tuple[str, str, str]:
    """Use supplied provenance facts and leave every omitted fact unknown."""
    return (
        inp.subject if inp.subject is not None else EventHomeMarker.UNKNOWN.value,
        inp.subject_owner if inp.subject_owner is not None else EventHomeOwnerMarker.UNRESOLVED.value,
        inp.principal if inp.principal is not None else EventHomeMarker.UNKNOWN.value,
    )


class MemoryStore:
    """Store and retrieve memory observations."""

    async def save_observation(self, inp: ObservationInput) -> ObservationResult:
        """Save an observation via the async database."""
        project = inp.project or DEFAULT_PROJECT
        now = datetime.now(UTC)
        title = inp.title or auto_title(inp.text)
        subject, subject_owner, principal = _observation_visibility(inp)

        # Get or create manual session for this project
        session_id = await self._get_or_create_manual_session(project)

        obs = db_models.MemoryObservation(
            memory_session_id=session_id,
            project=project,
            type=inp.type.value if hasattr(inp.type, "value") else str(inp.type),
            title=title,
            subtitle=None,
            facts=json.dumps(inp.facts) if inp.facts else None,
            narrative=inp.text,
            concepts=json.dumps(inp.concepts) if inp.concepts else None,
            files_read=None,
            files_modified=None,
            created_at=now.isoformat(),
            created_at_epoch=int(now.timestamp()),
            identity_key=inp.identity_key,
            subject=subject,
            subject_owner=subject_owner,
            principal=principal,
            state=inp.state.value,
            source_session_id=inp.source_session_id,
            extraction_id=inp.extraction_id,
        )

        async with db._session() as session:
            session.add(obs)
            await session.commit()
            await session.refresh(obs)

        return ObservationResult(id=obs.id, title=title, project=project)

    def save_observation_sync(self, inp: ObservationInput, db_path: str) -> ObservationResult:
        """Save an observation via sync database access (for hook receiver)."""
        project = inp.project or DEFAULT_PROJECT
        now = datetime.now(UTC)
        title = inp.title or auto_title(inp.text)
        subject, subject_owner, principal = _observation_visibility(inp)
        session_id = self._get_or_create_manual_session_sync(project, db_path)

        engine = create_engine(db_path)
        try:
            with SqlSession(engine) as session:
                obs = db_models.MemoryObservation(
                    memory_session_id=session_id,
                    project=project,
                    type=inp.type.value if hasattr(inp.type, "value") else str(inp.type),
                    title=title,
                    subtitle=None,
                    facts=json.dumps(inp.facts) if inp.facts else None,
                    narrative=inp.text,
                    concepts=json.dumps(inp.concepts) if inp.concepts else None,
                    files_read=None,
                    files_modified=None,
                    created_at=now.isoformat(),
                    created_at_epoch=int(now.timestamp()),
                    identity_key=inp.identity_key,
                    subject=subject,
                    subject_owner=subject_owner,
                    principal=principal,
                    state=inp.state.value,
                    source_session_id=inp.source_session_id,
                    extraction_id=inp.extraction_id,
                )
                session.add(obs)
                session.commit()
                session.refresh(obs)
        finally:
            engine.dispose()

        return ObservationResult(id=obs.id, title=title, project=project)

    async def backfill_observation_subjects(self) -> None:
        """Backfill historical project scope once without guessing principals."""
        try:
            if await db.get_system_setting(_MEMORY_SUBJECT_BACKFILL_SETTING) is not None:
                return
            async with db._session() as session:
                result = await session.exec(  # type: ignore[call-overload]
                    text(_MEMORY_SUBJECT_BACKFILL_ROWS_SQL)  # guard: raw-sql
                )
                rows = result.fetchall()
            ownership_index = load_project_ownership_index()
            rows_updated = 0
            for observation_id, project, identity_key in rows:
                if identity_key is not None:
                    # Legacy identity-scoped rows lack a principal; the opaque key cannot supply it.
                    subject = EventHomeMarker.UNKNOWN.value
                    subject_owner = EventHomeOwnerMarker.UNRESOLVED.value
                else:
                    subject, subject_owner = resolve_observation_project_scope(str(project), ownership_index)
                async with db._session() as session:
                    update_result = await session.exec(  # type: ignore[call-overload]
                        text(_MEMORY_SUBJECT_BACKFILL_UPDATE_SQL).bindparams(  # guard: raw-sql
                            id=int(observation_id),
                            subject=subject,
                            subject_owner=subject_owner,
                            principal=EventHomeMarker.UNKNOWN.value,
                        )
                    )
                    await session.commit()
                    rows_updated += update_result.rowcount or 0
            await db.set_system_setting(_MEMORY_SUBJECT_BACKFILL_SETTING, _MEMORY_SUBJECT_BACKFILL_COMPLETE)
        except Exception:
            logger.exception(_MEMORY_SUBJECT_BACKFILL_FAILED)
            raise
        logger.info(_MEMORY_SUBJECT_BACKFILL_FINISHED, rows_updated=rows_updated, observations=len(rows))

    async def delete_observation(self, observation_id: int) -> bool:
        """Delete an observation by ID. Returns True if deleted, False if not found."""
        async with db._session() as session:
            result = await session.exec(  # type: ignore[call-overload]
                text(  # guard: raw-sql
                    "DELETE FROM memory_observations WHERE id = :id"
                ).bindparams(id=observation_id)
            )
            await session.commit()
            return result.rowcount > 0  # type: ignore[no-any-return]

    async def get_by_ids(self, ids: list[int], project: str | None = None) -> list[db_models.MemoryObservation]:
        """Fetch observations by IDs."""
        if not ids:
            return []
        placeholders = ", ".join([":id_" + str(i) for i in range(len(ids))])
        params = {f"id_{i}": id_val for i, id_val in enumerate(ids)}
        sql = f"SELECT * FROM memory_observations WHERE id IN ({placeholders}) AND {CURRENT_MEMORY_PREDICATE}"  # guard: raw-sql
        if project:
            sql += " AND project = :project"
            params["project"] = project  # type: ignore[assignment]
        sql += " ORDER BY created_at_epoch DESC"

        async with db._session() as session:
            result = await session.exec(  # type: ignore[call-overload]
                text(sql).bindparams(**params)  # guard: raw-sql
            )
            rows = result.fetchall()
            return [_row_to_observation(row) for row in rows]

    async def get_recent(self, project: str, limit: int = 50) -> list[db_models.MemoryObservation]:
        """Get recent observations for a project."""
        async with db._session() as session:
            result = await session.exec(  # type: ignore[call-overload]
                text(  # guard: raw-sql
                    "SELECT * FROM memory_observations WHERE project = :project AND "
                    + CURRENT_MEMORY_PREDICATE
                    + " ORDER BY created_at_epoch DESC LIMIT :limit"
                ).bindparams(project=project, limit=limit)
            )
            rows = result.fetchall()
            return [_row_to_observation(row) for row in rows]

    async def get_recent_summaries(self, project: str, limit: int = 5) -> list[db_models.MemorySummary]:
        """Get recent summaries for a project."""
        async with db._session() as session:
            result = await session.exec(  # type: ignore[call-overload]
                text(  # guard: raw-sql
                    "SELECT * FROM memory_summaries WHERE project = :project "
                    "ORDER BY created_at_epoch DESC LIMIT :limit"
                ).bindparams(project=project, limit=limit)
            )
            rows = result.fetchall()
            return [_row_to_summary(row) for row in rows]

    async def _get_or_create_manual_session(self, project: str) -> str:
        """Get or create a manual session for API-created observations."""
        async with db._session() as session:
            result = await session.exec(  # type: ignore[call-overload]
                text(  # guard: raw-sql
                    "SELECT memory_session_id FROM memory_manual_sessions WHERE project = :project"
                ).bindparams(project=project)
            )
            row = result.first()
            if row:
                return row[0] if isinstance(row, tuple) else row.memory_session_id  # type: ignore[no-any-return]

            session_id = str(uuid.uuid4())
            now_epoch = int(datetime.now(UTC).timestamp())
            ms = db_models.MemoryManualSession(
                memory_session_id=session_id,
                project=project,
                created_at_epoch=now_epoch,
            )
            session.add(ms)
            await session.commit()
            return session_id

    def _get_or_create_manual_session_sync(self, project: str, db_path: str) -> str:
        """Get or create a manual session synchronously."""
        engine = create_engine(db_path)
        try:
            with SqlSession(engine) as session:
                result = session.exec(  # type: ignore[call-overload]
                    text(  # guard: raw-sql
                        "SELECT memory_session_id FROM memory_manual_sessions WHERE project = :project"
                    ).bindparams(project=project)
                )
                row = result.first()
                if row:
                    return row[0] if isinstance(row, tuple) else str(row)

                session_id = str(uuid.uuid4())
                now_epoch = int(datetime.now(UTC).timestamp())
                ms = db_models.MemoryManualSession(
                    memory_session_id=session_id,
                    project=project,
                    created_at_epoch=now_epoch,
                )
                session.add(ms)
                session.commit()
                return session_id
        finally:
            engine.dispose()


def auto_title(text: str) -> str:
    """Extract first sentence as title, truncated to 80 chars."""
    first_line = text.strip().split("\n")[0]
    for sep in (".", "!", "?"):
        idx = first_line.find(sep)
        if 0 < idx < 80:
            return first_line[: idx + 1]
    return first_line[:80] if len(first_line) > 80 else first_line


_row_to_observation = row_to_memory_observation
_row_to_summary = row_to_memory_summary
