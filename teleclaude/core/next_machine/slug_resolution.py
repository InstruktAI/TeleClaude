"""Slug resolution — find runnable slugs and manage item phase transitions.

No imports from core.py (circular-import guard).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from teleclaude.core.next_machine._types import ItemPhase, StateValue
from teleclaude.core.next_machine.lifecycle import (
    LifecyclePhase,
    coerce_lifecycle_phase,
    is_ready_for_work,
    lifecycle_phase_index,
)
from teleclaude.core.workflow_machine.dependencies import delivered_slugs, prepared_slugs
from teleclaude.core.workflow_machine.lane import resolve_lane
from teleclaude.core.workflow_machine.phase_reading import in_task_lane, read_phase
from teleclaude.types.lifecycle import TASK_LIFECYCLE_PHASES
from teleclaude.types.todos import TodoState
from teleclaude.types.workflow_record import Phase

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore
from teleclaude.core.next_machine.state_io import read_phase_state, write_phase_state
from teleclaude.core.todos_db._rows import TodoRow
from teleclaude.core.workflow_store.store import get_workflow_store_sync
from teleclaude.core.workflow_store.types import ItemChange

WORK_ENTRY_PHASES: Final = frozenset({Phase.PREPARED, Phase.WORK, Phase.READY})


class HolderResolutionMode(StrEnum):
    """Valid holder child resolution modes."""

    PREPARE = "prepare"
    WORK = "work"


class HolderResolutionReason(StrEnum):
    """Reason codes for holder child resolution outcomes."""

    NOT_HOLDER = "not_holder"
    OK = "ok"
    CHILDREN_NOT_IN_TODO = "children_not_in_todo"
    COMPLETE = "complete"
    DEPS_UNSATISFIED = "deps_unsatisfied"
    ALL_PREPARED = "all_prepared"
    ITEM_NOT_READY = "item_not_ready"


@dataclass(frozen=True)
class HolderChildResolution:
    """Resolved direct children for a holder and the runnable subset."""

    children: tuple[str, ...]
    runnable: tuple[str, ...]
    reason: HolderResolutionReason


async def resolve_slug_async(
    todos_db: WorkflowStore,
    slug: str | None,
    ready_only: bool = False,
    dependencies: dict[str, list[str]] | None = None,
) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or todo list using todos.db.

    Args:
        todos_db: Database instance for state and todo list queries.
        slug: Optional explicit slug.
        ready_only: If True, only match items with current == 'prepared' (for next_work).
        dependencies: Optional dependency graph for dependency gating.

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
    """
    if slug:
        return slug, True, ""

    entries = await todos_db.list_todo()
    delivered = await todos_db.delivered_slugs()
    dependency_delivered = (
        await effective_delivered_slugs_for_dependencies(todos_db, delivered) if dependencies is not None else delivered
    )

    for entry in entries:
        found_slug = entry["slug"]
        phase = await _get_item_phase_db(todos_db, found_slug, delivered)

        if phase == ItemPhase.DONE.value:
            continue

        is_ready = await _is_ready_for_work_db(
            todos_db, found_slug, legacy_in_progress=phase == ItemPhase.IN_PROGRESS.value
        )

        if ready_only and not is_ready:
            continue

        if ready_only and dependencies is not None:
            slug_deps = dependencies.get(found_slug, [])
            if slug_deps and not all(d in dependency_delivered for d in slug_deps):
                continue

        return found_slug, is_ready, entry.get("description") or ""

    return None, False, ""


async def _get_item_phase_db(
    todos_db: WorkflowStore,
    slug: str,
    delivered: set[str] | None = None,
) -> str:
    """Get current phase for a work item from todos.db."""
    if delivered is None:
        delivered = await todos_db.delivered_slugs()
    is_delivered = slug in delivered
    is_in_todo = await todos_db.slug_in_todo(slug)

    if is_in_todo:
        state = await todos_db.read_state(slug)
        if state is not None:
            phase = state.get("phase")
            if isinstance(phase, str):
                return phase
        return ItemPhase.PENDING.value
    if is_delivered:
        return ItemPhase.DONE.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in the todo list. Cannot determine phase."
    raise ValueError(msg)


async def _is_ready_for_work_db(todos_db: WorkflowStore, slug: str, *, legacy_in_progress: bool = False) -> bool:
    """DB-backed wrapper around the canonical readiness gate."""
    state = await todos_db.read_state(slug)
    if state is None:
        return False
    todo_state = TodoState.model_validate(state)
    if in_task_lane(todo_state):
        ready, _ = is_ready_for_work(kind=todo_state.kind, lifecycle_phase=todo_state.lifecycle_phase.value)
        return legacy_in_progress or ready
    lane = await resolve_lane(todos_db, str(todos_db.project_root), slug, state, todo_state)
    return read_phase(todo_state, lane).phase in WORK_ENTRY_PHASES


def deps_satisfied(dependencies: dict[str, list[str]], satisfied_set: set[str], slug: str) -> bool:
    """Return whether all todo dependencies for ``slug`` are in ``satisfied_set``."""
    slug_deps = dependencies.get(slug, [])
    return not slug_deps or all(dep in satisfied_set for dep in slug_deps)


def _children_by_group(entries: list[TodoRow]) -> dict[str, list[str]]:
    """Index group_id children from todo rows, keyed by the holder's slug.

    ``entries`` must include the holder rows themselves (status ``holder``)
    for the id→slug resolution to succeed — callers pass a row set fetched
    with holders included.
    """
    slug_by_id = {entry["id"]: entry["slug"] for entry in entries}
    children: dict[str, list[str]] = {}
    for entry in entries:
        group_id = entry.get("group_id")
        holder_slug = slug_by_id.get(group_id) if group_id else None
        if holder_slug:
            children.setdefault(holder_slug, []).append(entry["slug"])
    for grouped in children.values():
        grouped.sort()
    return children


async def _resolve_holder_children_from_entries(
    _todos_db: WorkflowStore,
    holder_slug: str,
    grouped_children: dict[str, list[str]],
) -> list[str]:
    """Resolve holder children from preloaded todo grouping rows."""
    return list(grouped_children.get(holder_slug, []))


async def effective_delivered_slugs_for_dependencies(
    todos_db: WorkflowStore,
    delivered: set[str] | None = None,
) -> set[str]:
    """Return raw delivered slugs plus holders whose children are all delivered.

    Holder rows do not carry their own lifecycle status. For dependency gating,
    a holder dependency is satisfied when every direct child has delivered; this
    mirrors the todo list projection without mutating the holder row itself.
    """
    return await delivered_slugs(todos_db, delivered)


async def effective_prepared_slugs_for_dependencies(
    todos_db: WorkflowStore,
    delivered: set[str] | None = None,
) -> set[str]:
    """Return delivered/prepared slugs plus holders whose children are all prepared."""
    return await prepared_slugs(todos_db, delivered)


async def _is_prepare_runnable_lifecycle(
    todos_db: WorkflowStore, slug: str, state: dict[str, StateValue] | None
) -> bool:
    """Return True when a child still needs prepare and can be targeted by prepare."""
    if state is None:
        return False
    phase = coerce_lifecycle_phase(state.get("lifecycle_phase"))
    if phase is None:
        return False
    if phase in TASK_LIFECYCLE_PHASES:
        return phase is LifecyclePhase.TASK_PLAN_DRAFTING
    todo_state = TodoState.model_validate(state)
    if in_task_lane(todo_state):
        return lifecycle_phase_index(phase) < lifecycle_phase_index(LifecyclePhase.PREPARED)
    lane = await resolve_lane(todos_db, str(todos_db.project_root), slug, state, todo_state)
    return read_phase(todo_state, lane).phase is Phase.PREPARATION


async def set_item_phase_db(todos_db: WorkflowStore, slug: str, phase: str) -> None:
    """Set phase for a work item in todos.db."""

    def mutate(current: dict[str, StateValue] | None, _digests: Mapping[str, str]) -> ItemChange | None:
        stored = current or {}
        if stored.get("phase") == phase:
            return None
        return ItemChange(state={**stored, "phase": phase})

    await todos_db.commit_item_change(slug, expect_digests={}, mutate=mutate, updated_by=None)


async def resolve_holder_children_db(todos_db: WorkflowStore, holder_slug: str) -> list[str]:
    """Resolve container/holder child slugs from DB todo grouping."""
    entries = await todos_db.list_todo(include_delivered=True, include_holders=True)
    return await _resolve_holder_children_from_entries(todos_db, holder_slug, _children_by_group(entries))


async def resolve_runnable_holder_children_db(
    todos_db: WorkflowStore,
    holder_slug: str,
    dependencies: dict[str, list[str]],
    *,
    mode: HolderResolutionMode,
) -> HolderChildResolution:
    """Resolve runnable direct children for a holder in prepare or work mode."""
    children = await resolve_holder_children_db(todos_db, holder_slug)
    if not children:
        return HolderChildResolution(children=(), runnable=(), reason=HolderResolutionReason.NOT_HOLDER)

    entries = await todos_db.list_todo()
    active_slugs = {entry["slug"] for entry in entries}
    delivered = await todos_db.delivered_slugs()
    dependency_satisfied = (
        await effective_prepared_slugs_for_dependencies(todos_db, delivered)
        if mode is HolderResolutionMode.PREPARE
        else await effective_delivered_slugs_for_dependencies(todos_db, delivered)
    )
    runnable: list[str] = []
    has_children_in_todo = False
    has_incomplete_children = False
    has_deps_blocked = False
    has_not_ready = False
    has_unprepared_child = False

    for child in children:
        if child in delivered:
            has_children_in_todo = True
            continue
        if child not in active_slugs:
            continue

        has_children_in_todo = True
        phase = await _get_item_phase_db(todos_db, child, delivered)
        if phase == ItemPhase.DONE.value:
            continue

        has_incomplete_children = True
        if mode is HolderResolutionMode.PREPARE:
            state = await todos_db.read_state(child)
            if not await _is_prepare_runnable_lifecycle(todos_db, child, state):
                has_not_ready = True
                task_lane = state is not None and in_task_lane(TodoState.model_validate(state))
                if not task_lane and child not in dependency_satisfied:
                    has_unprepared_child = True
                continue
        else:
            is_ready = await _is_ready_for_work_db(
                todos_db, child, legacy_in_progress=phase == ItemPhase.IN_PROGRESS.value
            )
            if not is_ready:
                has_not_ready = True
                continue

        if not deps_satisfied(dependencies, dependency_satisfied, child):
            has_deps_blocked = True
            continue

        runnable.append(child)

    if runnable:
        return HolderChildResolution(
            children=tuple(children), runnable=tuple(runnable), reason=HolderResolutionReason.OK
        )
    if not has_children_in_todo:
        return HolderChildResolution(
            children=tuple(children), runnable=(), reason=HolderResolutionReason.CHILDREN_NOT_IN_TODO
        )
    if not has_incomplete_children:
        return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.COMPLETE)
    if has_deps_blocked:
        return HolderChildResolution(
            children=tuple(children), runnable=(), reason=HolderResolutionReason.DEPS_UNSATISFIED
        )
    if mode is HolderResolutionMode.PREPARE and has_not_ready and not has_unprepared_child:
        return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.ALL_PREPARED)
    return HolderChildResolution(children=tuple(children), runnable=(), reason=HolderResolutionReason.ITEM_NOT_READY)


# ── Legacy sync functions (retained for callers not yet migrated) ────────


def get_item_phase(cwd: str, slug: str) -> str:
    """Sync legacy: resolve item phase using todos.db-backed state."""
    todos_db = get_workflow_store_sync(cwd)
    delivered = todos_db.delivered_slugs_sync()
    is_delivered = slug in delivered
    is_in_todo = todos_db.resolve_store_address_sync(slug) is not None

    if is_in_todo:
        state = todos_db.read_state_sync(slug)
        if state is not None:
            phase = state.get("phase")
            if isinstance(phase, str) and phase:
                return phase
        return ItemPhase.PENDING.value
    if is_delivered:
        return ItemPhase.DONE.value

    msg = f"Slug '{slug}' has no state in DB, is not delivered, and is not in the todo list. Cannot determine phase."
    raise ValueError(msg)


async def slug_in_todo(todos_db: WorkflowStore, slug: str) -> bool:
    """Compatibility shim for callers/tests that still patch module-level todo checks."""
    return await todos_db.slug_in_todo(slug)


def set_item_phase(cwd: str, slug: str, phase: str) -> None:
    """Sync legacy: set item phase on filesystem. Use set_item_phase_db for new code."""
    state = read_phase_state(cwd, slug)
    state["phase"] = phase

    def merge(stored: dict[str, StateValue]) -> dict[str, StateValue]:
        return {**stored, "phase": phase}

    write_phase_state(cwd, slug, state, merge=merge)


__all__ = [
    "HolderChildResolution",
    "HolderResolutionMode",
    "HolderResolutionReason",
    "_get_item_phase_db",
    "_is_ready_for_work_db",
    "deps_satisfied",
    "effective_delivered_slugs_for_dependencies",
    "effective_prepared_slugs_for_dependencies",
    "get_item_phase",
    "resolve_holder_children_db",
    "resolve_runnable_holder_children_db",
    "resolve_slug_async",
    "set_item_phase",
    "set_item_phase_db",
    "slug_in_todo",
]
