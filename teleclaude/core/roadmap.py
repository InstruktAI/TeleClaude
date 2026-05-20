"""Core roadmap assembly logic.

DB-backed roadmap assembly for CLI, API, and TUI.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.constants import TODO_KIND_DEFAULT, IntegrationPhase, RoadmapStatus
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    derive_build_status,
    derive_review_status,
    is_ready_for_work,
    require_lifecycle_phase,
)
from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._upcycle import upcycle_state_dict

logger = get_logger(__name__)

RECENTLY_DELIVERED_HOURS = 72


def recently_delivered_cutoff() -> str:
    """ISO-8601 cutoff for the default/TUI 'recently delivered' window.

    The default list view and TUI scope delivered entries to this window so
    they are not flooded with the full delivery history. The explicit CLI
    ``--since`` flag overrides it with a user-requested cutoff.
    """
    return (datetime.now(UTC) - timedelta(hours=RECENTLY_DELIVERED_HOURS)).isoformat()


def parse_since_to_cutoff(value: str) -> str:
    """Parse a user ``--since`` value into a clean ISO-8601 cutoff timestamp.

    Accepts a relative duration (``<int><unit>`` where unit is ``h`` hours,
    ``d`` days, or ``w`` weeks — e.g. ``72h``, ``7d``, ``2w``) or an absolute
    date / ISO timestamp (``2026-05-01`` or ``2026-05-01T12:30:00+05:00``).
    Naive datetimes are assumed UTC; timezone-aware inputs are normalised to
    UTC. Stored ``delivered_at`` values are UTC ISO strings compared
    lexicographically in SQLite, so the cutoff MUST also be a UTC (``+00:00``)
    ISO string — a non-UTC offset would make the string comparison disagree
    with chronological order. The return is always re-serialised via
    ``isoformat()`` so callers never embed raw user text into SQL.

    Raises ``ValueError`` with an actionable message on unparseable input.
    """
    raw = value.strip()
    if not raw:
        raise ValueError("--since requires a value (e.g. 7d, 72h, 2w, or 2026-05-01)")

    unit_hours = {"h": 1, "d": 24, "w": 24 * 7}
    if raw[-1].lower() in unit_hours and raw[:-1].lstrip("-").isdigit():
        amount = int(raw[:-1])
        if amount < 0:
            raise ValueError(f"--since duration must not be negative: {value!r}")
        delta = timedelta(hours=amount * unit_hours[raw[-1].lower()])
        return (datetime.now(UTC) - delta).isoformat()

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"--since value {value!r} is not a duration (7d, 72h, 2w) or ISO date (2026-05-01)") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _non_empty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _apply_holder_status(todos: list[TodoDTO]) -> list[TodoDTO]:
    """Override each holder's status with the aggregate of its leaf children.

    A holder carries no status of its own — it is always the recursive
    leaf-children aggregate. Derived here so every consumer reads one
    authoritative value.
    """
    by_slug = {t.slug: t for t in todos}
    children_by_parent: dict[str, list[str]] = {}
    for todo in todos:
        if todo.group:
            children_by_parent.setdefault(todo.group, []).append(todo.slug)

    def _leaf_statuses(slug: str, seen: set[str]) -> list[str]:
        if slug in seen:
            return []
        seen.add(slug)
        kids = children_by_parent.get(slug)
        if not kids:
            leaf = by_slug.get(slug)
            if leaf is None or leaf.status == RoadmapStatus.ICEBOX:
                return []
            return [leaf.status]
        collected: list[str] = []
        for kid in kids:
            collected.extend(_leaf_statuses(kid, seen))
        return collected

    for parent_slug in children_by_parent:
        holder = by_slug.get(parent_slug)
        if holder is None:
            continue
        leaf_statuses = _leaf_statuses(parent_slug, set())
        if not leaf_statuses:
            continue
        if all(s == RoadmapStatus.DELIVERED for s in leaf_statuses):
            derived = RoadmapStatus.DELIVERED
        elif any(s == RoadmapStatus.IN_PROGRESS for s in leaf_statuses):
            derived = RoadmapStatus.IN_PROGRESS
        elif all(s == RoadmapStatus.READY for s in leaf_statuses):
            derived = RoadmapStatus.READY
        else:
            derived = RoadmapStatus.PENDING
        if derived != holder.status:
            by_slug[parent_slug] = holder.model_copy(update={"status": derived})

    return [by_slug[t.slug] for t in todos]


def assemble_roadmap_from_db(
    project_path: str,
    include_icebox: bool = False,
    icebox_only: bool = False,
    include_delivered: bool = False,
    delivered_only: bool = False,
    delivered_since: str | None = None,
) -> list[TodoDTO]:
    """Assemble roadmap from todos.db using sync methods.

    Reads state, roadmap entries, and deps from the SQLite database.

    ``include_delivered``/``delivered_only`` return delivered entries.
    ``delivered_since`` optionally restricts delivered entries to those
    delivered at or after the given ISO-8601 timestamp. It is applied as a
    post-derivation DISPLAY filter — after holder-status derivation, never in
    SQL — so a holder whose children delivered outside the window still derives
    as delivered while the genuine old delivered leaf rows are hidden. Callers
    own their cutoff: the default/TUI list view passes
    ``now - RECENTLY_DELIVERED_HOURS``; the CLI ``--since`` flag passes the
    user-requested cutoff; an absent value returns all delivered entries. The
    value must be a clean ISO timestamp produced by the caller.
    """
    started_at = time.perf_counter()
    db = TodosDb(str(Path(project_path) / ".teleclaude" / "todos.db"))
    init_started_at = time.perf_counter()
    db.initialize_sync()
    init_dt = time.perf_counter() - init_started_at

    conn_open_started_at = time.perf_counter()
    conn = db._sync_conn()
    conn_open_dt = time.perf_counter() - conn_open_started_at
    try:
        # Build roadmap entries.
        #
        # The WHERE clause builds an explicit allow-list of statuses (active,
        # icebox, delivered) — never a negative predicate. Soft-removed rows
        # (status = 'removed') are therefore invisible by construction; do not
        # regress this to ``status != 'delivered'``.
        #
        # `delivered_since` is a DISPLAY window applied after holder-status
        # derivation — never in SQL — so a holder whose children delivered
        # outside the window still derives as delivered.
        delivered_clause = "status = 'delivered'"

        conditions = []
        if delivered_only:
            conditions.append(delivered_clause)
        elif icebox_only:
            conditions.append("status = 'icebox'")
        else:
            parts = ["status = 'active'"]
            if include_icebox:
                parts.append("status = 'icebox'")
            if include_delivered:
                parts.append(delivered_clause)
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
            try:
                state = upcycle_state_dict(json.loads(state_row[0]) if state_row else {})
            except ValueError as exc:
                logger.warning(
                    "Skipping todo with unreadable state",
                    slug=slug,
                    project_path=project_path,
                    reason=str(exc),
                )
                continue

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
            version_total_row = conn.execute(
                "SELECT COUNT(*) FROM todo_artifact_versions WHERE id = ?",  # guard: raw-sql
                (row_id,),
            ).fetchone()
            artifact_query_total_dt += time.perf_counter() - artifact_query_started_at
            version_total = int(version_total_row[0]) if version_total_row is not None else 0

            # --- Derive display values from canonical lifecycle state ---

            kind = state.get("kind")

            finalize_raw = state.get("finalize")
            finalize = finalize_raw if isinstance(finalize_raw, dict) else {}
            finalize_status = _non_empty_str(finalize.get("status"))

            lifecycle = require_lifecycle_phase(
                state.get("lifecycle_phase"),
                context=f"assemble_roadmap_from_db({slug})",
            )
            current_value = lifecycle.value
            is_draft_lifecycle = lifecycle == LifecyclePhase.DRAFT

            state_phase = state.get("phase", "")
            is_delivered = state_phase == RoadmapStatus.DELIVERED

            # Build/review status and lifecycle display phase derive from the
            # canonical lifecycle pointer via shared lifecycle helpers.
            build_status = derive_build_status(current_value, is_draft=is_draft_lifecycle, is_delivered=is_delivered)
            review_status = derive_review_status(current_value, is_draft=is_draft_lifecycle, is_delivered=is_delivered)
            lifecycle_phase = None if is_delivered else current_value

            raw_integration_phase = _non_empty_str(state.get("integration_phase"))
            # Normalize legacy 12-phase mirror values to the two canonical values.
            if raw_integration_phase and raw_integration_phase not in tuple(IntegrationPhase):
                integration_phase: str | None = IntegrationPhase.STARTED
            else:
                integration_phase = raw_integration_phase

            todo_status = row[5]  # active/icebox/delivered — authoritative DB state
            # Re-bucketing below only refines the 'active' bucket into more
            # granular states (pending/ready/in_progress). Icebox and delivered
            # are authoritative roadmap statuses — never overwrite them from a
            # lifecycle pointer (which defaults to DRAFT for never-prepared
            # entries and would otherwise clobber 'icebox' into 'pending').
            if todo_status == RoadmapStatus.DELIVERED or is_delivered:
                # Delivered wins over a never-advanced draft lifecycle pointer.
                todo_status = RoadmapStatus.DELIVERED
                integration_phase = IntegrationPhase.DELIVERED
            elif todo_status == RoadmapStatus.ACTIVE and is_draft_lifecycle:
                todo_status = RoadmapStatus.PENDING
            ready, _ = is_ready_for_work(
                kind=kind if isinstance(kind, str) else TODO_KIND_DEFAULT,
                lifecycle_phase=lifecycle_phase,
            )
            if todo_status == RoadmapStatus.ACTIVE and build_status:
                todo_status = RoadmapStatus.IN_PROGRESS
            elif todo_status == RoadmapStatus.ACTIVE and ready:
                todo_status = RoadmapStatus.READY
            elif todo_status == RoadmapStatus.ACTIVE and lifecycle_phase:
                todo_status = RoadmapStatus.IN_PROGRESS

            todos.append(
                TodoDTO(
                    slug=slug,
                    status=todo_status,
                    description=row[4] or "",
                    has_requirements=has_req_row is not None,
                    has_impl_plan=has_plan_row is not None,
                    build_status=build_status,
                    review_status=review_status,
                    after=deps_map.get(slug, []),
                    group=row[3],
                    delivered_at=row[6],
                    lifecycle_phase=lifecycle_phase,
                    integration_phase=integration_phase,
                    finalize_status=finalize_status,
                    files=[ar[0] for ar in artifact_rows],
                    version_total=version_total,
                )
            )
            todo_build_total_dt += time.perf_counter() - todo_build_started_at

        todos = _apply_holder_status(todos)

        # Display window: drop genuine delivered entries older than the cutoff.
        # Holders (derived 'delivered', no own delivered_at) are unaffected.
        # Children of holders ride along with their holder regardless of age —
        # filtering them out would orphan the holder row from the work that
        # produced its derived 'delivered' status.
        if delivered_since is not None:
            all_slugs = {t.slug for t in todos}
            todos = [
                t
                for t in todos
                if not (
                    t.status == RoadmapStatus.DELIVERED
                    and t.delivered_at
                    and t.delivered_at < delivered_since
                    and not (t.group and t.group in all_slugs)
                )
            ]

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
