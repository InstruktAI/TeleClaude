"""Memory store for saving and retrieving observations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from instrukt_ai_logging import get_logger
from sqlalchemy import create_engine, text  # noqa: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.memory.types import ObservationInput, ObservationResult

logger = get_logger(__name__)

DEFAULT_PROJECT = "teleclaude"


class MemoryStore:
    """Store and retrieve memory observations."""

    async def save_observation(self, inp: ObservationInput) -> ObservationResult:
        """Save an observation via the async database."""
        project = inp.project or DEFAULT_PROJECT
        now = datetime.now(timezone.utc)
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
        )

        async with db._session() as session:
            session.add(obs)
            await session.commit()
            await session.refresh(obs)

        return ObservationResult(id=obs.id, title=title, project=project)  # type: ignore[arg-type]

    def save_observation_sync(self, inp: ObservationInput, db_path: str) -> ObservationResult:
        """Save an observation via sync database access (for hook receiver)."""
        project = inp.project or DEFAULT_PROJECT
        now = datetime.now(timezone.utc)
        title = inp.title or _auto_title(inp.text)
        session_id = self._get_or_create_manual_session_sync(project, db_path)

        engine = create_engine(f"sqlite:///{db_path}")
        with SqlSession(engine) as session:
            session.exec(text("PRAGMA journal_mode = WAL"))  # noqa: raw-sql
            session.exec(text("PRAGMA busy_timeout = 5000"))  # noqa: raw-sql
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
            )
            session.add(obs)
            session.commit()
            session.refresh(obs)

        return ObservationResult(id=obs.id, title=title, project=project)  # type: ignore[arg-type]

    async def get_by_ids(self, ids: list[int], project: str | None = None) -> list[db_models.MemoryObservation]:
        """Fetch observations by IDs."""
        if not ids:
            return []
        placeholders = ", ".join([":id_" + str(i) for i in range(len(ids))])
        params = {f"id_{i}": id_val for i, id_val in enumerate(ids)}
        sql = f"SELECT * FROM memory_observations WHERE id IN ({placeholders})"  # noqa: raw-sql
        if project:
            sql += " AND project = :project"
            params["project"] = project
        sql += " ORDER BY created_at_epoch DESC"

        async with db._session() as session:
            result = await session.exec(text(sql).bindparams(**params))  # noqa: raw-sql
            rows = result.fetchall()
            return [_row_to_observation(row) for row in rows]

    async def get_recent(self, project: str, limit: int = 50) -> list[db_models.MemoryObservation]:
        """Get recent observations for a project."""
        async with db._session() as session:
            result = await session.exec(
                text(  # noqa: raw-sql
                    "SELECT * FROM memory_observations WHERE project = :project "
                    "ORDER BY created_at_epoch DESC LIMIT :limit"
                ).bindparams(project=project, limit=limit)
            )
            rows = result.fetchall()
            return [_row_to_observation(row) for row in rows]

    async def get_recent_summaries(self, project: str, limit: int = 5) -> list[db_models.MemorySummary]:
        """Get recent summaries for a project."""
        async with db._session() as session:
            result = await session.exec(
                text(  # noqa: raw-sql
                    "SELECT * FROM memory_summaries WHERE project = :project "
                    "ORDER BY created_at_epoch DESC LIMIT :limit"
                ).bindparams(project=project, limit=limit)
            )
            rows = result.fetchall()
            return [_row_to_summary(row) for row in rows]

    async def _get_or_create_manual_session(self, project: str) -> str:
        """Get or create a manual session for API-created observations."""
        async with db._session() as session:
            result = await session.exec(
                text(  # noqa: raw-sql
                    "SELECT memory_session_id FROM memory_manual_sessions WHERE project = :project"
                ).bindparams(project=project)
            )
            row = result.first()
            if row:
                return row[0] if isinstance(row, tuple) else row.memory_session_id  # type: ignore[union-attr]

            session_id = str(uuid.uuid4())
            now_epoch = int(datetime.now(timezone.utc).timestamp())
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
        engine = create_engine(f"sqlite:///{db_path}")
        with SqlSession(engine) as session:
            session.exec(text("PRAGMA journal_mode = WAL"))  # noqa: raw-sql
            session.exec(text("PRAGMA busy_timeout = 5000"))  # noqa: raw-sql
            result = session.exec(
                text(  # noqa: raw-sql
                    "SELECT memory_session_id FROM memory_manual_sessions WHERE project = :project"
                ).bindparams(project=project)
            )
            row = result.first()
            if row:
                return row[0] if isinstance(row, tuple) else str(row)

            session_id = str(uuid.uuid4())
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            ms = db_models.MemoryManualSession(
                memory_session_id=session_id,
                project=project,
                created_at_epoch=now_epoch,
            )
            session.add(ms)
            session.commit()
            return session_id


def _auto_title(text: str) -> str:
    """Extract first sentence as title, truncated to 80 chars."""
    first_line = text.strip().split("\n")[0]
    for sep in (".", "!", "?"):
        idx = first_line.find(sep)
        if 0 < idx < 80:
            return first_line[: idx + 1]
    return first_line[:80] if len(first_line) > 80 else first_line


def _row_to_observation(row: object) -> db_models.MemoryObservation:
    """Convert a raw SQL row to MemoryObservation."""
    if hasattr(row, "_mapping"):
        m = row._mapping  # type: ignore[attr-defined]
        return db_models.MemoryObservation(**dict(m))
    if isinstance(row, tuple):
        return db_models.MemoryObservation(
            id=row[0],
            memory_session_id=row[1],
            project=row[2],
            type=row[3],
            title=row[4],
            subtitle=row[5],
            facts=row[6],
            narrative=row[7],
            concepts=row[8],
            files_read=row[9],
            files_modified=row[10],
            prompt_number=row[11],
            discovery_tokens=row[12],
            created_at=row[13],
            created_at_epoch=row[14],
        )
    return row  # type: ignore[return-value]


def _row_to_summary(row: object) -> db_models.MemorySummary:
    """Convert a raw SQL row to MemorySummary."""
    if hasattr(row, "_mapping"):
        m = row._mapping  # type: ignore[attr-defined]
        return db_models.MemorySummary(**dict(m))
    if isinstance(row, tuple):
        return db_models.MemorySummary(
            id=row[0],
            memory_session_id=row[1],
            project=row[2],
            request=row[3],
            investigated=row[4],
            learned=row[5],
            completed=row[6],
            next_steps=row[7],
            created_at=row[8],
            created_at_epoch=row[9],
        )
    return row  # type: ignore[return-value]
