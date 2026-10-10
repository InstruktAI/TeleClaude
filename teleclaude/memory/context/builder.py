"""Build memory context from database for agent injection."""

from __future__ import annotations

from instrukt_ai_logging import get_logger
from sqlalchemy import text  # guard: raw-sql - Sync memory access
from sqlmodel import Session as SqlSession

from teleclaude.core.db.connection_factory import create_sync_db_engine as create_engine
from teleclaude.identity_reach import Reach
from teleclaude.memory._row_conversion import row_to_memory_observation, row_to_memory_summary
from teleclaude.memory.context.compiler import compile_timeline
from teleclaude.memory.context.renderer import render_context
from teleclaude.memory.store import resolve_observation_project_scope
from teleclaude.memory.types import CURRENT_MEMORY_PREDICATE

logger = get_logger(__name__)
_MEMORY_SUBJECT_COLUMN = "memory_observations.subject"
_MEMORY_SUBJECT_OWNER_COLUMN = "memory_observations.subject_owner"
_MEMORY_PRINCIPAL_COLUMN = "memory_observations.principal"
_REACH_FILTER_TEMPLATE = " AND ({predicate})"
_OBSERVATIONS_SQL = f"SELECT * FROM memory_observations WHERE project = :project AND {CURRENT_MEMORY_PREDICATE}"
_OBSERVATIONS_ORDER_LIMIT_SQL = " ORDER BY created_at_epoch DESC LIMIT 100"
_SUMMARIES_SQL = "SELECT * FROM memory_summaries WHERE project = :project ORDER BY created_at_epoch DESC LIMIT 5"


def generate_context_sync(
    project: str,
    db_path: str,
    reach: Reach,
    identity_key: str | None = None,
) -> str:
    """Generate memory context markdown (sync, for hook receiver) for what the given reach admits."""
    engine = create_engine(db_path)
    try:
        with SqlSession(engine) as session:
            # Recent observations use identity reach plus the existing opaque identity-key filter.
            obs_sql = _OBSERVATIONS_SQL
            obs_params: dict[str, str | int] = {"project": project}
            if identity_key:
                obs_sql += " AND (identity_key IS NULL OR identity_key = :identity_key)"
                obs_params["identity_key"] = identity_key
            predicate, reach_params = _reach_predicate(reach)
            obs_sql += _REACH_FILTER_TEMPLATE.format(predicate=predicate)
            obs_params.update(reach_params)
            obs_sql += _OBSERVATIONS_ORDER_LIMIT_SQL
            result = session.exec(text(obs_sql).bindparams(**obs_params))  # type: ignore[call-overload]  # guard: raw-sql
            obs_rows = result.fetchall()
            observations = [_row_to_observation(row) for row in obs_rows]

            project_subject, project_owner = resolve_observation_project_scope(project)
            if reach.admits(project_subject, project_owner, None):
                result = session.exec(  # type: ignore[call-overload]
                    text(_SUMMARIES_SQL).bindparams(project=project)  # guard: raw-sql
                )
                sum_rows = result.fetchall()
                summaries = [_row_to_summary(row) for row in sum_rows]
            else:
                summaries = []

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


def _reach_predicate(reach: Reach) -> tuple[str, dict[str, str]]:
    """Build the shared observation predicate for synchronous context reads."""
    return reach.sql_predicate(
        subject_col=_MEMORY_SUBJECT_COLUMN,
        owner_col=_MEMORY_SUBJECT_OWNER_COLUMN,
        principal_col=_MEMORY_PRINCIPAL_COLUMN,
    )
