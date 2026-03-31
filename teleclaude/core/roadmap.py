"""Core roadmap assembly logic.

DB-backed roadmap assembly for CLI, API, and TUI.
"""

import json
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.models import TodoInfo

logger = get_logger(__name__)

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
) -> list[TodoInfo]:
    """Assemble roadmap from todos.db using sync methods.

    Reads state, roadmap entries, and deps from the SQLite database.
    """
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    db = TodosDb(str(Path(project_path) / ".teleclaude" / "todos.db"))
    db.initialize_sync()

    conn = db._sync_conn()  # pylint: disable=protected-access
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
                parts.append("status = 'delivered'")
            conditions.append(" OR ".join(parts))

        where = conditions[0] if conditions else "1=1"
        rows = conn.execute(
            f"SELECT id, slug, position, group_slug, description, status, "  # guard: raw-sql
            f"delivered_at FROM roadmap WHERE {where} ORDER BY position",
        ).fetchall()

        # Load deps
        dep_rows = conn.execute(
            "SELECT slug, depends_on FROM roadmap_deps",  # guard: raw-sql
        ).fetchall()
        deps_map: dict[str, list[str]] = {}
        for dr in dep_rows:
            deps_map.setdefault(dr[0], []).append(dr[1])

        todos: list[TodoInfo] = []
        for row in rows:
            row_id = row[0]
            slug = row[1]
            state_row = conn.execute(
                "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                (row_id,),
            ).fetchone()

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

            todos.append(
                TodoInfo(
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
                    current=current or None,
                    prepare_phase=prepare_phase,
                    integration_phase=integration_phase,
                    finalize_status=finalize_status,
                    files=[ar[0] for ar in artifact_rows],
                )
            )

        return todos
    finally:
        conn.close()
