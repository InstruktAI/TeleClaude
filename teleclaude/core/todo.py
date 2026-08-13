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
    effective_hold,
    is_ready_band_eligible,
    is_ready_for_work,
    prepare_review_verdict_from_state,
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
    prepare_review_verdict: str | None


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


def _artifact_digest(state: dict[str, StateValue] | None, artifact_key: str) -> str | None:
    if not isinstance(state, dict):
        return None
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    artifact = artifacts.get(artifact_key)
    if not isinstance(artifact, dict):
        return None
    digest = artifact.get("digest")
    return digest if isinstance(digest, str) and digest else None


def _approval_digest(state: dict[str, StateValue] | None, approval_key: str) -> str | None:
    if not isinstance(state, dict):
        return None
    approvals = state.get("approvals")
    if not isinstance(approvals, dict):
        return None
    approval = approvals.get(approval_key)
    if not isinstance(approval, dict) or approval.get("approved") is not True:
        return None
    digest = approval.get("approved_digest")
    return digest if isinstance(digest, str) and digest else None


def _first_text(values: list[str | None]) -> str | None:
    return min(value for value in values if value) if any(values) else None


def _apply_holder_status(todos: list[TodoDTO], holder_slug_by_id: dict[str, str]) -> list[TodoDTO]:
    """Synthesize a label-only node for every holder with a live descendant.

    A holder row never enters ``todos`` (its status is neither active,
    icebox, delivered, nor removed) — it has no row-presence of its own in
    any band. Its node exists purely so referencing children have a labeled
    anchor to nest under; its displayed status is always the recursive
    leaf-children aggregate. A holder with no live (non-removed, non-icebox)
    descendant contributes no node at all.

    Keyed throughout by durable id (``todo_id``/``group_id``), never by
    slug: a retained delivered or removed row may legitimately share a slug
    with a live holder (see
    project/spec/feature/workflow/todo-management#known-caveats), and a
    slug-keyed map would silently collide the two.
    """
    by_id = {t.todo_id: t for t in todos if t.todo_id}

    children_by_parent_id: dict[str, list[str]] = {}
    for todo in todos:
        if todo.group_id and todo.todo_id:
            children_by_parent_id.setdefault(todo.group_id, []).append(todo.todo_id)

    def _leaf_todos(todo_id: str, seen: set[str]) -> list[TodoDTO]:
        if todo_id in seen:
            return []
        seen.add(todo_id)
        kids = children_by_parent_id.get(todo_id)
        if not kids:
            leaf = by_id.get(todo_id)
            if leaf is None or leaf.status in (TodoStatus.REMOVED, TodoStatus.ICEBOX):
                return []
            return [leaf]
        collected: list[TodoDTO] = []
        for kid in kids:
            collected.extend(_leaf_todos(kid, seen))
        return collected

    stubs: list[TodoDTO] = []
    for holder_id, holder_slug in holder_slug_by_id.items():
        if holder_id not in children_by_parent_id:
            continue
        leaf_todos = _leaf_todos(holder_id, set())
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

        stub = TodoDTO(
            slug=holder_slug,
            status=derived.value,
            has_requirements=False,
            has_impl_plan=False,
            todo_id=holder_id,
        )
        if derived == TodoStatus.READY:
            stub = stub.model_copy(
                update={
                    "band": READY_BAND,
                    "ready_since": _first_text([leaf.ready_since or leaf.updated_at for leaf in leaf_todos]),
                }
            )
        stubs.append(stub)

    return [*todos, *stubs]


def _apply_removed_holder_labels(todos: list[TodoDTO], holder_slug_by_id: dict[str, str]) -> list[TodoDTO]:
    """Synthesize a removed-band label stub for holders referenced by removed children.

    Mirrors :func:`_apply_holder_status`'s rollup but scoped to the removed
    band, independent of whether the same holder also carries live or
    delivered descendants (which land their own stub via
    ``_apply_holder_status``). A holder is never itself removed — the
    ``removed`` status here is purely the display-bucket routing
    ``build_todo_sections`` already uses for the ``delivered`` stub. Keyed by
    durable id, so a genuine (unrelated) removed row that happens to share
    the holder's slug from a prior generation is untouched and coexists
    alongside the synthetic label — no collision, no row lost.
    """
    removed_children_by_parent_id: dict[str, list[TodoDTO]] = {}
    for todo in todos:
        if todo.group_id and todo.status == TodoStatus.REMOVED:
            removed_children_by_parent_id.setdefault(todo.group_id, []).append(todo)
    if not removed_children_by_parent_id:
        return todos

    stubs = [
        TodoDTO(
            slug=holder_slug_by_id[holder_id],
            status=TodoStatus.REMOVED.value,
            has_requirements=False,
            has_impl_plan=False,
            todo_id=holder_id,
            removed_at=_first_text([child.removed_at for child in children]),
        )
        for holder_id, children in removed_children_by_parent_id.items()
        if holder_id in holder_slug_by_id
    ]
    return [*todos, *stubs]


def _apply_icebox_holder_labels(todos: list[TodoDTO], holder_slug_by_id: dict[str, str]) -> list[TodoDTO]:
    """Synthesize an icebox-band label stub for holders referenced by icebox children.

    :func:`_apply_holder_status`'s rollup deliberately excludes icebox leaves
    from its aggregate (an iceboxed child must never count toward the active
    band's derived status), so a holder whose live children are all iceboxed
    would otherwise get no label anywhere — its icebox children would render
    at their section root instead of under holder context. Mirrors
    :func:`_apply_removed_holder_labels`'s band-scoped, id-keyed
    stub-injection, independent of whether the same holder also carries
    live/delivered/removed descendants (which land their own stub
    elsewhere).
    """
    icebox_children_by_parent_id: dict[str, list[TodoDTO]] = {}
    for todo in todos:
        if todo.group_id and todo.status == TodoStatus.ICEBOX:
            icebox_children_by_parent_id.setdefault(todo.group_id, []).append(todo)
    if not icebox_children_by_parent_id:
        return todos

    stubs = [
        TodoDTO(
            slug=holder_slug_by_id[holder_id],
            status=TodoStatus.ICEBOX.value,
            has_requirements=False,
            has_impl_plan=False,
            todo_id=holder_id,
            updated_at=_first_text([child.updated_at for child in children]),
        )
        for holder_id, children in icebox_children_by_parent_id.items()
        if holder_id in holder_slug_by_id
    ]
    return [*todos, *stubs]


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
            prepare_review_verdict=None,
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
    prepare_review_verdict = (
        prepare_review_verdict_from_state(state) if lifecycle_phase == LifecyclePhase.BLOCKED.value else None
    )

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
        prepare_review_verdict=prepare_review_verdict,
    )


def section_sort_key(todo: TodoDTO, *, raw_status: str | None = None) -> tuple[int, object, str]:
    """Sort key for derived todo list sections — newest-first within each section.

    Active rows group actionable (Ready band) rows above in-prep rows, then sort
    newest-first by ``ready_since`` falling back to ``created_at``. Delivered
    sorts by ``delivered_at``, icebox by ``updated_at``, removed by
    ``removed_at``. Slug breaks ties.
    """
    status = raw_status or todo.status
    if status == TodoStatus.DELIVERED:
        return (0, _descending_text_key(todo.delivered_at), todo.slug)
    if status == TodoStatus.ICEBOX:
        return (0, _descending_text_key(todo.updated_at), todo.slug)
    if status == TodoStatus.REMOVED:
        return (0, _descending_text_key(todo.removed_at), todo.slug)
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
            "SELECT id, slug, ready_since, schedule, group_id, description, status, "  # guard: raw-sql
            f"delivered_at, updated_at, created_at, removed_at, lineage, entry_point, human_involved, context "
            f"FROM todo WHERE {where} ORDER BY id",
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

        # Holder rows never match the status allow-list above (never
        # 'active'/'icebox'/'delivered'/'removed'), so they carry no row of
        # their own in `rows`. Resolved separately so children can join their
        # holder's current slug label from the id edge — never a stored copy.
        holder_rows = conn.execute("SELECT id, slug FROM todo WHERE status = 'holder'").fetchall()  # guard: raw-sql
        holder_slug_by_id = {str(hid): str(hslug) for hid, hslug in holder_rows}

        todos: list[TodoDTO] = []
        raw_status_by_id: dict[str, str] = {}
        state_query_total_dt = 0.0
        artifact_query_total_dt = 0.0
        todo_build_total_dt = 0.0
        for row in rows:
            row_id = row[0]
            slug = row[1]
            raw_status = row[6]
            raw_status_by_id[str(row_id)] = raw_status
            state_query_started_at = time.perf_counter()
            state_row = conn.execute(
                "SELECT state FROM todo_state WHERE id = ?",  # guard: raw-sql
                (row_id,),
            ).fetchone()
            state_query_total_dt += time.perf_counter() - state_query_started_at

            todo_build_started_at = time.perf_counter()
            if state_row is None:
                # A delivered row legitimately carries no state: the legacy
                # importer records delivered todos as history (todo + artifacts,
                # no state). A non-delivered row missing state is an integrity
                # defect worth surfacing. Holder rows never reach this loop at
                # all — they are excluded by the status allow-list — so no
                # holder short-circuit is needed here.
                if raw_status == "delivered":
                    logger.trace(
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
            hold_audit = state.get("hold_audit")
            # Derive hold once at the projection boundary so every UI edge reads
            # only the verdict.
            held = effective_hold(hold=bool(state.get("hold")))

            todos.append(
                TodoDTO(
                    slug=slug,
                    status=projection.todo_status,
                    description=row[5] or "",
                    has_requirements=has_req_row is not None,
                    has_impl_plan=has_plan_row is not None,
                    kind=projection.kind,
                    ready_since=row[2],
                    schedule=row[3],
                    task_plan_digest=_artifact_digest(state, "task_plan"),
                    task_approved_digest=_approval_digest(state, "task_approved"),
                    updated_at=row[8],
                    created_at=row[9],
                    build_status=projection.build_status,
                    review_status=projection.review_status,
                    after=deps_map.get(slug, []),
                    group=holder_slug_by_id.get(row[4]) if row[4] else None,
                    group_id=row[4] if row[4] in holder_slug_by_id else None,
                    delivered_at=row[7],
                    lifecycle_phase=projection.lifecycle_phase,
                    integration_phase=projection.integration_phase,
                    finalize_status=projection.finalize_status,
                    prepare_review_verdict=projection.prepare_review_verdict,
                    hold=bool(state.get("hold")),
                    held=held,
                    hold_source=(
                        str(hold_audit.get("source"))
                        if isinstance(hold_audit, dict) and isinstance(hold_audit.get("source"), str)
                        else None
                    ),
                    active_runner=(
                        str(state.get("active_runner")) if isinstance(state.get("active_runner"), str) else None
                    ),
                    files=[ar[0] for ar in artifact_rows],
                    version_total=version_total,
                    todo_id=str(row_id),
                    removed_at=row[10],
                    lineage=row[11],
                    entry_point=row[12],
                    human_involved=bool(row[13]),
                    context=row[14],
                )
            )
            todo_build_total_dt += time.perf_counter() - todo_build_started_at

        todos = _apply_holder_status(todos, holder_slug_by_id)
        todos = _apply_removed_holder_labels(todos, holder_slug_by_id)
        todos = _apply_icebox_holder_labels(todos, holder_slug_by_id)
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
