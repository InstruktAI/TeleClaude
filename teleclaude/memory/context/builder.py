"""Build memory context from database for agent injection."""

from __future__ import annotations

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core.db.connection_factory import create_sync_db_engine as create_engine
from teleclaude.memory._row_conversion import row_to_memory_observation, row_to_memory_summary
from teleclaude.memory.context.compiler import compile_timeline
from teleclaude.memory.context.renderer import render_context

logger = get_logger(__name__)


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
            result = session.exec(text(obs_sql).bindparams(**obs_params))  # type: ignore[call-overload]  # guard: raw-sql
            obs_rows = result.fetchall()
            observations = [_row_to_observation(row) for row in obs_rows]

            # Recent summaries
            result = session.exec(  # type: ignore[call-overload]
                text(  # guard: raw-sql
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
        # Best-effort context injection: any failure (DB, render, schema drift)
        # must return "" rather than propagate, or the SessionStart hook crashes
        # and the entire session bootstrap fails. Log and degrade.
        logger.warning("Failed to generate memory context (sync)", project=project, exc_info=True)
        return ""
    finally:
        engine.dispose()


_row_to_observation = row_to_memory_observation
_row_to_summary = row_to_memory_summary
