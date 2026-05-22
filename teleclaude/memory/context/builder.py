"""Build memory context from database for agent injection."""

from __future__ import annotations

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import create_sync_db_engine as create_engine
from teleclaude.memory._row_conversion import row_to_memory_observation, row_to_memory_summary
from teleclaude.memory.context.compiler import compile_timeline
from teleclaude.memory.context.renderer import render_context

logger = get_logger(__name__)


async def generate_context(project: str, identity_key: str | None = None) -> str:
    """Generate memory context markdown (async, for daemon/API)."""
    try:
        observations = await _get_recent_observations(project, identity_key=identity_key)
        summaries = await _get_recent_summaries(project)

        if not observations and not summaries:
            return ""

        timeline = compile_timeline(observations, summaries)
        return render_context(timeline)
    except Exception:
        logger.warning("Failed to generate memory context", project=project, exc_info=True)
        return ""


def generate_context_sync(project: str, db_path: str, identity_key: str | None = None) -> str:
    """Generate memory context markdown (sync, for hook receiver)."""
    engine = create_engine(db_path)
    try:
        with SqlSession(engine) as session:
            # Recent observations (identity-scoped)
            obs_sql = "SELECT * FROM memory_observations WHERE project = :project"
            obs_params: dict[str, str | int] = {"project": project}
            if identity_key:
                obs_sql += " AND (identity_key IS NULL OR identity_key = :identity_key)"
                obs_params["identity_key"] = identity_key
            obs_sql += " ORDER BY created_at_epoch DESC LIMIT 100"
            result = session.exec(text(obs_sql).bindparams(**obs_params))  # type: ignore[call-overload]
            obs_rows = result.fetchall()
            observations = [_row_to_observation(row) for row in obs_rows]

            # Recent summaries
            result = session.exec(  # type: ignore[call-overload]
                text(
                    "SELECT * FROM memory_summaries WHERE project = :project ORDER BY created_at_epoch DESC LIMIT 5"
                ).bindparams(project=project)
            )
            sum_rows = result.fetchall()
            summaries = [_row_to_summary(row) for row in sum_rows]

        if not observations and not summaries:
            return ""

        timeline = compile_timeline(observations, summaries)
        return render_context(timeline)
    except Exception:
        logger.warning("Failed to generate memory context (sync)", project=project, exc_info=True)
        return ""
    finally:
        engine.dispose()


async def _get_recent_observations(
    project: str, limit: int = 100, identity_key: str | None = None
) -> list[db_models.MemoryObservation]:
    """Fetch recent observations for a project, optionally scoped by identity."""
    async with db._session() as session:
        sql = "SELECT * FROM memory_observations WHERE project = :project"
        params: dict[str, str | int] = {"project": project, "limit": limit}
        if identity_key:
            sql += " AND (identity_key IS NULL OR identity_key = :identity_key)"
            params["identity_key"] = identity_key
        sql += " ORDER BY created_at_epoch DESC LIMIT :limit"
        result = await session.exec(text(sql).bindparams(**params))  # type: ignore[call-overload]
        rows = result.fetchall()
        return [_row_to_observation(row) for row in rows]


async def _get_recent_summaries(project: str, limit: int = 5) -> list[db_models.MemorySummary]:
    """Fetch recent summaries for a project."""
    async with db._session() as session:
        result = await session.exec(  # type: ignore[call-overload]
            text(
                "SELECT * FROM memory_summaries WHERE project = :project ORDER BY created_at_epoch DESC LIMIT :limit"
            ).bindparams(project=project, limit=limit)
        )
        rows = result.fetchall()
        return [_row_to_summary(row) for row in rows]


_row_to_observation = row_to_memory_observation
_row_to_summary = row_to_memory_summary
