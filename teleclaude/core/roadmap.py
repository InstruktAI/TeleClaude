"""Core roadmap assembly logic.

DB-backed roadmap assembly for CLI, API, and TUI.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO

logger = get_logger(__name__)

RECENTLY_DELIVERED_HOURS = 72

# v2 current values that indicate prepare-phase territory
_PREPARE_CURRENT_VALUES: dict[str, str] = {
    "input_assessment": "input_assessment",
    "triangulation": "triangulation",
    "requirements_review": "requirements_review",
    "test_spec_build": "test_spec_build",
    "test_spec_review": "test_spec_review",
    "plan_drafting": "plan_drafting",
    "plan_review": "plan_review",
    "gate": "gate",
    "grounding_check": "grounding_check",
    "re_grounding": "re_grounding",
    "prepared": "prepared",
    "blocked": "blocked",
}


def _derive_prepare_phase_from_current(current: str | None) -> str | None:
    """Derive prepare_phase from v2 current field for display."""
    if not current:
        return None
    return _PREPARE_CURRENT_VALUES.get(current)


def _non_empty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def assemble_roadmap_from_db(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    project_path: str,
    include_icebox: bool = False,
    icebox_only: bool = False,
    include_delivered: bool = False,
    delivered_only: bool = False,
) -> list[TodoDTO]:
    """Assemble roadmap from todos.db using sync methods.

    Reads state, roadmap entries, and deps from the SQLite database.
    """
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    started_at = time.perf_counter()
    db = TodosDb(str(Path(project_path) / ".teleclaude" / "todos.db"))
    init_started_at = time.perf_counter()
    db.initialize_sync()
    init_dt = time.perf_counter() - init_started_at

    conn_open_started_at = time.perf_counter()
    conn = db._sync_conn()  # pylint: disable=protected-access
    conn_open_dt = time.perf_counter() - conn_open_started_at
    try:
        # Build roadmap entries
        conditions = []
        if delivered_only:
            conditions.append("status = 'delivered'")
        elif icebox_only:
            conditions.append("status = 'icebox'")
        else:
            parts = ["status = 'active'"]
            if include_icebox:
                parts.append("status = 'icebox'")
            if include_delivered:
                cutoff = (datetime.now(UTC) - timedelta(hours=RECENTLY_DELIVERED_HOURS)).isoformat()
                parts.append(f"(status = 'delivered' AND delivered_at >= '{cutoff}')")
            conditions.append(" OR ".join(parts))

        where = conditions[0] if conditions else "1=1"
        order = "delivered_at DESC" if delivered_only else "position"
        roadmap_started_at = time.perf_counter()
        rows = conn.execute(
            f"SELECT id, slug, position, group_slug, description, status, "  # guard: raw-sql
            f"delivered_at FROM roadmap WHERE {where} ORDER BY {order}",
        ).fetchall()
        roadmap_dt = time.perf_counter() - roadmap_started_at

        # Load deps
        deps_started_at = time.perf_counter()
        dep_rows = conn.execute(
            "SELECT slug, depends_on FROM roadmap_deps",  # guard: raw-sql
        ).fetchall()
        deps_dt = time.perf_counter() - deps_started_at
        deps_map: dict[str, list[str]] = {}
        for dr in dep_rows:
            deps_map.setdefault(dr[0], []).append(dr[1])

        todos: list[TodoDTO] = []
        state_query_total_dt = 0.0
        artifact_query_total_dt = 0.0
        todo_build_total_dt = 0.0
        for row in rows:
            row_id = row[0]
            slug = row[1]
            state_query_started_at = time.perf_counter()
            state_row = conn.execute(
                "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                (row_id,),
            ).fetchone()
            state_query_total_dt += time.perf_counter() - state_query_started_at

            todo_build_started_at = time.perf_counter()
            state = json.loads(state_row[0]) if state_row else {}
            current = str(state.get("current", ""))

            # Derive build/review status from current
            build_status: str | None = None
            review_status: str | None = None
            if current in ("build_started",):
                build_status = "started"
            elif current in (
                "build_complete",
                "review_pending",
                "review_changes_requested",
                "review_approved",
                "finalize_ready",
                "finalize_handed_off",
            ):
                build_status = "complete"
            if current in ("review_pending",):
                review_status = "pending"
            elif current in ("review_approved", "finalize_ready", "finalize_handed_off"):
                review_status = "approved"
            elif current == "review_changes_requested":
                review_status = "changes_requested"

            dor = state.get("dor")
            dor_score = dor.get("score", 0) if isinstance(dor, dict) else 0

            finalize = state.get("finalize")
            finalize_status = finalize.get("status") if isinstance(finalize, dict) else None

            prepare_phase = _derive_prepare_phase_from_current(current)
            integration_phase = _non_empty_str(state.get("integration_phase"))

            todo_status = row[5]  # active/icebox/delivered
            if todo_status == "active" and build_status:
                todo_status = "in_progress"
            elif todo_status == "active" and current in ("prepared",):
                todo_status = "ready"
            elif todo_status == "active" and prepare_phase:
                todo_status = "in_progress"

            # Check artifact existence from DB (by id)
            artifact_query_started_at = time.perf_counter()
            has_req_row = conn.execute(
                "SELECT 1 FROM todo_artifacts WHERE id = ? AND name = 'requirements'",  # guard: raw-sql
                (row_id,),
            ).fetchone()
            has_plan_row = conn.execute(
                "SELECT 1 FROM todo_artifacts WHERE id = ? AND name = 'implementation-plan'",  # guard: raw-sql
                (row_id,),
            ).fetchone()

            # List artifact names for the files field
            artifact_rows = conn.execute(
                "SELECT name FROM todo_artifacts WHERE id = ? ORDER BY name",  # guard: raw-sql
                (row_id,),
            ).fetchall()
            artifact_query_total_dt += time.perf_counter() - artifact_query_started_at

            todos.append(
                TodoDTO(
                    slug=slug,
                    status=todo_status,
                    description=row[4] or "",
                    has_requirements=has_req_row is not None,
                    has_impl_plan=has_plan_row is not None,
                    build_status=build_status,
                    review_status=review_status,
                    dor_score=dor_score if dor_score else None,
                    after=deps_map.get(slug, []),
                    group=row[3],
                    delivered_at=row[6],
                    prepare_phase=prepare_phase,
                    integration_phase=integration_phase,
                    finalize_status=finalize_status,
                    files=[ar[0] for ar in artifact_rows],
                    todo_path=str(Path(project_path) / "workspace" / slug),
                )
            )
            todo_build_total_dt += time.perf_counter() - todo_build_started_at

        total_dt = time.perf_counter() - started_at
        if total_dt >= 2.0:
            logger.warning(
                (
                    "assemble_roadmap_from_db was slow: total=%.3fs project=%s rows=%d deps=%d "
                    "init=%.3fs conn_open=%.3fs roadmap=%.3fs deps_load=%.3fs "
                    "state_queries=%.3fs artifact_queries=%.3fs todo_build=%.3fs other=%.3fs"
                ),
                total_dt,
                project_path,
                len(rows),
                len(dep_rows),
                init_dt,
                conn_open_dt,
                roadmap_dt,
                deps_dt,
                state_query_total_dt,
                artifact_query_total_dt,
                todo_build_total_dt,
                max(
                    0.0,
                    total_dt
                    - init_dt
                    - conn_open_dt
                    - roadmap_dt
                    - deps_dt
                    - state_query_total_dt
                    - artifact_query_total_dt
                    - todo_build_total_dt,
                ),
            )
        return todos
    finally:
        conn.close()
