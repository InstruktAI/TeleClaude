"""Memory store for saving and retrieving observations."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import create_sync_db_engine as create_engine
from teleclaude.memory._row_conversion import row_to_memory_observation, row_to_memory_summary
from teleclaude.memory.types import ObservationInput, ObservationResult

logger = get_logger(__name__)

DEFAULT_PROJECT = "teleclaude"


class MemoryStore:
    """Store and retrieve memory observations."""

    async def save_observation(self, inp: ObservationInput) -> ObservationResult:
        """Save an observation via the async database."""
        project = inp.project or DEFAULT_PROJECT
        now = datetime.now(UTC)
        title = inp.title or _auto_title(inp.text)

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
        title = inp.title or _auto_title(inp.text)
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
                )
                session.add(obs)
                session.commit()
                session.refresh(obs)
        finally:
            engine.dispose()

        return ObservationResult(id=obs.id, title=title, project=project)

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
        sql = f"SELECT * FROM memory_observations WHERE id IN ({placeholders})"  # guard: raw-sql
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
                    "SELECT * FROM memory_observations WHERE project = :project "
                    "ORDER BY created_at_epoch DESC LIMIT :limit"
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


def _auto_title(text: str) -> str:
    """Extract first sentence as title, truncated to 80 chars."""
    first_line = text.strip().split("\n")[0]
    for sep in (".", "!", "?"):
        idx = first_line.find(sep)
        if 0 < idx < 80:
            return first_line[: idx + 1]
    return first_line[:80] if len(first_line) > 80 else first_line


_row_to_observation = row_to_memory_observation
_row_to_summary = row_to_memory_summary
