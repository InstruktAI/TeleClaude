"""Core todo list assembly logic.

DB-backed todo list assembly for CLI, API, and TUI.
"""

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.api_models import TodoDTO
from teleclaude.constants import IntegrationPhase, TodoStatus
from teleclaude.core.next_machine.artifacts import artifact_name_to_state_key
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
from teleclaude.core.workflow_machine.held_standing import held_ready_standing, stored_ready_reading
from teleclaude.core.workflow_machine.phase_reading import PhaseReading
from teleclaude.core.workflow_store.store import WorkflowStore, get_workflow_store_sync
from teleclaude.core.workflow_store.types import TodoProjectionItem
from teleclaude.types.claim_change import WORKFLOW_STATE_KEY, workflow_record_of
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import PREPARED_SESSION_ID_STATE_KEY, HoldAuditSource, TodoState
from teleclaude.types.workflow_record import Phase

logger = get_logger(__name__)

_SKIP_DELIVERED_STATE_LOG = "Skipping delivered todo row without todo state"
_SKIP_MISSING_STATE_LOG = "Skipping todo row missing todo state"
_SKIP_UNREADABLE_STATE_LOG = "Skipping todo with unreadable state"
_EMPTY_TEXT = ""
_SLOW_ASSEMBLE_LOG = (
    "assemble_todo_from_db was slow: total=%.3fs project=%s rows=%d deps=%d "
    "init=%.3fs conn_open=%.3fs todo=%.3fs deps_load=%.3fs "
    "state_queries=%.3fs artifact_queries=%.3fs todo_build=%.3fs other=%.3fs"
)


class _ProjectionStateKey(StrEnum):
    HOLD = "hold"
    HOLD_AUDIT = "hold_audit"
    HOLD_SOURCE = "source"
    ACTIVE_RUNNER = "active_runner"
    TASK_PLAN = "task_plan"
    TASK_APPROVED = "task_approved"


RECENTLY_DELIVERED_HOURS = 168
READY_BAND = "ready"
IN_PREP_BAND = "in_prep"


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


def _public_hold_source(hold_audit: StateValue) -> str | None:
    """What set the hold, as the audit records it; a start\'s reservation mark is internal and reports nothing."""
    if not isinstance(hold_audit, dict):
        return None
    source = hold_audit.get(_ProjectionStateKey.HOLD_SOURCE)
    if not isinstance(source, str) or source == HoldAuditSource.START_RESERVATION:
        return None
    return source


_READ_TO_STORED: dict[Phase | None, LifecyclePhase] = {
    Phase.WORK: LifecyclePhase.WORK,
    Phase.PREPARATION: LifecyclePhase.PREPARATION,
}


READING_WORKERS: Final = 8


def _may_read_ready(state: dict[str, StateValue]) -> bool:
    """Whether the item is stored ``ready`` or carries an admission, the only items whose reading compares the head."""
    workflow = state.get(WORKFLOW_STATE_KEY)
    admitted = isinstance(workflow, dict) and bool(workflow.get("admitted"))
    return state.get("lifecycle_phase") == LifecyclePhase.READY.value or admitted


def _ready_readings(
    store: WorkflowStore, project_path: str, items: Sequence[TodoProjectionItem]
) -> dict[str, PhaseReading]:
    """The machine\'s reading of every item stored ``ready``, the remote reads taken together rather than one by one."""
    ready = [
        (str(item.item_id), item.state)
        for item in items
        if item.state is not None and item.state_error is None and _may_read_ready(item.state)
    ]
    if not ready:
        return {}

    def read(entry: tuple[str, dict[str, StateValue]]) -> tuple[str, PhaseReading | None]:
        slug, state = entry
        return slug, stored_ready_reading(store, project_path, slug, state)

    with ThreadPoolExecutor(max_workers=READING_WORKERS) as pool:
        results = list(pool.map(read, ready))
    return {slug: reading for slug, reading in results if reading is not None}


def _read_lifecycle(stored: LifecyclePhase, reading: PhaseReading | None) -> LifecyclePhase:
    """The phase the item reads, in the stored vocabulary, when the machine\'s reading moved a stored ``ready``.

    A stamp the integration head has moved past reads ``work`` (or ``preparation`` for a carried stamp nobody holds);
    the projection reports that, not the stored value, so the list and the item\'s detail say the same thing.
    """
    if reading is None or stored is not LifecyclePhase.READY:
        return stored
    return _READ_TO_STORED.get(reading.phase, stored)


def _non_empty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _prepared_session_id(state: dict[str, StateValue]) -> str | None:
    """The session that completed the item's preparation.

    The record of the lifecycle machine is the authority when it holds a prepared revision: the session that performed
    the prepared act. Otherwise the value stored before that machine is published as it was.
    """
    prepared = workflow_record_of(state).prepared
    if prepared is not None:
        return _non_empty_str(prepared.session_id)
    return _non_empty_str(state.get(PREPARED_SESSION_ID_STATE_KEY))


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
    local/projects/teleclaude/spec/feature/workflow/todo-management#known-caveats), and a
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


def _apply_delivered_holder_labels(todos: list[TodoDTO], holder_slug_by_id: dict[str, str]) -> list[TodoDTO]:
    """Project group context and latest delivery from visible delivered children."""
    visible = [
        todo for todo in todos if not (todo.status == TodoStatus.DELIVERED and todo.todo_id in holder_slug_by_id)
    ]
    children_by_holder: dict[str, list[TodoDTO]] = {}
    for todo in visible:
        if todo.status == TodoStatus.DELIVERED and todo.group_id and todo.group_id in holder_slug_by_id:
            children_by_holder.setdefault(todo.group_id, []).append(todo)

    stubs = [
        TodoDTO(
            slug=holder_slug_by_id[holder_id],
            status=TodoStatus.DELIVERED.value,
            has_requirements=False,
            has_impl_plan=False,
            todo_id=holder_id,
            delivered_at=max((child.delivered_at for child in children if child.delivered_at), default=None),
        )
        for holder_id, children in children_by_holder.items()
    ]
    return [*visible, *stubs]


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


def _derive_projection_fields(
    slug: str,
    raw_status: str,
    state: dict[str, StateValue] | None,
    *,
    artifact_write_timestamps: dict[str, str],
    reading: PhaseReading | None = None,
) -> _ProjectionFields:
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

    kind = TodoState.model_validate(state).kind

    finalize_raw = state.get("finalize")
    finalize = finalize_raw if isinstance(finalize_raw, dict) else {}
    finalize_status = _non_empty_str(finalize.get("status"))

    lifecycle = require_lifecycle_phase(
        state.get("lifecycle_phase"),
        context=f"assemble_todo_from_db({slug})",
    )
    lifecycle = _read_lifecycle(lifecycle, reading)
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
        prepare_review_verdict_from_state(state, artifact_write_timestamps=artifact_write_timestamps)
        if lifecycle_phase == LifecyclePhase.BLOCKED.value
        else None
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
        kind=kind,
        lifecycle_phase=lifecycle_phase,
    )
    if todo_status == TodoStatus.ACTIVE and build_status:
        todo_status = TodoStatus.IN_PROGRESS
    elif todo_status == TodoStatus.ACTIVE and ready:
        todo_status = TodoStatus.READY
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
    """Assemble the todo list from one typed workflow-store projection read.

    ``delivered_since`` remains a post-derivation display filter so a holder
    whose children delivered outside the window still derives as delivered.
    """
    started_at = time.perf_counter()
    init_started_at = time.perf_counter()
    store = get_workflow_store_sync(project_path)
    init_dt = time.perf_counter() - init_started_at

    if delivered_only:
        statuses: tuple[TodoStatus, ...] = (TodoStatus.DELIVERED,)
    elif icebox_only:
        statuses = (TodoStatus.ICEBOX,)
    elif removed_only:
        statuses = (TodoStatus.REMOVED,)
    else:
        selected = [TodoStatus.ACTIVE]
        if include_icebox:
            selected.append(TodoStatus.ICEBOX)
        if include_delivered:
            selected.append(TodoStatus.DELIVERED)
        if include_removed:
            selected.append(TodoStatus.REMOVED)
        statuses = tuple(selected)

    snapshot = store.read_todo_projection_snapshot_sync(statuses)
    metrics = snapshot.metrics
    delivered_slug_set = {str(item_id) for item_id in snapshot.delivered_items}
    deps_map = {str(item_id): [str(dep) for dep in deps] for item_id, deps in snapshot.dependencies.items()}
    holder_slug_by_id = {str(address): str(slug) for address, slug in snapshot.structural_group_slugs.items()}

    readings = _ready_readings(store, project_path, snapshot.items)
    todos: list[TodoDTO] = []
    raw_status_by_id: dict[str, str] = {}
    todo_build_total_dt = 0.0
    for item in snapshot.items:
        slug = str(item.item_id)
        row_id = str(item.store_address)
        raw_status = item.status
        raw_status_by_id[row_id] = raw_status
        if item.state_error is not None:
            logger.warning(
                _SKIP_UNREADABLE_STATE_LOG,
                slug=slug,
                project_path=project_path,
                reason=item.state_error,
            )
            continue
        if item.state is None:
            if raw_status == TodoStatus.DELIVERED.value:
                logger.trace(
                    _SKIP_DELIVERED_STATE_LOG,
                    slug=slug,
                    project_path=project_path,
                    todo_id=row_id,
                )
            else:
                logger.warning(
                    _SKIP_MISSING_STATE_LOG,
                    slug=slug,
                    status=raw_status,
                    project_path=project_path,
                    todo_id=row_id,
                )
            continue
        state = item.state
        build_started_at = time.perf_counter()
        artifact_write_timestamps = {
            artifact_name_to_state_key(artifact.name): artifact.updated_at
            for artifact in item.artifact_files
            if artifact.updated_at is not None
        }
        reading = readings.get(slug)
        projection = _derive_projection_fields(
            slug,
            raw_status,
            state,
            artifact_write_timestamps=artifact_write_timestamps,
            reading=reading,
        )
        hold_audit = state.get(_ProjectionStateKey.HOLD_AUDIT)
        held = effective_hold(hold=bool(state.get(_ProjectionStateKey.HOLD)))
        group_slug = holder_slug_by_id.get(str(item.group_address)) if item.group_address is not None else None
        group_id = str(item.group_address) if item.group_address is not None and group_slug is not None else None

        todos.append(
            TodoDTO(
                slug=slug,
                status=projection.todo_status,
                description=item.description or _EMPTY_TEXT,
                has_requirements=item.has_requirements,
                has_impl_plan=item.has_implementation_plan,
                kind=projection.kind,
                ready_since=item.ready_since,
                schedule=item.schedule,
                task_plan_digest=_artifact_digest(state, _ProjectionStateKey.TASK_PLAN),
                task_approved_digest=_approval_digest(state, _ProjectionStateKey.TASK_APPROVED),
                updated_at=item.updated_at,
                created_at=item.created_at,
                build_status=projection.build_status,
                review_status=projection.review_status,
                after=deps_map.get(slug, []),
                group=group_slug,
                group_id=group_id,
                delivered_at=item.delivered_at,
                lifecycle_phase=projection.lifecycle_phase,
                integration_phase=projection.integration_phase,
                finalize_status=projection.finalize_status,
                prepare_review_verdict=projection.prepare_review_verdict,
                hold=bool(state.get(_ProjectionStateKey.HOLD)),
                held=held,
                hold_source=_public_hold_source(hold_audit),
                active_runner=(
                    str(state.get(_ProjectionStateKey.ACTIVE_RUNNER))
                    if isinstance(state.get(_ProjectionStateKey.ACTIVE_RUNNER), str)
                    else None
                ),
                prepared_session_id=_prepared_session_id(state),
                files=[artifact.name for artifact in item.artifact_files],
                artifact_updated_at={
                    artifact.name: artifact.updated_at
                    for artifact in item.artifact_files
                    if artifact.updated_at is not None
                },
                version_total=item.version_total,
                todo_id=row_id,
                removed_at=item.removed_at,
                lineage=item.lineage,
                entry_point=item.entry_point,
                human_involved=item.human_involved,
                context=item.context,
                standing=held_ready_standing(state, reading),
            )
        )
        todo_build_total_dt += time.perf_counter() - build_started_at

    todos = _apply_holder_status(todos, holder_slug_by_id)
    todos = _apply_removed_holder_labels(todos, holder_slug_by_id)
    todos = _apply_icebox_holder_labels(todos, holder_slug_by_id)
    if delivered_since is not None:
        todos = [
            todo
            for todo in todos
            if todo.status != TodoStatus.DELIVERED or (todo.delivered_at and todo.delivered_at >= delivered_since)
        ]
    todos = _apply_delivered_holder_labels(todos, holder_slug_by_id)
    todos = _apply_section_ordering(todos, delivered_slug_set, raw_status_by_id)

    total_dt = time.perf_counter() - started_at
    if total_dt >= 2.0:
        deps_count = sum(len(deps) for deps in snapshot.dependencies.values())
        logger.warning(
            _SLOW_ASSEMBLE_LOG,
            total_dt,
            project_path,
            len(snapshot.items),
            deps_count,
            init_dt,
            metrics.connection_seconds,
            metrics.item_query_seconds,
            metrics.dependency_query_seconds,
            metrics.state_query_seconds,
            metrics.artifact_query_seconds,
            todo_build_total_dt,
            max(
                0.0,
                total_dt
                - init_dt
                - metrics.connection_seconds
                - metrics.item_query_seconds
                - metrics.dependency_query_seconds
                - metrics.state_query_seconds
                - metrics.artifact_query_seconds
                - todo_build_total_dt,
            ),
        )
    return todos
