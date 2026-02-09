"""Build memory context from database for agent injection."""

from __future__ import annotations

from instrukt_ai_logging import get_logger
from sqlalchemy import create_engine, text  # noqa: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.memory.context.compiler import compile_timeline, filter_by_recency
from teleclaude.memory.context.renderer import render_context

logger = get_logger(__name__)


async def generate_context(project: str) -> str:
    """Generate memory context markdown (async, for daemon/API)."""
    try:
        observations = await _get_recent_observations(project)
        summaries = await _get_recent_summaries(project)

        if not observations and not summaries:
            return ""

        timeline = compile_timeline(observations, summaries)
        timeline = filter_by_recency(timeline)
        return render_context(timeline)
    except Exception:
        logger.warning("Failed to generate memory context", project=project, exc_info=True)
        return ""


def generate_context_sync(project: str, db_path: str) -> str:
    """Generate memory context markdown (sync, for hook receiver)."""
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        with SqlSession(engine) as session:
            session.exec(text("PRAGMA journal_mode = WAL"))
            session.exec(text("PRAGMA busy_timeout = 5000"))

            # Recent observations
            result = session.exec(
                text(
                    "SELECT * FROM memory_observations WHERE project = :project ORDER BY created_at_epoch DESC LIMIT 50"
                ).bindparams(project=project)
            )
            obs_rows = result.fetchall()
            observations = [_row_to_observation(row) for row in obs_rows]

            # Recent summaries
            result = session.exec(
                text(
                    "SELECT * FROM memory_summaries WHERE project = :project ORDER BY created_at_epoch DESC LIMIT 5"
                ).bindparams(project=project)
            )
            sum_rows = result.fetchall()
            summaries = [_row_to_summary(row) for row in sum_rows]

        if not observations and not summaries:
            return ""

        timeline = compile_timeline(observations, summaries)
        timeline = filter_by_recency(timeline)
        return render_context(timeline)
    except Exception:
        logger.warning("Failed to generate memory context (sync)", project=project, exc_info=True)
        return ""


async def _get_recent_observations(project: str, limit: int = 50) -> list[db_models.MemoryObservation]:
    """Fetch recent observations for a project."""
    async with db._session() as session:
        result = await session.exec(
            text(
                "SELECT * FROM memory_observations WHERE project = :project ORDER BY created_at_epoch DESC LIMIT :limit"
            ).bindparams(project=project, limit=limit)
        )
        rows = result.fetchall()
        return [_row_to_observation(row) for row in rows]


async def _get_recent_summaries(project: str, limit: int = 5) -> list[db_models.MemorySummary]:
    """Fetch recent summaries for a project."""
    async with db._session() as session:
        result = await session.exec(
            text(
                "SELECT * FROM memory_summaries WHERE project = :project ORDER BY created_at_epoch DESC LIMIT :limit"
            ).bindparams(project=project, limit=limit)
        )
        rows = result.fetchall()
        return [_row_to_summary(row) for row in rows]


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
