"""Core todo list assembly logic.

DB-backed todo list assembly for CLI, API, and TUI.
"""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.constants import IntegrationPhase, TodoStatus
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    derive_build_status,
    derive_review_status,
    is_ready_band_eligible,
    is_ready_for_work,
    require_lifecycle_phase,
)
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.core.todos_db._upcycle import upcycle_state_dict
from teleclaude.types.state_value import StateValue
from teleclaude.types.todo_kind import TODO_KIND_DEFAULT

logger = get_logger(__name__)

RECENTLY_DELIVERED_HOURS = 72
READY_BAND = "ready"
IN_PREP_BAND = "in_prep"
_CLASSIFY_PHASE = "classify"


@dataclass(frozen=True)
class _ProjectionFields:
    todo_status: str
    kind: str | None
    build_status: str | None
    review_status: str | None
    lifecycle_phase: str | None
    integration_phase: str | None
    finalize_status: str | None


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
    by_id = {t.todo_id: t for t in todos if t.todo_id}
    # Removed slug twins must not override a live/delivered row used for tree derivation.
    non_removed_by_slug = {t.slug: t for t in todos if t.status != TodoStatus.REMOVED}

    children_by_parent: dict[str, list[str]] = {}
    for todo in todos:
        if todo.group:
            children_by_parent.setdefault(todo.group, []).append(todo.slug)

    def _leaf_todos(slug: str, seen: set[str]) -> list[TodoDTO]:
        if slug in seen:
            return []
        seen.add(slug)
        kids = children_by_parent.get(slug)
        if not kids:
            leaf = non_removed_by_slug.get(slug)
            if leaf is None or leaf.status == TodoStatus.ICEBOX:
                return []
            return [leaf]
        collected: list[TodoDTO] = []
        for kid in kids:
            collected.extend(_leaf_todos(kid, seen))
        return collected

    def _first_text(values: list[str | None]) -> str | None:
        return min(value for value in values if value) if any(values) else None

    for parent_slug in children_by_parent:
        holder = non_removed_by_slug.get(parent_slug)
        if holder is None:
            continue
        leaf_todos = _leaf_todos(parent_slug, set())
        leaf_statuses = [leaf.status for leaf in leaf_todos]
        if not leaf_statuses:
            continue
        if all(s == TodoStatus.DELIVERED for s in leaf_statuses):
            derived = TodoStatus.DELIVERED
        elif any(s == TodoStatus.IN_PROGRESS for s in leaf_statuses):
            derived = TodoStatus.IN_PROGRESS
        elif all(s == TodoStatus.READY for s in leaf_statuses):
            derived = TodoStatus.READY
        else:
            derived = TodoStatus.PENDING

        updates: dict[str, str | None] = {"status": derived.value}
        if derived == TodoStatus.READY:
            updates["band"] = READY_BAND
            updates["ready_since"] = _first_text([leaf.ready_since or leaf.updated_at for leaf in leaf_todos])

        if updates["status"] != holder.status or any(getattr(holder, key) != value for key, value in updates.items()):
            updated_holder = holder.model_copy(update=updates)
            if holder.todo_id:
                by_id[holder.todo_id] = updated_holder
            non_removed_by_slug[parent_slug] = updated_holder

    return [by_id[t.todo_id] if t.todo_id and t.todo_id in by_id else t for t in todos]


def _descending_text_key(value: str | None) -> tuple[int, tuple[int, ...]]:
    if not value:
        return (1, ())
    return (0, tuple(-ord(char) for char in value))


def _with_active_band(todo: TodoDTO, delivered_slug_set: set[str]) -> TodoDTO:
    if todo.band in {READY_BAND, IN_PREP_BAND}:
        return todo
    band = (
        READY_BAND
        if is_ready_band_eligible(
            kind=todo.kind,
            lifecycle_phase=todo.lifecycle_phase,
            after_deps=todo.after,
            delivered_slugs=delivered_slug_set,
        )
        else IN_PREP_BAND
    )
    return todo.model_copy(update={"band": band})


def _derive_projection_fields(slug: str, raw_status: str, state: dict[str, StateValue] | None) -> _ProjectionFields:
    if state is None:
        return _ProjectionFields(
            todo_status=raw_status,
            kind=None,
            build_status=None,
            review_status=None,
            lifecycle_phase=None,
            integration_phase=None,
            finalize_status=None,
        )

    raw_kind = state.get("kind")
    kind = raw_kind if isinstance(raw_kind, str) else None

    finalize_raw = state.get("finalize")
    finalize = finalize_raw if isinstance(finalize_raw, dict) else {}
    finalize_status = _non_empty_str(finalize.get("status"))

    kind_is_unset = raw_kind is None
    if kind_is_unset and state.get("lifecycle_phase") is None:
        lifecycle = None
        current_value = _CLASSIFY_PHASE
        is_draft_lifecycle = False
    else:
        lifecycle = require_lifecycle_phase(
            state.get("lifecycle_phase"),
            context=f"assemble_todo_from_db({slug})",
        )
        current_value = lifecycle.value
        is_draft_lifecycle = lifecycle == LifecyclePhase.DRAFT

    state_phase = state.get("phase", "")
    is_delivered = state_phase == TodoStatus.DELIVERED

    build_status = derive_build_status(
        current_value,
        is_draft=is_draft_lifecycle,
        is_delivered=is_delivered,
    )
    review_status = derive_review_status(
        current_value,
        is_draft=is_draft_lifecycle,
        is_delivered=is_delivered,
    )
    lifecycle_phase = None if is_delivered else current_value

    raw_integration_phase = _non_empty_str(state.get("integration_phase"))
    if raw_integration_phase and raw_integration_phase not in tuple(IntegrationPhase):
        integration_phase: str | None = IntegrationPhase.STARTED
    else:
        integration_phase = raw_integration_phase

    todo_status = raw_status
    if todo_status == TodoStatus.DELIVERED or is_delivered:
        todo_status = TodoStatus.DELIVERED
        integration_phase = IntegrationPhase.DELIVERED
    elif todo_status == TodoStatus.ACTIVE and is_draft_lifecycle:
        todo_status = TodoStatus.PENDING

    ready, _ = is_ready_for_work(
        kind=kind if isinstance(kind, str) else TODO_KIND_DEFAULT,
        lifecycle_phase=lifecycle_phase,
    )
    if todo_status == TodoStatus.ACTIVE and build_status:
        todo_status = TodoStatus.IN_PROGRESS
    elif todo_status == TodoStatus.ACTIVE and ready:
        todo_status = TodoStatus.READY
    elif todo_status == TodoStatus.ACTIVE and kind_is_unset:
        todo_status = TodoStatus.IN_PROGRESS
    elif todo_status == TodoStatus.ACTIVE and lifecycle_phase:
        todo_status = TodoStatus.IN_PROGRESS

    return _ProjectionFields(
        todo_status=todo_status,
        kind=kind,
        build_status=build_status,
        review_status=review_status,
        lifecycle_phase=lifecycle_phase,
        integration_phase=integration_phase,
        finalize_status=finalize_status,
    )


def section_sort_key(todo: TodoDTO, *, raw_status: str | None = None) -> tuple[int, object, str]:
    """Sort key for derived todo list sections — newest-first within each section.

    Active rows group actionable (Ready band) rows above in-prep rows, then sort
    newest-first by ``ready_since`` falling back to ``created_at``. Delivered
    sorts by ``delivered_at``, icebox by ``updated_at``. Slug breaks ties.
    """
    status = raw_status or todo.status
    if status == TodoStatus.DELIVERED:
        return (0, _descending_text_key(todo.delivered_at), todo.slug)
    if status == TodoStatus.ICEBOX:
        return (0, _descending_text_key(todo.updated_at), todo.slug)
    band_rank = 0 if todo.band == READY_BAND else 1
    return (band_rank, _descending_text_key(todo.ready_since or todo.created_at), todo.slug)


def _apply_section_ordering(
    todos: list[TodoDTO],
    delivered_slug_set: set[str],
    raw_status_by_id: dict[str, str],
) -> list[TodoDTO]:
    """Sort todos into their todo sections (ready/prep/icebox/delivered)."""
    banded: list[TodoDTO] = []
    for todo in todos:
        raw_status = raw_status_by_id.get(todo.todo_id or "")
        if raw_status == TodoStatus.ACTIVE:
            banded.append(_with_active_band(todo, delivered_slug_set))
        else:
            banded.append(todo)
    return sorted(
        banded,
        key=lambda todo: section_sort_key(todo, raw_status=raw_status_by_id.get(todo.todo_id or "")),
    )


def assemble_todo_from_db(
    project_path: str,
    include_icebox: bool = False,
    icebox_only: bool = False,
    include_delivered: bool = False,
    delivered_only: bool = False,
    delivered_since: str | None = None,
    include_removed: bool = False,
    removed_only: bool = False,
) -> list[TodoDTO]:
    """Assemble todo list from todos.db using sync methods.

    Reads state, todo list entries, and deps from the SQLite database.

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
    init_started_at = time.perf_counter()
    db = get_todos_db_sync(project_path)
    init_dt = time.perf_counter() - init_started_at

    conn_open_started_at = time.perf_counter()
    conn = db._sync_conn()
    conn_open_dt = time.perf_counter() - conn_open_started_at
    try:
        # Build todo list entries.
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
        removed_clause = "status = 'removed'"

        conditions = []
        if delivered_only:
            conditions.append(delivered_clause)
        elif icebox_only:
            conditions.append("status = 'icebox'")
        elif removed_only:
            conditions.append(removed_clause)
        else:
            parts = ["status = 'active'"]
            if include_icebox:
                parts.append("status = 'icebox'")
            if include_delivered:
                parts.append(delivered_clause)
            if include_removed:
                parts.append(removed_clause)
            conditions.append(" OR ".join(parts))

        where = conditions[0] if conditions else "1=1"
        todo_started_at = time.perf_counter()
        rows = conn.execute(
            "SELECT id, slug, ready_since, group_slug, description, status, "  # guard: raw-sql
            f"delivered_at, updated_at, created_at, removed_at FROM todo WHERE {where} ORDER BY id",
        ).fetchall()
        todo_dt = time.perf_counter() - todo_started_at

        delivered_slug_rows = conn.execute(
            "SELECT slug FROM todo WHERE status = 'delivered'",  # guard: raw-sql
        ).fetchall()
        delivered_slug_set = {str(delivered_slug[0]) for delivered_slug in delivered_slug_rows}

        # Load deps
        deps_started_at = time.perf_counter()
        dep_rows = conn.execute(
            "SELECT slug, depends_on FROM todo_deps",  # guard: raw-sql
        ).fetchall()
        deps_dt = time.perf_counter() - deps_started_at
        deps_map: dict[str, list[str]] = {}
        for dr in dep_rows:
            deps_map.setdefault(dr[0], []).append(dr[1])

        holder_slugs = {row[3] for row in rows if row[3] and row[3] != row[1]}

        todos: list[TodoDTO] = []
        raw_status_by_id: dict[str, str] = {}
        state_query_total_dt = 0.0
        artifact_query_total_dt = 0.0
        todo_build_total_dt = 0.0
        for row in rows:
            row_id = row[0]
            slug = row[1]
            raw_status = row[5]
            raw_status_by_id[str(row_id)] = raw_status
            state_query_started_at = time.perf_counter()
            state_row = conn.execute(
                "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                (row_id,),
            ).fetchone()
            state_query_total_dt += time.perf_counter() - state_query_started_at

            todo_build_started_at = time.perf_counter()
            is_holder = slug in holder_slugs
            if state_row is None and not is_holder:
                # A delivered row legitimately carries no state: the legacy
                # importer records delivered todos as history (todo + artifacts,
                # no state). A non-delivered row missing state is an integrity
                # defect worth surfacing.
                if raw_status == "delivered":
                    logger.debug(
                        "Skipping delivered todo row without todo state",
                        slug=slug,
                        project_path=project_path,
                        todo_id=str(row_id),
                    )
                else:
                    logger.warning(
                        "Skipping todo row missing todo state",
                        slug=slug,
                        status=raw_status,
                        project_path=project_path,
                        todo_id=str(row_id),
                    )
                continue
            if is_holder:
                state = None
            else:
                try:
                    state = upcycle_state_dict(json.loads(state_row[0]))
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

            projection = _derive_projection_fields(slug, raw_status, state)
            hold_audit = state.get("hold_audit") if isinstance(state, dict) else None

            todos.append(
                TodoDTO(
                    slug=slug,
                    status=projection.todo_status,
                    description=row[4] or "",
                    has_requirements=has_req_row is not None,
                    has_impl_plan=has_plan_row is not None,
                    kind=projection.kind,
                    ready_since=row[2],
                    updated_at=row[7],
                    created_at=row[8],
                    build_status=projection.build_status,
                    review_status=projection.review_status,
                    after=deps_map.get(slug, []),
                    group=row[3],
                    delivered_at=row[6],
                    lifecycle_phase=projection.lifecycle_phase,
                    integration_phase=projection.integration_phase,
                    finalize_status=projection.finalize_status,
                    hold=bool(state.get("hold")) if isinstance(state, dict) else False,
                    hold_source=(
                        str(hold_audit.get("source"))
                        if isinstance(hold_audit, dict) and isinstance(hold_audit.get("source"), str)
                        else None
                    ),
                    active_runner=(
                        str(state.get("active_runner"))
                        if isinstance(state, dict) and isinstance(state.get("active_runner"), str)
                        else None
                    ),
                    files=[ar[0] for ar in artifact_rows],
                    version_total=version_total,
                    todo_id=str(row_id),
                    removed_at=row[9],
                )
            )
            todo_build_total_dt += time.perf_counter() - todo_build_started_at

        todos = _apply_holder_status(todos)
        todos = _apply_section_ordering(todos, delivered_slug_set, raw_status_by_id)

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
                    t.status == TodoStatus.DELIVERED
                    and t.delivered_at
                    and t.delivered_at < delivered_since
                    and not (t.group and t.group in all_slugs)
                )
            ]

        total_dt = time.perf_counter() - started_at
        if total_dt >= 2.0:
            logger.warning(
                (
                    "assemble_todo_from_db was slow: total=%.3fs project=%s rows=%d deps=%d "
                    "init=%.3fs conn_open=%.3fs todo=%.3fs deps_load=%.3fs "
                    "state_queries=%.3fs artifact_queries=%.3fs todo_build=%.3fs other=%.3fs"
                ),
                total_dt,
                project_path,
                len(rows),
                len(dep_rows),
                init_dt,
                conn_open_dt,
                todo_dt,
                deps_dt,
                state_query_total_dt,
                artifact_query_total_dt,
                todo_build_total_dt,
                max(
                    0.0,
                    total_dt
                    - init_dt
                    - conn_open_dt
                    - todo_dt
                    - deps_dt
                    - state_query_total_dt
                    - artifact_query_total_dt
                    - todo_build_total_dt,
                ),
            )
        return todos
    finally:
        conn.close()
